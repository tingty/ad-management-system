#!/usr/bin/env python3
"""V4.80 / P1 验收：交付时长用实测值 + 文件名唯一化（零费用，纯本地断言）。

对应验收条目：
- P1-1 时长实测：无 ffprobe 也能从 moov/mvhd 读出真实秒数（v0 / v1 两种版本头）；
- P1-2 时长来源：measured（实测）/ planned（拿不到元数据时才退回计划值），不乱标；
- P1-3 时长不符提示：实测 10s 而计划 15s 时必须显式告知，不许当成 15s 交付；
- P1-4 文件名唯一：同一秒内连续两次出片文件名不同、两个文件都在（不再相互覆盖）；
- P1-5 扩展名一致：厂商回 webm 时不能被存成 .mp4（否则浏览器按 MIME 拒播）。

用法：python3 scripts/check_video_p1.py
"""
from __future__ import annotations

import asyncio
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

TMP = tempfile.mkdtemp(prefix="v480_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(TMP, 'p1.db')}"

import providers  # noqa: E402
from database import Base, engine, SessionLocal  # noqa: E402
from models import ModelConfig, User  # noqa: E402
import routers  # noqa: E402
from schemas import CWVideoGenerateRequest  # noqa: E402

results: list[dict] = []


def record(name: str, ok: bool, detail: str):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(("  ✅ " if ok else "  ❌ ") + f"{name} — {detail}")


# ---------------- 合成 MP4（带真实 mvhd，含版本 0 / 1） ----------------
def _box(typ: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + typ + body


def _mvhd_v0(timescale: int, duration: int) -> bytes:
    body = b"\x00" + b"\x00\x00\x00"          # version 0 + flags
    body += b"\x00" * 8                        # creation + modification
    body += struct.pack(">I", timescale)
    body += struct.pack(">I", duration)
    body += b"\x00" * 80                       # rate / volume / matrix / next track
    return _box(b"mvhd", body)


def _mvhd_v1(timescale: int, duration: int) -> bytes:
    body = b"\x01" + b"\x00\x00\x00"          # version 1 + flags
    body += b"\x00" * 16                       # creation + modification（8+8）
    body += struct.pack(">I", timescale)
    body += struct.pack(">Q", duration)
    body += b"\x00" * 80
    return _box(b"mvhd", body)


def mp4_bytes(seconds: float, version: int = 0, with_mvhd: bool = True) -> bytes:
    scale = 1000
    dur = int(round(seconds * scale))
    head = _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2avc1mp41")
    padding = _box(b"mdat", b"\x00" * 5000)     # 让 moov 落在文件尾，顺便验证 box 跳过 mdat
    moov_body = (_mvhd_v1(scale, dur) if version == 1 else _mvhd_v0(scale, dur)) if with_mvhd else b"\x00" * 60
    return head + padding + _box(b"moov", moov_body)


class _NoProbe:
    """模拟「镜像里没装 ffprobe」的常见部署环境。"""
    def __init__(self):
        self.calls = 0

    def __call__(self, path):
        self.calls += 1
        return {"available": False, "ok": False, "reason": "ffprobe not found"}


# ---------------- 假供应商：只负责把「成片」写到 routers 给的路径 ----------------
class StubProvider:
    def __init__(self, seconds: float, reported: bool = True):
        self.seconds = seconds
        self.reported = reported
        self.names: list[str] = []

    async def generate(self, prompt, platform, filename, meta=None):
        self.names.append(filename)
        path = os.path.join(routers.UPLOAD_DIR, filename)
        with open(path, "wb") as f:
            f.write(mp4_bytes(self.seconds))
        out = {"provider": "model", "file_path": path, "model": "stub-video",
               "output_aspect": "9:16", "file_bytes": os.path.getsize(path)}
        if self.reported:   # reported=False 模拟厂商+校验都没给时长
            out["duration_sec"] = self.seconds
            out["duration_source"] = "mvhd"
        return out


def seed_video_cfg():
    db = SessionLocal()
    db.query(ModelConfig).delete()
    db.add(ModelConfig(name="桩视频模型", usage="video", usages=["video"],
                       provider="aliyun-maas-video", api_key="sk-test",
                       base_url="http://127.0.0.1:9", model="stub-video", params={}, is_active=True))
    db.commit()
    db.close()


def req_of(seconds: int) -> CWVideoGenerateRequest:
    return CWVideoGenerateRequest(
        analysis={"product": "测试产品"}, platform="TikTok",
        plan={"aspect": "9:16", "duration_sec": seconds,
              "shots": [{"idx": 1, "t": "0-3s", "shot": "开场", "visual": "产品特写"}]},
        options={"duration": seconds, "aspect": "9:16"},
    )


async def main():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    user = db.query(User).first()
    if not user:
        user = User(username="qa1", email="qa1@test.local", display_name="QA1",
                    role="admin", password_hash="x", salt="x")
        db.add(user)
        db.commit()
        db.refresh(user)
    uid = user.id
    print(f"临时库：{os.environ['DATABASE_URL']}  user_id={uid}\n")

    real_probe = providers._ffprobe_video
    probe = _NoProbe()
    providers._ffprobe_video = probe

    try:
        print("[1] 时长实测：moov/mvhd 解析（P1-1）")
        p0 = os.path.join(TMP, "v0.mp4")
        with open(p0, "wb") as f:
            f.write(mp4_bytes(15.04, version=0))
        record("v0 头 15.04s", abs(providers._mp4_duration(p0) - 15.04) < 0.05,
               f"{providers._mp4_duration(p0)}s")

        p1 = os.path.join(TMP, "v1.mp4")
        with open(p1, "wb") as f:
            f.write(mp4_bytes(5.0, version=1))
        record("v1 头 5.0s", abs(providers._mp4_duration(p1) - 5.0) < 0.05,
               f"{providers._mp4_duration(p1)}s")

        pn = os.path.join(TMP, "no_mvhd.mp4")
        with open(pn, "wb") as f:
            f.write(mp4_bytes(15.0, with_mvhd=False))
        record("无 mvhd → 0（不瞎猜）", providers._mp4_duration(pn) == 0.0,
               f"{providers._mp4_duration(pn)}")

        print("\n[2] 校验结论带上实测时长与来源（P1-2）")
        info = providers.verify_video_file(p0)
        record("无 ffprobe 仍拿到实测时长",
               info.get("ok") and abs(float(info.get("duration") or 0) - 15.04) < 0.05,
               f"ok={info.get('ok')} duration={info.get('duration')} source={info.get('duration_source')}")
        record("来源标记为 mvhd", info.get("duration_source") == "mvhd", f"{info.get('duration_source')}")
        info_n = providers.verify_video_file(pn)
        record("拿不到元数据时不编造时长",
               info_n.get("ok") and not info_n.get("duration") and not info_n.get("duration_source"),
               f"duration={info_n.get('duration')} source={info_n.get('duration_source')!r}")

        print("\n[3] 扩展名与真实容器一致（P1-5）")
        pw = os.path.join(TMP, "clip.mp4")
        with open(pw, "wb") as f:
            f.write(b"\x1aE\xdf\xa3" + b"\x00" * 5000)   # webm 魔数
        newp = providers.align_video_ext(pw)
        record("webm 内容 → 改名为 .webm", newp.endswith(".webm") and os.path.exists(newp) and not os.path.exists(pw),
               f"{os.path.basename(newp)}")

        print("\n[4] 文件名唯一 + 实测时长进入交付物（P1-3 / P1-4）")
        names = {routers._cw_video_filename(uid) for _ in range(20)}
        record("同秒 20 次命名无重复", len(names) == 20, f"{len(names)}/20 唯一")

        seed_video_cfg()
        stub = StubProvider(10.0)
        routers.get_video = lambda _db: stub
        res1 = await routers._cw_video_generate_impl(req_of(15), db, user)
        v1 = res1.videos[0] if res1.videos else None
        record("交付时长 = 实测 10s（不是计划的 15s）",
               bool(v1) and abs(float(v1.duration_sec) - 10.0) < 0.05 and v1.duration_source == "measured",
               f"duration={getattr(v1, 'duration_sec', None)} source={getattr(v1, 'duration_source', '')}")
        record("时长不符有明确提示",
               "实测成片时长 10.0s" in (res1.note or ""), (res1.note or "")[:80])
        f1 = os.path.join(routers.UPLOAD_DIR, os.path.basename(v1.url)) if v1 else ""
        record("分镜保留计划值、实际值单列",
               res1.storyboard.get("duration_sec") == 15 and abs(float(res1.storyboard.get("duration_sec_actual") or 0) - 10.0) < 0.05,
               f"plan={res1.storyboard.get('duration_sec')} actual={res1.storyboard.get('duration_sec_actual')}")

        res2 = await routers._cw_video_generate_impl(req_of(15), db, user)
        v2 = res2.videos[0] if res2.videos else None
        f2 = os.path.join(routers.UPLOAD_DIR, os.path.basename(v2.url)) if v2 else ""
        record("同秒两次出片两个文件都在（不覆盖）",
               bool(f1 and f2 and f1 != f2 and os.path.exists(f1) and os.path.exists(f2)),
               f"{os.path.basename(f1)} / {os.path.basename(f2)}")

        print("\n[5] 拿不到实测时长时退回计划值并标注来源")
        seed_video_cfg()
        stub2 = StubProvider(10.0, reported=False)
        routers.get_video = lambda _db: stub2
        res3 = await routers._cw_video_generate_impl(req_of(15), db, user)
        v3 = res3.videos[0] if res3.videos else None
        record("兜底用计划值且标明 planned",
               bool(v3) and float(v3.duration_sec) == 15 and v3.duration_source == "planned",
               f"duration={getattr(v3, 'duration_sec', None)} source={getattr(v3, 'duration_source', '')}")
        record("兜底时不谎报不符",
               "实测成片时长" not in (res3.note or ""), (res3.note or "")[:60] or "(空)")
        for p in (f1, f2, os.path.join(routers.UPLOAD_DIR, os.path.basename(v3.url)) if v3 else ""):
            if p and os.path.exists(p):
                os.remove(p)
    finally:
        providers._ffprobe_video = real_probe
        db.close()

    passed = sum(1 for r in results if r["ok"])
    print(f"\n结果：{passed}/{len(results)} 通过")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
