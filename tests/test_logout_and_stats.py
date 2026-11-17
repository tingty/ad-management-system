"""V4.86 日志模块：登录/登出均记录（账号/IP/时间），统计为全表真实口径。"""
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402  环境变量隔离（DATABASE_URL -> 临时 SQLite）

from fastapi.testclient import TestClient

from database import SessionLocal
from migrations import ensure_schema
from models import User, LoginLog
from auth import hash_password
from main import app  # 触发 on_startup：建表 + 默认管理员

ADMIN_EMAIL = "logouttest@recomob.com"
ADMIN_USER = "logouttest"
ADMIN_PWD = "TestPwd123"


class TestLogoutAndStats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()  # 兼容旧库：自动补 login_logs.action 列
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

    def _login(self, xff=None):
        headers = {}
        if xff:
            headers["X-Forwarded-For"] = xff
        r = self.client.post("/api/auth/login",
                             json={"email": ADMIN_EMAIL, "password": ADMIN_PWD},
                             headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        out = {"Authorization": f"Bearer {r.json()['token']}"}
        if xff:
            out["X-Forwarded-For"] = xff
        return out

    def _stats(self, headers):
        r = self.client.get("/api/log-stats", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_01_login_action_ip_time(self):
        self._login(xff="198.51.100.23, 10.0.0.1")
        db = SessionLocal()
        try:
            rec = db.query(LoginLog).filter_by(
                username=ADMIN_USER, action="login", ip="198.51.100.23").order_by(
                LoginLog.id.desc()).first()
            self.assertIsNotNone(rec, "登录必须落库 action=login 与真实 IP")
            self.assertIsNotNone(rec.created_at, "必须记录登录时间")
        finally:
            db.close()

    def test_02_logout_logged_with_ip_time(self):
        h = self._login(xff="198.51.100.44, 10.0.0.1")
        r = self.client.post("/api/auth/logout", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        db = SessionLocal()
        try:
            rec = db.query(LoginLog).filter_by(
                username=ADMIN_USER, action="logout", ip="198.51.100.44").order_by(
                LoginLog.id.desc()).first()
            self.assertIsNotNone(rec, "登出必须落库且记录账号/IP/时间")
            self.assertIsNotNone(rec.created_at)
            self.assertTrue(rec.success)
            self.assertEqual((rec.detail or {}).get("event"), "logout")
        finally:
            db.close()

    def test_03_logout_requires_auth(self):
        r = self.client.post("/api/auth/logout")
        self.assertEqual(r.status_code, 401, "未登录不得调用登出（无法确认用户）")

    def test_04_action_filter(self):
        h = self._login()
        self.client.post("/api/auth/logout", headers=h)
        logins = self.client.get("/api/login-logs?limit=2000&action=login", headers=h).json()
        logouts = self.client.get("/api/login-logs?limit=2000&action=logout", headers=h).json()
        self.assertTrue(logins and logouts, "两类事件都应可筛选")
        self.assertTrue(all(x["action"] == "login" for x in logins))
        self.assertTrue(all(x["action"] == "logout" for x in logouts))
        self.assertTrue(all(x["ip"] and x["created_at"] for x in logouts))

    def test_05_stats_are_full_table_not_paged(self):
        h = self._login()
        before = self._stats(h)
        h2 = self._login()                       # 一次登录
        self.client.post("/api/auth/logout", headers=h2)  # 一次登出
        after = self._stats(h)
        self.assertEqual(after["login_total"], before["login_total"] + 2)
        # login_count 只数登录事件：本次新增 1 次登录 + 1 次登出
        self.assertEqual(after["login_count"], before["login_count"] + 1)
        self.assertEqual(after["logout_count"], before["logout_count"] + 1)
        self.assertEqual(after["login_success"], before["login_success"] + 2)
        self.assertEqual(after["audit_total"], before["audit_total"])
        # 列表用小 limit，条数远小于统计总数 —— 标题必须用 stats 而非列表长度
        small = self.client.get("/api/login-logs?limit=1", headers=h).json()
        self.assertEqual(len(small), 1)
        self.assertGreater(after["login_total"], 1)

    def test_06_failed_login_counted_in_stats(self):
        h = self._login()
        before = self._stats(h)
        r = self.client.post("/api/auth/login",
                             json={"email": ADMIN_EMAIL, "password": "wrong-password"})
        self.assertEqual(r.status_code, 401)
        after = self._stats(h)
        self.assertEqual(after["login_fail"], before["login_fail"] + 1)
        self.assertEqual(after["login_total"], before["login_total"] + 1)

    def test_07_stats_admin_only(self):
        r = self.client.get("/api/log-stats")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
