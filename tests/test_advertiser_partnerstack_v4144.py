# -*- coding: utf-8 -*-
"""V4.144 · PartnerStack 模板「按官方文档只填 API Key」契约专项测试。

用户决议：模板名称就是 partnerstack，字段要求必须来自文档说明的请求方式与
必要信息，不得沿用 CJ / Awin 的「Token + CID + Endpoint」三元结构。

官方 Partner API：GET https://api.partnerstack.com/api/v2/rewards
  - 唯一必要信息：Authorization: Bearer <Partner API Key>
  - 全部 query 参数都是可选筛选，无必填 CID / publisherId
  - 响应：data.items[] / data.has_more / data.total
"""
import os
import sys
import tempfile
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_api  # noqa: E402
import advertiser_protocol as proto  # noqa: E402
import migrations  # noqa: E402
from database import Base  # noqa: E402
from models import ApiConnection, ApiFieldMap  # noqa: E402

PS = migrations.PARTNERSTACK_TEMPLATE_ID
OLD_PS = "partnerstack_partner_rewards"
CJ = migrations.CJ_TEMPLATE_ID
AWIN = "awin_publisher_transactions"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestTemplateNameAndRequiredFields(unittest.TestCase):
    def test_template_is_named_partnerstack(self):
        tpl = advertiser_api.template_by_code("partnerstack")
        self.assertIsNotNone(tpl)
        self.assertEqual(tpl["code"], "partnerstack")
        self.assertEqual(tpl["name"], "PartnerStack")
        self.assertEqual(tpl["vendor"], "PartnerStack")
        # V4.143 的自造标识已彻底废弃
        self.assertIsNone(advertiser_api.template_by_code(OLD_PS))

    def test_only_partner_api_key_is_required(self):
        tpl = advertiser_api.template_by_code(PS)
        self.assertEqual([f["key"] for f in tpl["required_fields"]], ["token"])
        self.assertEqual(tpl["required_fields"][0]["label"], "Partner API Key")
        self.assertEqual(tpl["required_fields"][0]["type"], "password")
        self.assertTrue(tpl["required_fields"][0]["required"])
        self.assertFalse(advertiser_api.requires_cid(PS))
        self.assertTrue(advertiser_api.requires_cid(CJ))

    def test_existing_templates_keep_their_own_fields(self):
        """最小改动：CJ / Awin 的字段要求与布局完全不变。"""
        for code in (CJ, AWIN):
            tpl = advertiser_api.template_by_code(code)
            self.assertIsNotNone(tpl)
            keys = {f["key"] for f in tpl["required_fields"]}
            self.assertEqual(keys, {"token", "cid", "endpoint"}, code)
            self.assertTrue(advertiser_api.requires_cid(code), code)

    def test_template_codes_are_unique(self):
        codes = [t["code"] for t in advertiser_api.PRESET_TEMPLATES]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertIn("partnerstack", codes)


class TestRequestFollowsOfficialDoc(unittest.TestCase):
    def test_url_auth_and_only_documented_params(self):
        r = proto.build_request(
            template_code=PS, endpoint="", token="KEY", cid="",
            since_event_date="2026-11-01T00:00:00Z",
            before_event_date="2026-11-20T00:00:00Z")
        self.assertEqual(r["method"], "GET")
        self.assertEqual(r["url"], "https://api.partnerstack.com/api/v2/rewards")
        self.assertEqual(r["headers"]["Authorization"], "Bearer KEY")
        self.assertIsNone(r["json_body"])
        self.assertEqual(set(r["params"]),
                         {"min_created", "max_created", "limit", "order_by"})
        self.assertEqual(r["params"]["min_created"], 1793491200000)
        self.assertEqual(r["params"]["max_created"], 1795132800000)
        self.assertEqual(r["params"]["limit"], 250)
        self.assertEqual(r["params"]["order_by"], "-created_at")
        for banned in ("company_key", "publisherId", "hide_archived_rewards", "cid"):
            self.assertNotIn(banned, r["params"], f"不应发送文档未要求的参数 {banned}")

    def test_protocol_declares_no_cid_concept(self):
        self.assertEqual(proto.protocol_of(PS)["cid_in"], "none")
        r = proto.build_request(
            template_code=PS, endpoint="", token="KEY", cid="legacy-residual",
            since_event_date="a", before_event_date="b")
        self.assertNotIn("company_key", r["params"])
        self.assertNotIn("publisherId", r["params"])

    def test_starting_after_is_the_only_cursor(self):
        r = proto.build_request(
            template_code=PS, endpoint="", token="KEY", cid="",
            since_event_date="a", before_event_date="b",
            since_commission_id="rwrd_last")
        self.assertEqual(r["params"]["starting_after"], "rwrd_last")
        self.assertNotIn("ending_before", r["params"])

    def test_endpoint_is_fixed_by_template_not_user_input(self):
        tpl = advertiser_api.template_by_code(PS)
        self.assertEqual(tpl["default_endpoint"], "https://api.partnerstack.com/api")
        self.assertEqual(proto.protocol_of(PS)["endpoint_path"], "v2/rewards")
        self.assertNotIn("endpoint", {f["key"] for f in tpl["required_fields"]})


class TestTemplateIdMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.engine = create_engine("sqlite:///" + self.tmp)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_renames_legacy_rows_and_is_idempotent(self):
        db = self.Session()
        db.add(ApiFieldMap(template_id=OLD_PS, source_path="key",
                           target_field="fact.commission_id", transform="direct",
                           version=1, enabled=True))
        db.add(ApiConnection(owner_id=1, name="PS legacy", template_code=OLD_PS))
        db.commit()
        db.close()

        with self.engine.begin() as conn:
            note = migrations._migrate_v4144_2(conn)
        self.assertIn(OLD_PS, note)
        self.assertIn(PS, note)

        db = self.Session()
        self.assertEqual(db.query(ApiFieldMap).filter_by(template_id=PS).count(), 1)
        self.assertEqual(db.query(ApiFieldMap).filter_by(template_id=OLD_PS).count(), 0)
        self.assertEqual(db.query(ApiConnection).filter_by(template_code=PS).count(), 1)
        self.assertEqual(db.query(ApiConnection).filter_by(template_code=OLD_PS).count(), 0)
        db.close()

        # 再插一条旧标识且新标识已存在 → 走「删除旧行」分支，不产生重复映射
        db = self.Session()
        db.add(ApiFieldMap(template_id=OLD_PS, source_path="amount",
                           target_field="fact.commission_amount_usd", transform="direct",
                           version=1, enabled=True))
        db.commit()
        db.close()
        with self.engine.begin() as conn:
            migrations._migrate_v4144_2(conn)
        db = self.Session()
        self.assertEqual(db.query(ApiFieldMap).filter_by(template_id=OLD_PS).count(), 0)
        self.assertEqual(db.query(ApiFieldMap).filter_by(template_id=PS).count(), 1)
        db.close()

    def test_migration_registered(self):
        versions = [v for v, _, _ in migrations.MIGRATIONS]
        self.assertIn("V4.144.2", versions)


class TestStaticContract(unittest.TestCase):
    def test_frontend_renders_fields_by_template_declaration(self):
        s = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertIn("hasField(form.template_code, 'cid')", s)
        self.assertIn("hasField(form.template_code, 'endpoint')", s)
        self.assertIn("tokenLabel(form.template_code)", s)
        self.assertIn("const cidRequired", s)
        # 文档没有「公司 Key」这种必填概念，界面不应再出现该误导文案
        self.assertNotIn("留空读取全部；填写则只读取该公司 Key", s)
        self.assertNotIn("company_key", s)

    def test_no_undocumented_param_left_in_backend(self):
        s = _read("backend/advertiser_api.py")
        self.assertNotIn("hide_archived_rewards", s)
        self.assertNotIn('"cid_param": "company_key"', s)

    def test_templates_endpoint_serializes_template_fields(self):
        s = _read("backend/routers.py")
        self.assertIn("required_fields", s)
        self.assertIn("t.get(\"required_fields\")", s)


if __name__ == "__main__":
    unittest.main()
