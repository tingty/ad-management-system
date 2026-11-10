"""测试环境隔离：任何 backend 模块导入之前先执行本文件。

- 强制清空默认模型密钥，杜绝测试中读取 .env 后发起真实付费调用；
- 把 DATABASE_URL 指到临时目录，绝不触碰生产 / 演示数据库；
- 只读地把 backend 加入 sys.path，不启动 FastAPI、不跑 startup 播种。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

os.environ["DEFAULT_LLM_API_KEY"] = ""
os.environ["DEFAULT_LLM_BASE_URL"] = ""
os.environ["AD_MATERIAL_TEST_MODE"] = "1"
_TMP = tempfile.mkdtemp(prefix="admp_tests_")
os.environ.setdefault("TEST_TMP_DIR", _TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/regression.db"

TEST_TMP_DIR = _TMP
