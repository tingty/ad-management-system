#!/usr/bin/env python3
"""V4.79 真实出片验收：**只发起 1 次**付费调用，补齐证据链。

为什么需要单独跑：真实出片会真实扣费，且厂商 Key 只在部署机（公网 IP 已加白名单）上，
所以这个脚本设计成「必须显式 --yes 才发一次请求」，跑完把证据写进 docs/evidence/。

在哪跑（二选一）：
  1) 部署机容器内：docker compose exec backend python3 /app/../scripts/verify_real_video_once.py --yes
     （若 compose 未挂载 scripts，用 docker cp 放进去，或直接进容器 python3 -c 调用）
  2) 部署机后端目录：cd <项目>/ad-material-platform && python3 scripts/verify_real_video_once.py --yes

输出：控制台结构化结论 + docs/evidence/v479_real_<时间>.json（含脱敏证据链）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from database import SessionLocal  # noqa: E402
from models import ModelConfig  # noqa: E402
from providers import ModelVideo, VideoPipelineError, _active_config, verify_video_file  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="确认发起 1 次真实付费出片")
    ap.add_argument("--prompt", default="A smartphone product rotating slowly on a clean desk, soft studio light, vertical 9:16")
    ap.add_argument("--timeout", type=int, default=600, help="轮询总时长（秒）")
    args = ap.parse_args()

    db = SessionLocal()
    cfg = _active_config(db, "video")
    if not cfg:
        print("❌ 没有生效的视频模型配置（用途 video + 已启用 + Key/链接/模型齐全）。"
              "先去「大模型配置」补齐，再跑本脚本。")
        return 2
    params = dict(cfg.params or {})
    print("将使用配置：")
    print(f"  #{cfg.id} {cfg.name or ''} | provider={cfg.provider} | model={cfg.model}")
    print(f"  base_url={cfg.base_url}")
    print(f"  family={(params.get('body_shape') or 'generic')} endpoint={params.get('endpoint') or '/video/generations'}")
    if not args.yes:
        print("\n这是付费调用，未加 --yes 不会发起。确认请重跑并加 --yes。")
        return 0

    params["poll_timeout_sec"] = str(args.timeout)
    params.setdefault("output_aspect", "9:16")
    mv = ModelVideo(cfg.api_key, cfg.base_url, cfg.model, params)
    fname = f"real_v479_{int(time.time())}.mp4"
    print(f"\n发起 1 次真实出片…（最长等 {args.timeout}s）")
    t0 = time.time()
    payload: dict = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "config_id": cfg.id,
                     "provider": cfg.provider, "model": cfg.model, "base_url": cfg.base_url}
    try:
        res = await mv.generate(args.prompt, "TikTok", fname, {"aspect": "9:16", "duration": 5})
        info = verify_video_file(res.get("file_path") or "")
        payload.update({"ok": True, "elapsed_sec": round(time.time() - t0, 1),
                        "file": os.path.basename(res.get("file_path") or ""),
                        "bytes": info.get("bytes"), "container": info.get("container"),
                        "duration": info.get("duration"), "evidence": res.get("evidence")})
        print(f"\n✅ 出片成功：{payload['file']}  {payload['bytes']} 字节  "
              f"容器={payload['container']}  耗时 {payload['elapsed_sec']}s")
        if info.get("duration"):
            print(f"   实测时长：{info['duration']}s（{info.get('width')}x{info.get('height')}）")
        print(f"   证据：submit={bool((res.get('evidence') or {}).get('submit'))} "
              f"polls={len(((res.get('evidence') or {}).get('polls')) or [])}")
    except VideoPipelineError as e:
        payload.update({"ok": False, "elapsed_sec": round(time.time() - t0, 1),
                        "error_code": e.error_code, "error_message": e.message,
                        "error_action": e.action, "stage": e.stage,
                        "task_id": e.task_id, "evidence": e.evidence})
        print(f"\n❌ 出片失败：{e.error_code}（阶段 {e.stage}）")
        print(f"   原文：{e.message}")
        print(f"   动作：{e.action}")
        if e.task_id:
            print(f"   任务号：{e.task_id}（到厂商控制台按此号取片，不要重复提交）")

    outdir = os.path.join(ROOT, "docs", "evidence")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"v479_real_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n证据已写入：{path}")
    db.close()
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
