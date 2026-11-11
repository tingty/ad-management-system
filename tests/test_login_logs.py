"""V4.47 登录日志：所有账号的登录（成功 / 失败）必须记录账号名称、IP 与时间，且仅管理员可读。"""
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402  环境变量隔离（DATABASE_URL -> 临时 SQLite）

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from database import SessionLocal
from migrations import ensure_schema
from models import User, LoginLog
from auth import hash_password
from main import app  # 触发 on_startup：建表 + 默认管理员

ADMIN_EMAIL = "logintest@recomob.com"
ADMIN_USER = "logintest"
ADMIN_PWD = "TestPwd123"


class TestLoginLogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 确保 login_logs 表存在，并自建一个已知口令的 admin（避免依赖随机口令）
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="LT",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)

    def _login(self, email, pwd, headers=None):
        return self.client.post("/api/auth/login",
                                json={"email": email, "password": pwd}, headers=headers or {})

    def test_01_success_logged_with_account_ip_time(self):
        r = self._login(ADMIN_EMAIL, ADMIN_PWD)
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        logs = self.client.get("/api/login-logs?limit=50",
                               headers={"Authorization": f"Bearer {token}"}).json()
        recs = [l for l in logs if l["success"] and l["username"] == ADMIN_USER]
        self.assertTrue(recs, "成功登录必须写入 login_logs 且管理员可读")
        rec = recs[0]
        self.assertEqual(rec["username"], ADMIN_USER)   # 登陆账号名称
        self.assertTrue(rec["ip"], "必须记录登陆 IP 地址")
        self.assertIsNotNone(rec["created_at"])          # 登陆时间
        self.assertTrue(rec["success"])

    def test_02_failure_logged(self):
        r = self._login(ADMIN_EMAIL, "wrong-password")
        self.assertEqual(r.status_code, 401)
        db = SessionLocal()
        try:
            fails = db.query(LoginLog).filter_by(success=False).all()
            self.assertTrue(fails, "失败登录必须写入 login_logs")
            rec = fails[0]
            self.assertEqual(rec.username, ADMIN_EMAIL)  # 尝试登录的账号
            self.assertTrue(rec.ip)
            self.assertFalse(rec.success)
        finally:
            db.close()

    def test_03_login_logs_admin_only(self):
        # 未携带 token 直接访问应被拒绝
        r = self.client.get("/api/login-logs?limit=10")
        self.assertEqual(r.status_code, 401)

    def test_04_x_forwarded_for_respected(self):
        # Cloudflare Tunnel / Caddy 场景：真实客户端 IP 取自 X-Forwarded-For 第一段
        self._login(ADMIN_EMAIL, ADMIN_PWD,
                    headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
        db = SessionLocal()
        try:
            recs = db.query(LoginLog).filter_by(username=ADMIN_USER, ip="203.0.113.7").all()
            self.assertTrue(recs, "应尊重 X-Forwarded-For 取真实客户端 IP")
        finally:
            db.close()

    def test_05_inactive_user_failure_logged(self):
        # 停用账号登录失败也应记入（尝试的账号名称）
        db = SessionLocal()
        try:
            h, s = hash_password("Inactive123")
            db.add(User(username="inactive1", email="inactive1@recomob.com", display_name="I",
                        role="viewer", password_hash=h, salt=s, active=False))
            db.commit()
        finally:
            db.close()
        r = self._login("inactive1@recomob.com", "Inactive123")
        self.assertEqual(r.status_code, 401)
        db = SessionLocal()
        try:
            rec = db.query(LoginLog).filter_by(username="inactive1@recomob.com").first()
            self.assertIsNotNone(rec, "停用账号尝试登录应被记录")
            self.assertFalse(rec.success)
        finally:
            db.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
