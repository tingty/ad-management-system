"""N06：移除源码固定管理员凭据与启动自愈、提供显式轮换入口。"""
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

ROOT = Path(_bootstrap.ROOT)
BACKEND = ROOT / "backend"
MAIN = (BACKEND / "main.py").read_text(encoding="utf-8")
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")


class TestCredentialHygiene(unittest.TestCase):
    def test_01_no_fixed_passwords_in_source(self):
        for bad in ("Tingty@123", "Admin@123", "Manager@123",
                    "Editor@123", "Viewer@123", "admin123"):
            self.assertNotIn(bad, MAIN, bad)

    def test_02_no_legacy_reset_logic(self):
        self.assertNotIn("LEGACY_DEFAULT_PASSWORDS", MAIN)
        self.assertNotIn("is_legacy", MAIN)
        self.assertNotIn("默认管理员已重置", MAIN)

    def test_03_admin_not_mutated_when_exists(self):
        self.assertIn("不做重置", MAIN)
        self.assertIn("return", MAIN[MAIN.index("if existing:"):MAIN.index("if existing:") + 260])

    def test_04_random_initial_password(self):
        self.assertIn("secrets.token_urlsafe", MAIN)
        self.assertIn("INITIAL_PASSWORD_", MAIN)

    def test_05_bootstrap_file_is_ignored(self):
        self.assertIn(".bootstrap_credentials", GITIGNORE)
        self.assertIn(".env", GITIGNORE)

    def test_06_rotate_script_exists_and_rotates_secret(self):
        p = ROOT / "scripts" / "rotate_admin.py"
        self.assertTrue(p.exists())
        s = p.read_text(encoding="utf-8")
        self.assertIn("AUTH_SECRET", s)
        self.assertIn("hash_password", s)
        self.assertIn("失效", s)

    def test_07_no_fixed_password_anywhere_in_backend(self):
        hits = []
        for f in BACKEND.glob("*.py"):
            text = f.read_text(encoding="utf-8")
            for bad in ("Tingty@123.com", "Admin@123.com", "Manager@123"):
                if bad in text:
                    hits.append(f"{f.name}:{bad}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
