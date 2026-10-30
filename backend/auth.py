"""
V2.0 鉴权：PBKDF2 口令散列 + HMAC 签名 Token（无第三方依赖）。
Token 形如 base64url(payload).hexsignature，payload 含 uid/role/exp。
生产环境请通过环境变量 AUTH_SECRET 覆盖默认密钥。
"""
import os, json, time, hmac, hashlib, base64
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User

SECRET = os.getenv("AUTH_SECRET", "admb-dev-secret-change-me").encode()
TTL_SECONDS = int(os.getenv("AUTH_TTL_HOURS", "12")) * 3600
PBKDF2_ROUNDS = 120_000


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    salt = salt or base64.urlsafe_b64encode(os.urandom(12)).decode()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return base64.b64encode(h).decode(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    calc, _ = hash_password(password, salt)
    return hmac.compare_digest(calc, password_hash)


def create_token(user: User) -> dict:
    payload = {"uid": user.id, "role": user.role, "sub": user.username,
               "exp": int(time.time()) + TTL_SECONDS}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return {"token": f"{body}.{sig}", "expires_in": TTL_SECONDS, "user": _user_dict(user)}


def decode_token(token: str) -> Optional[dict]:
    try:
        body, sig = token.rsplit(".", 1)
        expect = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        pad = "=" * (-len(body) % 4)
        data = json.loads(base64.urlsafe_b64decode(body + pad))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def _user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "role": u.role, "active": bool(u.active)}

# 对外别名
user_dict = _user_dict


def _extract(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    return authorization[7:] if authorization.lower().startswith("bearer ") else authorization


def optional_user(authorization: Optional[str] = Header(None),
                  db: Session = Depends(get_db)) -> Optional[User]:
    payload = decode_token(_extract(authorization) or "")
    if not payload:
        return None
    u = db.query(User).filter_by(id=payload["uid"], active=True).first()
    return u


def current_user(authorization: Optional[str] = Header(None),
                 db: Session = Depends(get_db)) -> User:
    u = optional_user(authorization, db)
    if not u:
        raise HTTPException(401, "未登录或登录已过期")
    return u


def require_roles(*roles: str):
    """角色门禁：admin 始终放行。"""
    def dep(user: User = Depends(current_user)) -> User:
        if user.role != "admin" and user.role not in roles:
            raise HTTPException(403, f"需要角色：{'/'.join(roles)}")
        return user
    return dep


ROLE_LABELS = {
    "admin": "管理员（全权限：用户/规格/模型/审阅）",
    "manager": "投放经理（审阅、规格维护、生成导出）",
    "editor": "投放执行（生成、重生成、导出）",
    "viewer": "只读（查看素材与报表）",
}
ROLES = tuple(ROLE_LABELS.keys())
CAN_EDIT = ("admin", "manager", "editor")
CAN_REVIEW = ("admin", "manager")
CAN_ADMIN = ("admin",)
