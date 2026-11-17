"""V4.87 落地页抓取健壮性：超限 / 二进制 / 异常 scheme 必须在抓取层被拦截，不拖垮 worker。"""
import asyncio
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402

import services  # noqa: E402
import fetchers  # noqa: E402

_BODY = ("<html><head><title>测试产品</title></head><body>"
         "<h1>无线降噪耳机</h1>" + ("这是页面正文内容。" * 40) +
         "<a href='/buy'>立即购买</a></body></html>").encode("utf-8")
_LARGE = (_BODY + b"x" * (services.MAX_FETCH_BYTES + 1024))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        if self.path.startswith("/normal"):
            self._send(_BODY, "text/html; charset=utf-8")
        elif self.path.startswith("/binary"):
            self._send(b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000, "image/png")
        elif self.path.startswith("/large"):
            self._send(_LARGE, "text/html; charset=utf-8")
        elif self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/normal")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


class TestFetchRobustness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def fetch(self, path):
        return asyncio.run(services.fetch_page(self.base + path))

    def test_01_normal_html_still_parsed(self):
        r = self.fetch("/normal")
        self.assertTrue(r["fetched"])
        self.assertEqual(r["fetch_quality"], "ok")
        self.assertIn("无线降噪耳机", r["text"])
        self.assertIn("测试产品", r["title"])

    def test_02_binary_content_type_rejected(self):
        # 二进制直链不得走 r.text 解码成巨型乱码（OOM → worker 重启 → 502）
        r = self.fetch("/binary")
        self.assertFalse(r["fetched"])
        self.assertEqual(r["fetch_quality"], "unsupported_content_type")

    def test_03_oversize_response_truncated(self):
        # 超限响应必须被截断并标记 too_large，不能整页读进内存
        r = self.fetch("/large")
        self.assertTrue(r["fetched"])
        self.assertEqual(r["fetch_quality"], "too_large")
        self.assertLessEqual(len(r.get("html") or ""), services.MAX_FETCH_BYTES)

    def test_04_redirect_followed(self):
        r = self.fetch("/redirect")
        self.assertTrue(r["fetched"])
        self.assertTrue(r["redirect_chain"], "应记录跳转链")
        self.assertIn("无线降噪耳机", r["text"])

    def test_05_unsupported_scheme_blocked(self):
        r = asyncio.run(services.fetch_page("ftp://example.com/x"))
        self.assertEqual(r["fetch_quality"], "unsupported_scheme")
        self.assertFalse(r["fetched"])

    def test_06_product_blocks_bad_quality(self):
        # fetch_product 必须把超限 / 二进制 / 异常 scheme 判为失败，交给路由给 422
        for path, expect in [("/large", "too_large"), ("/binary", "unsupported_content_type")]:
            fp = asyncio.run(fetchers.fetch_product(self.base + path))
            self.assertFalse(fp["ok"], f"{path} 应阻断")
            self.assertEqual(fp["page"]["fetch_quality"], expect)
        fp = asyncio.run(fetchers.fetch_product("ftp://example.com/x"))
        self.assertFalse(fp["ok"])

    def test_07_limits_are_reasonable(self):
        # 防止 Someone 把上限调到无限大：必须有界
        self.assertGreater(services.MAX_FETCH_BYTES, 0)
        self.assertLessEqual(services.MAX_FETCH_BYTES, 64 * 1024 * 1024)
        self.assertGreaterEqual(services.MAX_REDIRECTS, 1)


if __name__ == "__main__":
    unittest.main()
