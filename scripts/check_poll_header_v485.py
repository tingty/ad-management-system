#!/usr/bin/env python3
"""V4.85 视频任务轮询请求头验收（本地假供应商，零外部依赖、零费用）。

问题：提交视频生成后拉取任务时不应携带 X-DashScope-Async。
- 提交（POST）必须带 X-DashScope-Async: enable（百炼 MaaS 异步必需）——不能因修复而丢失。
- 轮询（GET /api/v1/tasks/{id}）必须不带该头——部分网关因该头返回 400/403。
- worker 重启后读到的旧任务快照（无 poll_headers 字段）也必须防御性剔除。

覆盖：
  C1 plan_request 冻结的 headers 含异步头 / poll_headers 不含
  C2 真实 submit_job 发出的 POST 头含异步头
  C3 真实 poll_job 发出的 GET 头不含异步头
  C4 旧快照（仅 headers，无 poll_headers）poll_job 仍不带异步头
  C5 非 dashscope（async_header 未开）提交与轮询都不带异步头

用法：python3 scripts/check_poll_header_v485.py [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from providers import ModelVideo  # noqa: E402

ASYNC_HEADER = "X-DashScope-Async"

_seen_lock = threading.Lock()
_seen: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj, code: int = 200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        with _seen_lock:
            _seen.append({"method": "POST", "path": self.path,
                          "headers": {k.lower(): v for k, v in self.headers.items()}})
        self._json({"request_id": "req_test",
                    "output": {"task_id": "tk_test", "task_status": "PENDING"}})

    def do_GET(self):
        with _seen_lock:
            _seen.append({"method": "GET", "path": self.path,
                          "headers": {k.lower(): v for k, v in self.headers.items()}})
        if self.path.startswith("/api/v1/tasks/"):
            self._json({"output": {"task_id": "tk_test", "task_status": "SUCCEEDED",
                                   "video_url": "http://127.0.0.1/media/dummy.mp4"}})
            return
        self._json({"message": "not found"}, 404)


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


RESULTS: list[dict] = []


def record(name: str, ok: bool, detail: str):
    RESULTS.append({"case": name, "ok": bool(ok), "detail": detail})
    print(("  ✅ " if ok else "  ❌ ") + f"{name} — {detail}")


def make_model(base: str, model: str, async_header: str = "true") -> ModelVideo:
    params = {"body_shape": "dashscope_maas",
              "endpoint": "/api/v1/services/aigc/video-generation/video-synthesis",
              "async_header": async_header, "poll_path": "/api/v1/tasks",
              "output_aspect": "9:16", "poll_timeout_sec": "3", "poll_interval_sec": "0.1"}
    return ModelVideo("sk-test", base, model, params)


def has_async(headers: dict) -> bool:
    return any(k.lower() == ASYNC_HEADER.lower() for k in headers)


async def main():
    srv, base = start_server()
    try:
        # ---------- C1：冻结头分离 ----------
        m = make_model(base, "model-ok")
        req = m.plan_request("a cat", {"aspect": "9:16", "duration": 15})
        record("C1.1 提交头含 X-DashScope-Async",
               has_async(req["headers"]), f"headers={sorted(req['headers'])}")
        record("C1.2 轮询头不含 X-DashScope-Async",
               not has_async(req["poll_headers"]), f"poll_headers={sorted(req['poll_headers'])}")
        record("C1.3 提交头/轮询头对象独立",
               req["headers"] is not req["poll_headers"], "两份字典互不影响")

        # ---------- C2/C3：真实 submit + poll ----------
        with _seen_lock:
            _seen.clear()
        sub = await m.submit_job("a cat", {"aspect": "9:16", "duration": 15})
        poll = await m.poll_job(sub["task_id"], sub["request"])
        with _seen_lock:
            posts = [x for x in _seen if x["method"] == "POST"]
            gets = [x for x in _seen if x["method"] == "GET"]
        record("C2 真实 POST 提交头含异步头",
               bool(posts) and has_async(posts[0]["headers"]),
               f"POST {posts[0]['path'] if posts else '-'} async={has_async(posts[0]['headers']) if posts else '-'}")
        record("C3 真实 GET 轮询头不含异步头",
               bool(gets) and not has_async(gets[0]["headers"]),
               f"GET {gets[0]['path'] if gets else '-'} async={has_async(gets[0]['headers']) if gets else '-'}")
        record("C3.2 轮询确实拿到 SUCCEEDED",
               poll.get("state") == "succeeded", f"state={poll.get('state')}")

        # ---------- C4：旧快照（仅 headers，无 poll_headers）----------
        with _seen_lock:
            _seen.clear()
        legacy_req = dict(req)
        legacy_req.pop("poll_headers", None)  # 模拟 worker 重启读到的旧快照
        await m.poll_job("tk_test", legacy_req)
        with _seen_lock:
            gets_legacy = [x for x in _seen if x["method"] == "GET"]
        record("C4 旧快照轮询也剔除异步头",
               bool(gets_legacy) and not has_async(gets_legacy[0]["headers"]),
               f"async={has_async(gets_legacy[0]['headers']) if gets_legacy else '-'}")

        # ---------- C5：未开启 async_header ----------
        m2 = make_model(base, "model-sync", async_header="false")
        req2 = m2.plan_request("a cat", {"duration": 5})
        record("C5 未开 async_header 时提交头无异步头",
               not has_async(req2["headers"]), f"headers={sorted(req2['headers'])}")
        record("C5.2 未开 async_header 时轮询头也无异步头",
               not has_async(req2["poll_headers"]), f"poll_headers={sorted(req2['poll_headers'])}")
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_path", default="")
    args = ap.parse_args()
    asyncio.run(main())
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print(f"\n结果：{passed}/{total} 通过")
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(RESULTS, f, ensure_ascii=False, indent=2)
    if passed != total:
        sys.exit(1)
