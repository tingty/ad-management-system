import os
import secrets
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from database import engine, Base, SessionLocal
from models import User, ModelConfig, PromptConfig
from migrations import ensure_schema
from routers import router
from auth import decode_token, hash_password
from services import PROMPT_REGISTRY, sync_prompt_defaults, REMOVED_PROMPT_KEYS
from version import APP_VERSION

app = FastAPI(title="广告管理系统", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 无需登录即可访问的接口（登录、元数据、健康检查、文档）
PUBLIC_PREFIXES = ("/api/auth/login", "/api/health", "/api/auth/roles")

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


# V4.44 / N06：源码不再包含任何固定默认口令（含管理员）。
# 首次初始化时口令来自 `INITIAL_PASSWORD_<USERNAME>` 环境变量；未配置则用 CSPRNG 随机生成，
# 只写入 0600 权限的本地引导文件，绝不打印到日志或提交进仓库。
BOOTSTRAP_FILE = os.path.join(os.path.dirname(__file__), ".bootstrap_credentials")
DEFAULT_USERS = [
    ("leson", "系统管理员", "admin", "leson@recomob.com"),
    ("manager", "投放经理", "manager", None),
    ("editor", "投放执行", "editor", None),
    ("viewer", "只读账号", "viewer", None),
]


def _initial_password(username: str) -> str:
    configured = os.getenv(f"INITIAL_PASSWORD_{username.upper()}", "").strip()
    return configured or secrets.token_urlsafe(18)


def _persist_bootstrap(rows: list[tuple[str, str, str]]) -> str:
    """把一次性初始口令写入本地引导文件（0600）；已存在则追加，不覆盖。"""
    import json
    from datetime import datetime, timezone
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": [{"username": u, "email": e, "initial_password": p}
                     for u, e, p in rows],
        "note": "仅用于首次登录；登录后请立即用 scripts/rotate_admin.py 轮换并删除本文件",
    }
    with open(BOOTSTRAP_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    try:
        os.chmod(BOOTSTRAP_FILE, 0o600)
    except OSError:
        pass
    return BOOTSTRAP_FILE


def seed_users():
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return                      # 已有账号：绝不改写口令 / 重置任何字段
        rows = []
        for username, name, role, email in DEFAULT_USERS:
            pwd = _initial_password(username)
            h, s = hash_password(pwd)
            u = User(username=username, display_name=name, role=role,
                     password_hash=h, salt=s, active=True)
            if email:
                u.email = email
            db.add(u)
            rows.append((username, email or "", pwd))
        db.commit()
        path = _persist_bootstrap(rows)
        print(f"[seed] 已创建初始账号；随机初始口令仅保存在 {path}（0600），"
              "请首次登录后立即轮换并删除该文件")
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


def ensure_default_admin():
    """V4.44 / N06：安全初始化，不再有「命中历史默认口令就重置」的自愈逻辑。

    - 已存在任何启用的 admin：一律不改动用户名 / 邮箱 / 口令 / 角色；
    - 完全没有 admin 时才补建，口令同样来自环境变量或 CSPRNG 随机值；
    - 需要轮换时由管理员显式执行 `scripts/rotate_admin.py`（同时轮换 AUTH_SECRET，
      使既有会话全部失效），源码里不再保存任何固定口令。
    """
    email = os.getenv("DEFAULT_ADMIN_EMAIL", "leson@recomob.com")
    username = os.getenv("DEFAULT_ADMIN_USERNAME", "leson")
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.role == "admin",
                                        User.active.is_(True)).first()
        if existing:
            print(f"[ensure_admin] 已存在管理员，保留当前凭据不做重置：{existing.email or existing.username}")
            return
        pwd = os.getenv("DEFAULT_ADMIN_PASSWORD", "").strip() or secrets.token_urlsafe(18)
        h, s = hash_password(pwd)
        db.add(User(username=username, email=email, display_name="系统管理员",
                    role="admin", password_hash=h, salt=s, active=True))
        db.commit()
        path = _persist_bootstrap([(username, email, pwd)])
        print(f"[ensure_admin] 已补建管理员；初始口令见 {path}（0600），请立即轮换")
    finally:
        db.close()

def seed_prompts():
    """播种系统提示词（key 唯一，已存在不覆盖）；用户可在「素材提示词」页编辑，保存即生效。

    代码里升级了默认提示词时由 sync_prompt_defaults 同步：正文只在库里仍是旧默认时刷新，
    用户编辑过的内容保留。V4.37 会清理已下线「素材管理」模块遗留的提示词行。
    """
    db = SessionLocal()
    try:
        # V4.37：旧模块的提示词不再出现在目录里，库内残留行一并归档清理
        stale = db.query(PromptConfig).filter(PromptConfig.key.in_(REMOVED_PROMPT_KEYS)).all()
        for row in stale:
            db.delete(row)
        if stale:
            db.commit()
            print(f"[seed] 已清理下线模块提示词：{', '.join(r.key for r in stale)}")
        created = []
        for item in PROMPT_REGISTRY:
            if db.query(PromptConfig).filter_by(key=item["key"]).count() == 0:
                db.add(PromptConfig(key=item["key"], name=item["name"], module=item["module"],
                                    category=item.get("category"),
                                    func_type=item.get("func_type"),
                                    usage_type=item.get("usage_type"),
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
    seed_users()
    backfill_user_emails()
    ensure_default_admin()
    seed_prompts()
    seed_default_model()
    # V4.42 / F12：进程重启后把停在 running/queued 的任务标为失败，避免状态永久卡住
    from job_service import recover_interrupted
    n = recover_interrupted()
    if n:
        print(f"[jobs] 重启后回收 {n} 个中断任务（状态已标为 failed，可用分项重试）")


@app.on_event("startup")
async def start_model_health_scheduler():
    """V4.34：启动「每日大模型连通性测试」后台协程（需在建表/补列之后）。"""
    from model_health import start_daily_scheduler
    start_daily_scheduler()


@app.on_event("shutdown")
async def stop_model_health_scheduler():
    from model_health import stop_daily_scheduler
    stop_daily_scheduler()


@app.get("/api/health")
def health():
    return {"service": "ad-material-platform", "status": "ok", "version": app.version}

@app.get("/")
def root():
    return {"service": "ad-material-platform", "status": "ok", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8033)
