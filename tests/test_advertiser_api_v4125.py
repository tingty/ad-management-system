# -*- coding: utf-8 -*-
"""V4.125 · API对接界面改造专项测试。

覆盖：
1. 模板显示名改为「CJ联盟」，底层 code 不变（历史连接免迁移）；
2. 连接表新增状态明细列（HTTP code / 返回条数）与定期任务配置列；
3. 「保存即测试」原子接口、测试回写字段、设置接口规范化；
4. 前端页面收敛为一张列表 + 两个弹窗：标题 / 列头 / 状态浮层 / 保存即测试 / 设置弹窗；
5. 旧版契约仍兼容（菜单标签、Token 加密、开启功能开关）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestTemplateName(unittest.TestCase):
    def test_display_name_changed_but_code_kept(self):
        import advertiser_api as aa
        tpl = aa.template_by_code("cj_publisher_commissions")
        self.assertIsNotNone(tpl)
        self.assertEqual(tpl["name"], "CJ联盟")
        self.assertEqual(tpl["code"], "cj_publisher_commissions")
        self.assertNotIn("发布者佣金明细", tpl["name"])


class TestDataContract(unittest.TestCase):
    def test_connection_model_new_columns(self):
        model = _read("backend/models.py")
        for col in ["last_test_http_code", "last_test_count", "schedule_json"]:
            self.assertIn(col, model, f"模型缺少列 {col}")

    def test_schema_outputs_status_detail_and_schedule(self):
        schema = _read("backend/schemas.py")
        for key in ["last_test_http_code", "last_test_count", "schedule: dict", "schedule: Optional[dict]"]:
            self.assertIn(key, schema)

    def test_router_create_and_test_and_writeback(self):
        routers = _read("backend/routers.py")
        self.assertIn('/connections/create-and-test', routers)
        self.assertIn('_record_test_result(r, result)', routers)
        self.assertIn('r.last_test_http_code = int(result.get("http_code") or 0) or None', routers)
        # V4.131：列表口径改为 PublisherCommission 明细数，不再回退到聚合 count
        self.assertIn('result.get("record_count", result.get("count", 0))', routers)

    def test_schedule_normalization(self):
        import routers
        out = routers._normalize_schedule({
            "enabled": True, "frequency": "bad", "hour": 99,
            "lookback_days": 0, "backfill_days": 999, "evil": "ignored",
        })
        self.assertEqual(out, {
            "enabled": True, "frequency": "daily", "hour": 23,
            "lookback_days": 1, "backfill_days": 365,
        })
        self.assertEqual(routers._normalize_schedule(None), {})


class TestFrontendRefactor(unittest.TestCase):
    def setUp(self):
        self.page = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.api = _read("frontend/src/api.ts")
        self.css = _read("frontend/src/styles.css")

    def test_title_and_top_description_removed(self):
        app = _read("frontend/src/App.tsx")
        self.assertIn("pageTitle: 'API对接', desc: ''", app)
        self.assertNotIn('把广告主 / 联盟的接口沉淀为标准模板', app)
        self.assertNotIn('① 可用模板', self.page)
        self.assertNotIn('③ 定期任务', self.page)
        self.assertNotIn('④ 运行记录', self.page)
        self.assertNotIn('模板固化接口怎么调', self.page)
        self.assertIn('CJ联盟', self.page)

    def test_list_columns_exactly_as_requested(self):
        self.assertIn('<th>NO.</th><th>广告主</th><th>模板</th><th>状态</th><th>设置</th>', self.page)
        self.assertIn('className="ad-no">{c.id}', self.page)
        self.assertIn('className="ad-status', self.page)
        self.assertIn('onClick={() => openSettings(c)}>设置</button>', self.page)

    def test_status_hover_shows_http_detail(self):
        self.assertIn('ad-status-pop', self.page)
        self.assertIn('HTTP ${c.last_test_http_code', self.page)
        self.assertIn('请求成功', self.page)
        self.assertIn('请求失败', self.page)
        self.assertIn('.ad-status-pop', self.css)

    def test_create_modal_has_only_save_submit(self):
        self.assertIn('新建 API 对接', self.page)
        self.assertIn('{saving ? \'保存并测试中…\' : \'保存\'}', self.page)
        self.assertNotIn('测试连接（不保存）', self.page)
        self.assertNotIn('保存为草稿', self.page)
        self.assertIn('createAndTestConnection', self.api)

    def test_settings_modal_has_schedule_options(self):
        for key in ["enabled", "frequency", "hour", "lookback_days", "backfill_days"]:
            self.assertIn(key, self.page)
        self.assertIn('设置 · 定期任务', self.page)
        self.assertIn('重新测试', self.page)


class TestCompatibility(unittest.TestCase):
    def test_legacy_menu_and_flag_unchanged(self):
        app = _read("frontend/src/App.tsx")
        self.assertIn("label: '广告主API'", app)
        self.assertIn("label: '广告主报表'", app)
        ver = _read("backend/version.py")
        self.assertIn('ENABLE_ADVERTISER_DATA = True', ver)

    def test_token_security_unchanged(self):
        page = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertIn('type="password"', page)
        self.assertNotIn('token_mask', page)


if __name__ == "__main__":
    unittest.main()
