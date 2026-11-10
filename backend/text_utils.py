"""素材创作平台共用的文案安全裁剪工具。

V4.37：原 creative.py 绝大部分内容只服务于已下线的「素材管理」 Campaign 生产链路，
这里只保留「素材创作 → 营销推广设置」仍在使用的 `fit_text`。

V4.39 / F01：新增 `clip_report`，把「是否发生裁剪、裁掉了什么」显式返回。
此前 media_ad._build_fields 调用 fit_text 后丢弃裁剪标记，_validate 只比较长度，
于是 "Book in minutes." 被裁成 "Book in" 仍返回 valid=true。
"""
import re


def fit_text(text: str, limit: int) -> tuple[str, bool]:
    """按词边界裁到 limit 内，返回 (结果, 是否发生了裁剪)。

    广告文案里出现 "…upda" 这种半截词等于废稿，所以宁可丢词也不切断词。
    中文按字符裁，但会避开标点切分点。

    注意：本函数**只做几何裁剪，不保证语义完整**。调用方必须用
    `industry_profiles.is_complete_sentence` 与 `missing_protected` 判断是否可用，
    超长文案应走语义压缩而不是直接采用裁剪结果。
    """
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text, False
    if re.search(r"[\u4e00-\u9fa5]", text):
        cut = text[:limit]
        for i in range(len(cut) - 1, max(0, len(cut) - 8), -1):
            if cut[i] in "，。、；：,.;: ":
                return cut[:i].strip(), True
        return cut.rstrip("，。、；： "), True
    words = text.split()
    out = ""
    for w in words:
        cand = f"{out} {w}".strip()
        if len(cand) <= limit:
            out = cand
        else:
            break
    if not out:
        return text[:limit].rstrip(), True
    return out.rstrip(" ,.;:—-"), True


def clip_report(text: str, limit: int) -> dict:
    """返回一次裁剪的完整报告，供上层判断是否需要语义压缩 / 阻断。"""
    original = (text or "").strip()
    result, clipped = fit_text(original, limit)
    return {
        "original": original,
        "result": result,
        "limit": limit,
        "clipped": clipped,
        "lost": original[len(result):].strip() if clipped else "",
    }
