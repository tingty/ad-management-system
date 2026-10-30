import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from database import engine, Base, SessionLocal
from models import PlatformSpec, User
from specs_data import PLATFORM_SPECS
from migrations import ensure_schema, normalize_data
from routers import router
from auth import decode_token, hash_password

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

@app.on_event("startup")
def on_startup():
    ensure_schema()   # 建表 + 自动补齐缺失列（避免旧演示库与模型漂移）
    normalize_data()  # 新列数据回填
    seed_specs()
    seed_users()

@app.get("/api/health")
def health():
    return {"service": "ad-material-platform", "status": "ok", "version": app.version}

@app.get("/")
def root():
    return {"service": "ad-material-platform", "status": "ok", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8033)
