#!/usr/bin/env python3
"""V4.44 / N06：管理员口令轮换 + 既有会话失效（运维显式执行）。

源码里不再保存任何固定管理员口令；首次初始化口令在
`backend/.bootstrap_credentials`（0600）。上线前必须由管理员执行本脚本：

    python3 scripts/rotate_admin.py --username leson
    python3 scripts/rotate_admin.py --username leson --password '你的新口令'
    python3 scripts/rotate_admin.py --username leson --no-rotate-secret  # 不轮换密钥（不推荐）

脚本做两件事：
1. 重置指定账号的 password_hash / salt；
2. 轮换 `backend/.env` 中的 `AUTH_SECRET`（保留其它配置），使所有已签发的
   无状态 token 在重启后立刻失效。删除源码固定口令**不能替代**这一步。

执行后必须重启后端服务；若部署通过环境变量注入 AUTH_SECRET，请同步更新部署配置。
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

ENV_FILE = ROOT / "backend" / ".env"


def rotate_auth_secret() -> str:
    """写入新 AUTH_SECRET，保留 .env 中其它键；返回新密钥长度信息（不回显密钥）。"""
    new_secret = secrets.token_urlsafe(48)
    lines: list[str] = []
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("AUTH_SECRET="):
                continue
            lines.append(line)
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append(f"AUTH_SECRET={new_secret}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    return str(ENV_FILE)


def main() -> int:
    ap = argparse.ArgumentParser(description="轮换管理员口令并失效既有会话")
    ap.add_argument("--username", default="", help="按用户名定位账号")
    ap.add_argument("--email", default="", help="按邮箱定位账号")
    ap.add_argument("--password", default="", help="新口令；留空则随机生成并打印一次")
    ap.add_argument("--no-rotate-secret", action="store_true",
                    help="不轮换 AUTH_SECRET（既有 token 仍有效，仅调试用）")
    args = ap.parse_args()

    if not args.username and not args.email:
        print("ERROR: 请指定 --username 或 --email", file=sys.stderr)
        return 2

    from database import SessionLocal
    from models import User
    from auth import hash_password

    pwd = args.password.strip() or secrets.token_urlsafe(20)
    db = SessionLocal()
    try:
        q = db.query(User)
        u = (q.filter(User.email == args.email).first() if args.email
             else q.filter(User.username == args.username).first())
        if not u:
            print("ERROR: 未找到账号", file=sys.stderr)
            return 1
        h, s = hash_password(pwd)
        u.password_hash, u.salt = h, s
        u.active = True
        db.commit()
        who = u.email or u.username
    finally:
        db.close()

    print(f"[ok] 已轮换账号口令：{who}")
    if not args.password.strip():
        print(f"[ok] 随机新口令（只显示这一次，请立即保存）：{pwd}")
    if args.no_rotate_secret:
        print("[warn] 未轮换 AUTH_SECRET：既有 token 仍有效，不建议在生产使用")
    else:
        path = rotate_auth_secret()
        print(f"[ok] 已轮换 AUTH_SECRET → {path}（0600）；重启服务后所有既有会话失效")
    print("[next] 1) 重启后端  2) 删除 backend/.bootstrap_credentials  "
          "3) 若部署用环境变量注入 AUTH_SECRET，同步更新部署配置")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
