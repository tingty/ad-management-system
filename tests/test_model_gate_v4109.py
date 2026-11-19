"""V4.109 模型闸门口径：用途并集 + 未就绪原因细分。

背景（真实环境误判）：工作坊把「图片模型」判成「未配置」，而配置页里明明有一条图片
模型。两个成因：
1. `usages` 为空数组时会盖掉仍有内容的 `usage` 列，配置在选路时被整体跳过；
2. 未就绪原因只有一句「未配置」，把「配了但没点测试 / 测试没过 / 被停用 / 要素不全」
   全都读成「系统看不到这条配置」。

覆盖：
- `usages` 与 `usage` 取并集、去重保序；
- 空 `usages` 的旧配置仍能被选中；
- 未就绪原因逐态可区分，并带上该用途的候选条数；
- 真实环境的排查入口（只读诊断脚本）存在且不写库；
- 工作坊前端把原因显示出来。

无模型 / 无网络 / 不写库。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

import workshop  # noqa: E402
from providers import _pick_config, _usages_of  # noqa: E402


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _DB:
    """最小替身：只实现 `query(...).all()`，不连数据库。"""

    def __init__(self, rows):
        self.rows = list(rows)

    def query(self, *_a, **_k):
        return _Rows(self.rows)


def _cfg(cid, usage=None, usages=None, *, active=True, key="sk-x",
         base="https://api.example.com/v1", model="m-1", ok=None, name=None):
    from models import ModelConfig
    c = ModelConfig()
    c.id = cid
    c.name = name if name is not None else f"配置{cid}"
    c.usage = usage
    c.usages = usages
    c.provider = "openai"
    c.api_key = key
    c.base_url = base
    c.model = model
    c.params = {}
    c.is_active = active
    c.last_test_ok = ok
    c.last_test_at = None
    return c


class TestModelGateV4109(unittest.TestCase):

    # ---------- 用途解析 ----------
    def test_01_usages_union_not_either_or(self):
        # 旧配置：只有 usage 列
        self.assertEqual(_usages_of(_cfg(1, usage="image")), ["image"])
        # 新配置：只有 usages 数组
        self.assertEqual(_usages_of(_cfg(2, usages=["analysis", "copy"])),
                         ["analysis", "copy"])
        # 关键回归：usages 为空数组时不得丢掉 usage
        self.assertEqual(_usages_of(_cfg(3, usage="image", usages=[])), ["image"])
        # 两列有交集也不重复
        self.assertEqual(_usages_of(_cfg(4, usage="copy", usages=["copy", "image"])),
                         ["copy", "image"])

    def test_02_legacy_image_config_is_picked(self):
        rows = [_cfg(1, usage="image", usages=[], ok=True, model="wanx-v1")]
        picked = _pick_config(rows, "image")
        self.assertIsNotNone(picked, "usages 为空数组的旧图片配置必须仍能被选中")
        self.assertEqual(picked.model, "wanx-v1")

    def test_03_inactive_or_incomplete_is_not_picked(self):
        self.assertIsNone(_pick_config([_cfg(1, usage="image", active=False, ok=True)], "image"))
        self.assertIsNone(_pick_config([_cfg(2, usage="image", key="", ok=True)], "image"))

    # ---------- 未就绪原因 ----------
    def test_04_reason_not_configured(self):
        st = workshop.model_status(_DB([]))
        img = [i for i in st["items"] if i["usage"] == "image"][0]
        self.assertEqual(img["reason"], "未配置")
        self.assertEqual(img["candidates"], 0)
        self.assertFalse(img["ready"])
        self.assertTrue(st["missing"])

    def test_05_reason_disabled(self):
        rows = [_cfg(1, usage="image", active=False)]
        img = [i for i in workshop.model_status(_DB(rows))["items"] if i["usage"] == "image"][0]
        self.assertEqual(img["reason"], "已配置但已停用")
        self.assertEqual(img["candidates"], 1, "配了但停用：候选数应为 1，不是 0")

    def test_06_reason_incomplete(self):
        rows = [_cfg(1, usage="image", model="")]
        img = [i for i in workshop.model_status(_DB(rows))["items"] if i["usage"] == "image"][0]
        self.assertIn("配置不完整", img["reason"])

    def test_07_reason_untested_vs_failed(self):
        untested = [_cfg(1, usage="image", ok=None)]
        img = [i for i in workshop.model_status(_DB(untested))["items"] if i["usage"] == "image"][0]
        self.assertEqual(img["reason"], "尚未测试通过")
        self.assertNotEqual(img["reason"], "未配置", "配了没测不等于没配")

        failed = [_cfg(2, usage="image", ok=False)]
        img = [i for i in workshop.model_status(_DB(failed))["items"] if i["usage"] == "image"][0]
        self.assertEqual(img["reason"], "最近一次连通测试未通过")

    def test_08_ready_only_when_verified(self):
        rows = [_cfg(1, usage="analysis", usages=["analysis", "copy"], ok=True),
                _cfg(2, usage="image", usages=["image"], ok=True, model="gpt-image-1")]
        st = workshop.model_status(_DB(rows))
        self.assertTrue(st["ready"], st["missing"])
        for item in st["items"]:
            self.assertEqual(item["reason"], "")
            self.assertEqual(item["candidates"], 1)

    def test_09_image_untested_degrades_not_blocks(self):
        # 文案就绪、图片未就绪：missing_models 只报图片，文案不被牵连
        rows = [_cfg(1, usage="analysis", usages=["analysis"], ok=True),
                _cfg(2, usage="copy", usages=["copy"], ok=True),
                _cfg(3, usage="image", usages=["image"], ok=None)]
        db = _DB(rows)
        self.assertEqual(workshop.missing_models(db, ["copy"]), [])
        img = workshop.missing_models(db, ["image"])
        self.assertEqual(len(img), 1)
        self.assertEqual(img[0]["reason"], "尚未测试通过")

    # ---------- 真实环境排查入口 ----------
    def test_10_diagnose_script_is_read_only(self):
        p = BACKEND / "model_diagnose.py"
        self.assertTrue(p.exists(), "缺少真实环境诊断脚本")
        src = p.read_text(encoding="utf-8")
        for token in ("SessionLocal", "各用途实际生效的配置", "model_diagnose.py"):
            self.assertIn(token, src)
        for forbidden in ("db.commit(", "db.add(", "db.delete("):
            self.assertNotIn(forbidden, src, "诊断脚本必须只读")

    def test_11_frontend_shows_reason(self):
        page = (FRONTEND / "pages" / "MaterialWorkshop.tsx").read_text(encoding="utf-8")
        for token in ("modelReason", "m.reason", "未就绪（"):
            self.assertIn(token, page)
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("candidates", api)


if __name__ == "__main__":
    unittest.main()
