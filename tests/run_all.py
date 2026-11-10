#!/usr/bin/env python3
"""V4.44 / N06：一键运行可复现回归测试（仅标准库，无需 pytest / 无需网络）。

    python3 tests/run_all.py

测试在临时 SQLite 数据库中运行，强制清空默认模型密钥，不修改生产 / 演示数据，
不发起任何真实付费模型或文生图调用。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> int:
    suite = unittest.TestLoader().discover(str(HERE), pattern="test_*.py", top_level_dir=str(HERE))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("=" * 68)
    print(f"回归结果：运行 {result.testsRun} 项，失败 {len(result.failures)}，"
          f"错误 {len(result.errors)}，跳过 {len(result.skipped)}")
    print("状态：模拟 / 纯函数 / 临时数据库测试通过；"
          "真实模型验证与真实投放验证均为「未验证」，不得互相替代。")
    print("=" * 68)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
