import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from database import engine, Base, SessionLocal
from models import PlatformSpec, User, ModelConfig, PromptConfig
from specs_data import PLATFORM_SPECS
from migrations import ensure_schema, normalize_data
from routers import router
from auth import decode_token, hash_password
from services import PROMPT_REGISTRY, sync_prompt_defaults

app = FastAPI(title="广告管理系统", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 无需登录即可访问的接口（登录、元数据、健康检查、文档）
PUBLIC_PREFIXES = ("/api/auth/login", "/api/meta", "/api/health", "/api/auth/roles")

@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """统一鉴权：/api/* 默认需要 Bearer Token；静态素材与文档页面放行。"""
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api"):
        return await call_next(request)
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    raw = request.headers.get("authorization")
    token = raw[7:] if raw and raw.lower().startswith("bearer ") else raw
    if not token:
        token = request.query_params.get("token")   # 浏览器直链下载/导出无法带 Header，允许查询参数
    if not decode_token(token or ""):
        return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
    return await call_next(request)

app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")
app.include_router(router)

# ---------------- 默认大模型 ----------------
# 轻量加载 backend/.env（已被 .gitignore 忽略，不进仓库）：已存在的环境变量优先。
def _load_dotenv():
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


_load_dotenv()

# 默认模型：analysis / copy 两个文本用途共用；值可用 .env 或部署环境变量覆盖。
# 密钥不写死在代码里——DEFAULT_LLM_API_KEY 为空时跳过播种，系统自动退回本地 Mock。
DEFAULT_LLM = {
    "provider": os.getenv("DEFAULT_LLM_PROVIDER", "千问大模型"),
    "base_url": os.getenv("DEFAULT_LLM_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "model": os.getenv("DEFAULT_LLM_MODEL", "qwen-plus"),
    "api_key": os.getenv("DEFAULT_LLM_API_KEY", ""),
    "params": {"temperature": 0.7, "max_tokens": 4096},
}


def seed_default_model():
    """为 analysis / copy 播种默认大模型并默认启用；已有配置不覆盖，用户可在设置页改/加。"""
    if not DEFAULT_LLM["api_key"]:
        print("[seed] 未配置 DEFAULT_LLM_API_KEY，跳过默认模型播种（使用本地 Mock）")
        return
    db = SessionLocal()
    try:
        created = []
        for usage in ("analysis", "copy"):
            if db.query(ModelConfig).filter_by(usage=usage).count() == 0:
                db.add(ModelConfig(usage=usage, provider=DEFAULT_LLM["provider"],
                                   api_key=DEFAULT_LLM["api_key"],
                                   base_url=DEFAULT_LLM["base_url"],
                                   model=DEFAULT_LLM["model"],
                                   params=DEFAULT_LLM["params"], is_active=True))
                created.append(usage)
        if created:
            db.commit()
            print(f"[seed] 默认大模型已启用：{DEFAULT_LLM['provider']} / {DEFAULT_LLM['model']} @ "
                  f"{DEFAULT_LLM['base_url']}（{', '.join(created)}）")
    finally:
        db.close()


DEFAULT_USERS = [
    ("admin", "Admin@123", "系统管理员", "admin"),
    ("manager", "Manager@123", "投放经理", "manager"),
    ("editor", "Editor@123", "投放执行", "editor"),
    ("viewer", "Viewer@123", "只读账号", "viewer"),
]

def seed_users():
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            for username, pwd, name, role in DEFAULT_USERS:
                h, s = hash_password(pwd)
                db.add(User(username=username, display_name=name, role=role,
                            password_hash=h, salt=s, active=True))
            db.commit()
            print("[seed] 默认账号已创建：admin / manager / editor / viewer")
    finally:
        db.close()


def backfill_user_emails():
    """历史账号（无邮箱）补填邮箱，使其可用邮箱登录：<username>@example.com。"""
    db = SessionLocal()
    try:
        changed = []
        for u in db.query(User).filter(User.email.is_(None)).all():
            cand = f"{u.username}@example.com"
            if db.query(User).filter(User.email == cand).first():
                cand = f"{u.username}.{u.id}@example.com"
            u.email = cand
            changed.append(cand)
        if changed:
            db.commit()
            print(f"[seed] 已为 {len(changed)} 个历史账号补填邮箱（用于邮箱登录）")
    finally:
        db.close()

def seed_specs():
    db = SessionLocal()
    try:
        if db.query(PlatformSpec).count() == 0:
            for s in PLATFORM_SPECS:
                db.add(PlatformSpec(**s))
            db.commit()
            print("[seed] platform_specs 已初始化")
    finally:
        db.close()

def seed_prompts():
    """播种系统提示词（key 唯一，已存在不覆盖）；用户可在「提示词管理」页编辑，保存即生效。

    代码里升级了默认提示词时由 sync_prompt_defaults 同步：正文只在库里仍是旧默认时刷新，
    用户编辑过的内容保留。
    """
    db = SessionLocal()
    try:
        created = []
        for item in PROMPT_REGISTRY:
            if db.query(PromptConfig).filter_by(key=item["key"]).count() == 0:
                db.add(PromptConfig(key=item["key"], name=item["name"], module=item["module"],
                                    description=item["description"], content=item["content"],
                                    is_active=True))
                created.append(item["key"])
        if created:
            db.commit()
            print(f"[seed] 系统提示词已初始化：{', '.join(created)}")
        updated = sync_prompt_defaults(db)
        if updated:
            print(f"[seed] 系统提示词默认值已升级：{', '.join(updated)}")
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    ensure_schema()   # 建表 + 自动补齐缺失列（避免旧演示库与模型漂移）
    normalize_data()  # 新列数据回填
    seed_specs()
    seed_users()
    backfill_user_emails()
    seed_prompts()
    seed_default_model()

@app.get("/api/health")
def health():
    return {"service": "ad-material-platform", "status": "ok", "version": app.version}

@app.get("/")
def root():
    return {"service": "ad-material-platform", "status": "ok", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8033)
