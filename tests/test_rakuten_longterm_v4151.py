import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(
    ROOT, "docs", "Rakuten_Advertising_API接入说明与广告主API标准工作流.md")


class RakutenLongTermContractV4151(unittest.TestCase):
    """V4.151：固化 Rakuten 凭据机制与长期拉取边界。"""

    @classmethod
    def setUpClass(cls):
        with open(DOC, "r", encoding="utf-8") as f:
            cls.text = f.read()

    def test_credentials_mechanism_is_explicit(self):
        self.assertIn("Base64(client_id:client_secret)", self.text)
        self.assertIn("`account-id` 作为 `scope`", self.text)
        self.assertIn("Authorization: Bearer <access_token>", self.text)
        self.assertIn("oauth:{token-key}|{account-id}", self.text)
        self.assertIn("未拆成", self.text)

    def test_token_lifetime_and_rate_limits_are_explicit(self):
        self.assertIn("3600", self.text)
        self.assertIn("100 次/分钟", self.text)
        self.assertIn("refresh_token", self.text)

    def test_events_api_limitations_are_explicit(self):
        self.assertIn("只保存前 1–2 周数据", self.text)
        self.assertIn("不建议用它计算 expected commissions", self.text)
        self.assertIn("Publisher Dashboard", self.text)
        self.assertIn("长期滚动拉取", self.text)


if __name__ == "__main__":
    unittest.main()
