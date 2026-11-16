#!/usr/bin/env python3
"""V4.79 / P0 视频出片链路确定性验收（本地假供应商，零外部依赖、零费用）。

覆盖 A01–A14 中除「真实付费出片」外的全部条目：
- A02 解析白名单：PENDING 响应里的 input.image 绝不能被当成成片（F04）
- A03 轮询 5xx / 非 JSON / 404 分类与退避，超限报 POLL_UNREACHABLE（F02）
- A04 任务完成但无成片地址 → EMPTY_OUTPUT（F04/F03）
- A05 厂商回报 FAILED → PROVIDER_REJECTED，并带原文
- A06 提交 401 / 500 / 200+HTML → AUTH_FAILED / PROVIDER_ERROR / CONTRACT_MISMATCH
- A07 下载到 HTML 错误页 → DOWNLOAD_FAILED（F05）
- A08 MP4 缺 moov 索引 → DOWNLOAD_FAILED（F05）
- A09 同步直出 → 落盘并通过校验
- A10 异步成功 → 落盘并通过校验，证据链含 submit/polls/download
- A11 连通测试严格化：200 但非 JSON / 无任务号 → 不再判「通过」（F01）
- A12 轮询超时保留 task_id（POLL_TIMEOUT）

用法：python3 scripts/check_video_pipeline_p0.py [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import providers  # noqa: E402
from providers import ModelVideo, VideoPipelineError, verify_video_file  # noqa: E402

# ---------------------------------------------------------------- 假供应商素材
def _mp4_bytes(with_moov: bool = True) -> bytes:
    head = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    body = b"\x00\x00\x00\x08free"
    if with_moov:
        body += b"\x00\x00\x00\x40moov" + b"\x00" * 60
    body += b"\x00" * 9000
    return head + body


VIDEO_MP4 = _mp4_bytes(True)
BROKEN_MP4 = _mp4_bytes(False)
HTML_PAGE = b"<html><body>502 Bad Gateway</body></html>" + b" " * 5000

# 场景：model 名 → 行为
SCENARIOS = {
    "ok-async", "pending-echo", "empty-output", "rejected",
    "poll-500", "html-submit", "auth-401", "err-500",
    "bad-media", "no-moov", "sync-direct", "contract-empty",
}

_state_lock = threading.Lock()
_poll_counts: dict[str, int] = {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音
        pass

    # ---------- 工具 ----------
    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    # ---------- 路由 ----------
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        model = str(body.get("model") or "")

        if model == "html-submit":
            return self._send(200, HTML_PAGE, "text/html")
        if model == "auth-401":
            return self._json({"code": "InvalidApiKey", "message": "Invalid API-key provided."}, 401)
        if model == "err-500":
            return self._json({"message": "internal error"}, 500)
        if model == "contract-empty":
            return self._json({"request_id": "req_only", "output": {"task_status": "PENDING"}})
        if model == "sync-direct":
            return self._json({"output": {"video_url": f"{self.base}/media/video.mp4"}})
        if model == "pending-echo":
            # 关键用例：PENDING + 输入回显（商品图）——旧实现会把这张图当成片
            return self._json({"request_id": "req_echo",
                               "output": {"task_id": "tk_pending-echo", "task_status": "PENDING",
                                          "input": {"image": f"{self.base}/media/product.png"}}})
        if model in SCENARIOS:
            with _state_lock:
                _poll_counts[model] = 0
            return self._json({"request_id": "req_" + model,
                               "output": {"task_id": "tk_" + model, "task_status": "PENDING"}})
        return self._json({"message": "unknown model"}, 400)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/media/video.mp4":
            return self._send(200, VIDEO_MP4, "video/mp4")
        if path == "/media/broken.mp4":
            return self._send(200, BROKEN_MP4, "video/mp4")
        if path == "/media/page.html":
            return self._send(200, HTML_PAGE, "text/html")
        if path == "/media/product.png":
            return self._send(200, b"\x89PNG\r\n\x1a\n" + b"0" * 2000, "image/png")
        if path.startswith("/api/v1/tasks/"):
            model = path.rsplit("/", 1)[-1].replace("tk_", "")
            with _state_lock:
                _poll_counts[model] = _poll_counts.get(model, 0) + 1
                cnt = _poll_counts[model]
            if model == "poll-500":
                return self._json({"message": "upstream timeout"}, 500)
            if model == "no-moov":
                return self._json({"output": {"task_status": "SUCCEEDED",
                                              "video_url": f"{self.base}/media/broken.mp4"}})
            if model == "bad-media":
                return self._json({"output": {"task_status": "SUCCEEDED",
                                              "video_url": f"{self.base}/media/page.html"}})
            if model == "empty-output":
                return self._json({"output": {"task_status": "SUCCEEDED"}})
            if model == "rejected":
                return self._json({"output": {"task_status": "FAILED",
                                              "message": "内容审核未通过"}})
            if model == "pending-echo":
                return self._json({"output": {"task_id": "tk_pending-echo", "task_status": "PENDING",
                                              "input": {"image": f"{self.base}/media/product.png"}}})
            if cnt < 2:
                return self._json({"output": {"task_id": "tk_" + model, "task_status": "PENDING"}})
            return self._json({"output": {"task_id": "tk_" + model, "task_status": "SUCCEEDED",
                                          "video_url": f"{self.base}/media/video.mp4"}})
        return self._send(404, b'{"message":"not found"}', "application/json")


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ---------------------------------------------------------------- 断言工具
RESULTS: list[dict] = []


def record(name: str, ok: bool, detail: str):
    RESULTS.append({"case": name, "ok": bool(ok), "detail": detail})
    print(("  ✅ " if ok else "  ❌ ") + f"{name} — {detail}")


def make_model(base: str, model: str, **params) -> ModelVideo:
    p = {"body_shape": "dashscope_maas",
         "endpoint": "/api/v1/services/aigc/video-generation/video-synthesis",
         "async_header": "true", "poll_path": "/api/v1/tasks",
         "output_aspect": "9:16", "poll_interval_sec": "0.2", "poll_timeout_sec": "3",
         "poll_max_failures": "3"}
    p.update({k: str(v) for k, v in params.items()})
    return ModelVideo("sk-test", base, model, p)


async def expect_error(name: str, model_name: str, base: str, code: str, **params):
    mv = make_model(base, model_name, **params)
    try:
        res = await mv.generate("测试提示词", "TikTok", f"p0_{model_name}.mp4", {"aspect": "9:16"})
        record(name, False, f"应失败却成功：provider={res.get('provider')} file={res.get('file_path')}")
    except VideoPipelineError as e:
        ok = e.error_code == code and bool(e.action)
        record(name, ok, f"error_code={e.error_code}（期望 {code}）stage={e.stage} "
                         f"task_id={e.task_id or '-'} action={'有' if e.action else '缺'}")


async def expect_success(name: str, model_name: str, base: str):
    mv = make_model(base, model_name)
    res = await mv.generate("测试提示词", "TikTok", f"p0_{model_name}.mp4", {"aspect": "9:16"})
    path = res.get("file_path") or ""
    info = verify_video_file(path) if path else {"ok": False, "reason": "无 file_path"}
    ev = res.get("evidence") or {}
    ok = bool(path) and info.get("ok") and "submit" in ev and ev.get("download")
    detail = f"file={os.path.basename(path) or '-'} bytes={info.get('bytes')} container={info.get('container')} " \
             f"evidence.submit={bool(ev.get('submit'))} polls={len(ev.get('polls') or [])}"
    record(name, ok, detail)
    if path and os.path.exists(path):
        os.remove(path)


async def run(base: str):
    print("\n[1] 解析白名单（F04：输入回显不得被当成片）")
    pending = {"output": {"task_status": "PENDING", "task_id": "tk_x",
                          "input": {"image": "https://example.com/p.png"}}}
    u, b = providers.video_media_of(pending, "dashscope_maas")
    record("A02 PENDING 不含 input.image", not (u or b), f"media=({u or '-'},{b or '-'})")
    done = {"output": {"task_status": "SUCCEEDED", "video_url": "https://example.com/a.mp4"}}
    u2, _ = providers.video_media_of(done, "dashscope_maas")
    record("A02 完成态取 output.video_url", u2 == "https://example.com/a.mp4", f"media={u2}")

    print("\n[2] 异步成功链路")
    await expect_success("A10 异步成功落盘并留证据", "ok-async", base)
    await expect_success("A09 同步直出落盘", "sync-direct", base)

    print("\n[3] 失败分类（每个错误码只给一个动作）")
    await expect_error("A06 提交 401 → AUTH_FAILED", "auth-401", base, "AUTH_FAILED")
    await expect_error("A06 提交 500 → PROVIDER_ERROR", "err-500", base, "PROVIDER_ERROR")
    await expect_error("A06 提交 200+HTML → CONTRACT_MISMATCH", "html-submit", base, "CONTRACT_MISMATCH")
    await expect_error("A06 只有 request_id 无任务号 → CONTRACT_MISMATCH", "contract-empty", base, "CONTRACT_MISMATCH")
    await expect_error("A04 完成但无成片地址 → EMPTY_OUTPUT", "empty-output", base, "EMPTY_OUTPUT")
    await expect_error("A05 厂商回报 FAILED → PROVIDER_REJECTED", "rejected", base, "PROVIDER_REJECTED")
    await expect_error("A03 轮询持续 5xx → POLL_UNREACHABLE", "poll-500", base, "POLL_UNREACHABLE")
    await expect_error("A07 下载到 HTML → DOWNLOAD_FAILED", "bad-media", base, "DOWNLOAD_FAILED")
    await expect_error("A08 MP4 缺 moov → DOWNLOAD_FAILED", "no-moov", base, "DOWNLOAD_FAILED")
    await expect_error("A12 轮询超时保留 task_id → POLL_TIMEOUT", "pending-echo", base, "POLL_TIMEOUT",
                       poll_timeout_sec="1.2")

    # 超时必须带任务号，且分镜不得被写入
    try:
        mv = make_model(base, "pending-echo", poll_timeout_sec="1.0")
        await mv.generate("x", "TikTok", "p0_timeout.mp4", {"aspect": "9:16"})
    except VideoPipelineError as e:
        record("A12 超时保留厂商任务号", e.task_id == "tk_pending-echo", f"task_id={e.task_id}")

    print("\n[4] 连通测试严格化（F01）")
    from llm_catalog import _test_generic_video
    req = {"api_key": "sk", "base_url": base, "model": "html-submit",
           "params": {"body_shape": "dashscope_maas",
                      "endpoint": "/api/v1/services/aigc/video-generation/video-synthesis",
                      "async_header": "true"}}
    r1 = await _test_generic_video(dict(req), None)
    record("A11 200+HTML 不判通过", r1.get("ok") is False and r1.get("error_type") == "non_json_response",
           f"ok={r1.get('ok')} type={r1.get('error_type')}")
    req2 = dict(req, model="contract-empty")
    r2 = await _test_generic_video(req2, None)
    record("A11 有 request_id 无任务号不判通过", r2.get("ok") is False,
           f"ok={r2.get('ok')} type={r2.get('error_type')}")
    req3 = dict(req, model="ok-async")
    r3 = await _test_generic_video(req3, None)
    record("A11 正常受理判通过", r3.get("ok") is True, f"reply={str(r3.get('reply'))[:40]}")

    print("\n[5] 落盘校验单测")
    p = os.path.join(providers.UPLOAD_DIR, "p0_html.tmp")
    with open(p, "wb") as f:
        f.write(HTML_PAGE)
    info = verify_video_file(p)
    os.remove(p)
    record("A08 HTML 文件不被当视频", info["ok"] is False and "不是可识别的视频容器" in info["reason"],
           info["reason"][:60])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    srv, base = start_server()
    Handler.base = base
    print(f"假供应商已启动：{base}")
    try:
        asyncio.run(run(base))
    finally:
        srv.shutdown()
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n结果：{passed}/{total} 通过")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"passed": passed, "total": total, "results": RESULTS,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, ensure_ascii=False, indent=2)
        print(f"报告：{args.json}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
