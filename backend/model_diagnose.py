"""大模型配置自检（只读）。V4.109

用途：在**真实环境**里一眼看清「系统到底认了哪条配置、为什么不可用」。
此前排查只能翻设置页或猜，容易出现「明明配了图片模型，却说未配置」这类误判。

用法（服务器上，仓库根目录）：
    docker compose exec backend python3 model_diagnose.py

也支持本地：
    cd backend && python3 model_diagnose.py

只读：不写库、不调用任何模型接口、不产生费用。
"""
from __future__ import annotations

import sys

USAGES = ("analysis", "copy", "image", "video")
LABEL = {"analysis": "分析", "copy": "文案", "image": "图片", "video": "视频"}


def _fmt(v) -> str:
    if v is None:
        return "-"
    if v is True:
        return "是"
    if v is False:
        return "否"
    return str(v)


def main() -> int:
    from database import DATABASE_URL, SessionLocal
    from models import ModelConfig
    from providers import _pick_config, _usages_of, _usable, is_video_capable

    print(f"数据库：{DATABASE_URL}")
    db = SessionLocal()
    try:
        rows = db.query(ModelConfig).order_by(ModelConfig.id).all()
        if not rows:
            print("模型配置：空表（一条都没有）")
            return 1

        print(f"\n共 {len(rows)} 条配置：")
        head = ("id", "名称", "供应商", "模型", "用途", "启用", "测试通过", "要素完整", "视频能力")
        print("  " + " | ".join(head))
        for c in rows:
            print("  " + " | ".join([
                str(c.id),
                (c.name or "-")[:18],
                (c.provider or "-")[:16],
                (c.model or "-")[:28],
                ",".join(_usages_of(c)) or "-",
                _fmt(bool(c.is_active)),
                _fmt(c.last_test_ok),
                _fmt(_usable(c)),
                _fmt(is_video_capable(c)) if "video" in _usages_of(c) else "-",
            ]))

        print("\n各用途实际生效的配置：")
        bad = []
        for u in USAGES:
            cfg = _pick_config(rows, u)
            if cfg is None:
                why = "无候选（未勾选 / 已停用 / 要素不全" + (" / 无视频能力" if u == "video" else "") + "）"
                print(f"  {LABEL[u]:<2} 未生效 —— {why}")
                bad.append(u)
                continue
            ok = cfg.last_test_ok is True
            print(f"  {LABEL[u]:<2} #{cfg.id} {cfg.name or '(未命名)'} / {cfg.provider} / {cfg.model}"
                  f" —— {'已测试通过' if ok else '未测试通过'}")
            if not ok:
                bad.append(u)

        print("\n结论：")
        for u in ("analysis", "copy", "image"):
            state = "不可用" if u in bad else "可用"
            print(f"  工作坊·{LABEL[u]}模型：{state}")
        if "video" in bad:
            print("  创意工作台·视频模型：未生效（出片会走兜底分镜，不是真实视频）")
        print("\n提示：工作坊把「最近一次连通测试通过」作为付费调用的前提。"
              "若某用途显示已配置但未测试通过，请到「系统设置 → 大模型配置」点该条目的测试连接。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
