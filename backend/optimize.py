"""
素材优化引擎：把「标题再短一点、去掉数字、换成纯文字版式」这类自然语言要求，
翻译成对已生成素材的确定性调整，并逐条记录改了什么。

为什么不直接整段丢给模型：
- 投放人员的优化要求大多是具体动作（更短/去数字/突出某卖点/换版式），规则改写更快、更可解释；
- 没有配置模型时也必须可用，否则"优化"按钮等于摆设；
- 每条变更都要能给出 before → after，用户才知道这次优化到底动了什么。

配置了大模型时，服务层会先用模型重写文案，再用这里的规则兜底字数与结构。
"""
import re

from creative import ANGLE_MAP, COPY_SCHEMA, fit_text

# ----------------------------- 指令解析 -----------------------------
# 顺序有意义：先匹配"数字"这类互斥规则，再匹配泛化的"突出/强调"
RULE_DEFS = [
    ("shorter", "文案更短", ["更短", "短一点", "缩短", "简短", "精简", "简洁", "收敛", "压缩",
                            "shorter", "concise", "tighten", "trim"]),
    ("no_numbers", "去掉数字", ["不要数字", "去掉数字", "别用数字", "减少数字", "不出现数字",
                                "no numbers", "remove numbers", "without numbers", "no digits"]),
    ("numbers", "突出数字", ["突出数字", "强调数字", "带上数字", "加数字", "用数字",
                             "highlight numbers", "with numbers", "add numbers"]),
    ("longer", "文案更具体", ["更详细", "详细一点", "更具体", "展开", "加长", "补充说明", "多写",
                              "longer", "more detail", "specific"]),
    ("casual", "更口语", ["口语", "自然一点", "轻松", "随性", "接地气", "casual", "friendly",
                          "conversational"]),
    ("formal", "更正式", ["正式", "专业一点", "严谨", "formal", "professional"]),
    ("question", "改成疑问句", ["疑问句", "问句", "提问", "设问", "question", "ask"]),
    ("urgent", "加强行动号召", ["紧迫", "限时", "赶紧", "立刻", "马上", "促销感", "催",
                                "urgent", "hurry", "act now"]),
    ("no_brand", "标题去掉品牌名", ["不要品牌名", "去掉品牌", "不用产品名", "别带品牌",
                                    "no brand", "remove brand"]),
    ("template", "更换版式", ["版式", "模板", "排版", "纯文字", "大字", "评分卡", "对比",
                              "手机框", "界面", "折扣", "layout", "template"]),
    ("color", "更换主色", ["颜色", "配色", "主色", "色调", "蓝色", "红色", "绿色", "橙色",
                           "紫色", "黑色", "金色", "color", "palette"]),
    ("cta", "指定按钮文案", ["按钮", "cta", "call to action"]),
    ("emphasize", "突出指定卖点", ["突出", "强调", "主打", "重点", "聚焦",
                                   "emphasize", "highlight", "focus on"]),
]

# "突出数字""重点讲卖点"这类是泛指，不是具体卖点，不能当成关键词去匹配
GENERIC_ARGS = {"数字", "数据", "卖点", "标题", "文案", "内容", "产品", "品牌", "核心",
                "优势", "功能", "这一点", "它", "词", "关键词"}

TEMPLATE_WORDS = [
    (("纯文字", "大字", "字体", "无图"), "bigtype"),
    (("数字", "数据", "stat"), "stat"),
    (("评分", "星级", "好评", "口碑"), "rating"),
    (("折扣", "促销", "优惠", "倒计时", "券"), "promo"),
    (("手机", "界面", "录屏", "ugc", "截图"), "ugc"),
    (("对比", "前后", "分屏", "before"), "compare"),
]
COLOR_WORDS = [("蓝", "#2E75B6"), ("红", "#D64545"), ("绿", "#2F9E44"), ("橙", "#E8590C"),
               ("紫", "#7B5EA7"), ("金", "#C9A227"), ("黄", "#F2C14E"), ("黑", "#1C2733")]

EMPHASIZE_RE = re.compile(
    r"(?:突出|强调|主打|重点(?:讲|说|写|是|放在)?|聚焦|emphasize|highlight|focus on)\s*[：:]?\s*"
    r"[「\"'“‘]?([^，。,.；;、\n]{1,20})")
CTA_RE = re.compile(r"(?:按钮|CTA|cta)\s*(?:文案)?\s*(?:改成|改为|换成|写|用)\s*[「\"'“‘]?([^，。,\n]{2,20})")

FB_ENUM_MAP = {
    "download": "DOWNLOAD", "下载": "DOWNLOAD", "立即下载": "DOWNLOAD",
    "install": "INSTALL_MOBILE_APP", "安装": "INSTALL_MOBILE_APP",
    "learn more": "LEARN_MORE", "了解更多": "LEARN_MORE", "see more": "LEARN_MORE",
    "shop now": "SHOP_NOW", "购买": "SHOP_NOW", "立即购买": "SHOP_NOW",
    "sign up": "SIGN_UP", "注册": "SIGN_UP", "免费试用": "SIGN_UP", "试用": "SIGN_UP",
    "get offer": "GET_OFFER", "领取": "GET_OFFER", "领券": "GET_OFFER", "优惠": "GET_OFFER",
    "play": "PLAY_GAME", "开始游戏": "PLAY_GAME",
    "subscribe": "SUBSCRIBE", "订阅": "SUBSCRIBE",
}


def _clean_arg(raw: str) -> str:
    s = (raw or "").strip(" 「」\"'“”‘’。，,.;；:：")
    s = re.sub(r"(一点|一些|这个|那个|的|吧|呢|啊)$", "", s).strip()
    return "" if s in GENERIC_ARGS or len(s) < 2 else s


def parse_instruction(text: str) -> list[dict]:
    """返回命中的规则列表；未命中任何规则时返回空，由上层提示用户。"""
    low = (text or "").lower()
    rules, seen = [], set()
    for key, label, words in RULE_DEFS:
        if not any(w.lower() in low for w in words):
            continue
        if key in seen:
            continue
        arg = ""
        if key == "emphasize":
            m = EMPHASIZE_RE.search(text or "")
            arg = _clean_arg(m.group(1)) if m else ""
            if not arg:                       # 只说了"突出"没说是哪一点，交给模型/忽略
                continue
        elif key == "cta":
            m = CTA_RE.search(text or "")
            arg = _clean_arg(m.group(1)) if m else ""
            if not arg:
                continue
        elif key == "template":
            arg = next((t for ws, t in TEMPLATE_WORDS if any(w in low for w in ws)), "")
            if not arg:
                continue
        elif key == "color":
            # 明确给了 hex 就照用（投放人员常带品牌色卡），否则退到中文色名映射
            hexm = re.search(r"#?\b([0-9a-fA-F]{6})\b", text or "")
            if hexm:
                arg = "#" + hexm.group(1).upper()
            else:
                arg = next((hexv for w, hexv in COLOR_WORDS if w in (text or "")), "")
            if not arg:
                continue
        seen.add(key)
        rules.append({"key": key, "label": label, "arg": arg})
    return rules


# ----------------------------- 字段变换 -----------------------------
def _strip_digits(s: str) -> str:
    out = re.sub(r"[¥$€£]?\s?\d[\d.,]*\s?(?:%|％|percent|万|亿|million|billion|[KMBkmb]|\+|-star|x)?",
                 "", s or "", flags=re.I)
    out = re.sub(r"(\s*[—\-–]\s*)+", " ", out)     # 去掉数字后留下的孤立破折号
    # 删掉数字后常留下悬空的介词（"asleep within"），一并收掉才算成句
    out = re.sub(r"\s+(?:within|in|for|over|under|about|after|before|than|up to|nearly|"
                 r"more than|at|by|of)\s*([.!?]?)$", r"\1", out, flags=re.I)
    return _tidy(out)


def _fit(s: str, limit: int) -> str:
    return fit_text(s, limit)[0]


def _tidy(s: str) -> str:
    s = re.sub(r"\s{2,}", " ", s or "")
    return s.strip(" \t-—·|")


def _sentences_pool(out: dict, keys: list[str]) -> list[str]:
    """把同组的文案拆成句子池，用于"缩短时换一句完整的"，而不是把原句砍半。"""
    pool = []
    for k in keys:
        v = out.get(k)
        for x in (v if isinstance(v, list) else [v]):
            if not isinstance(x, str):
                continue
            for seg in re.split(r"(?<=[.!?])\s+", x):
                seg = _tidy(seg)
                if 8 <= len(seg) <= 80 and seg not in pool:
                    pool.append(seg)
    return pool


FILLER_RE = re.compile(r"\b(just|really|very|actually|simply|literally|quite|pretty|truly|super)\b\s*", re.I)


def _luma(hexv: str) -> int:
    """粗略亮度：用来判断主色上叠白字还能不能看清。"""
    try:
        r, g, b = (int(hexv[1:3], 16), int(hexv[3:5], 16), int(hexv[5:7], 16))
    except (ValueError, IndexError):
        return 0
    return int(0.299 * r + 0.587 * g + 0.114 * b)


def _trim_filler(s: str) -> str:
    """删掉不承载信息的填充词。"更短"里唯一既确定不改语义、又真能减字的手段。

    `A calmer mind, in just 10 minutes a day` → `A calmer mind, in 10 minutes a day`
    """
    t = FILLER_RE.sub("", s)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,;:-—")
    t = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", t)
    if t and s[:1].isupper() and t[:1].islower():
        t = t[0].upper() + t[1:]
    # 删完只剩碎片就不要
    if len(re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]", t)) < 2:
        return ""
    return t


def _clip_smart(s: str, target: int) -> str:
    """只在"能保证语义完整"的位置断开：标点处、或去掉尾部介词短语。

    不用 fit_text 硬裁——英文标题按词截断几乎必然留下
    "Calm, without the extra" 这种残句，那种素材投不出去。
    所有规则都不成立时返回空串，由调用方保留原句。
    """
    # ① 删填充词：语义等价，优先做
    trim = _trim_filler(s)
    if trim and len(trim) < len(s) and len(trim) >= 8:
        return trim
    # ② 标点处断开
    for sep in (" — ", " - ", ": ", "; ", ", "):
        if sep in s:
            head = s.split(sep)[0].strip(" ,;:-—")
            if 8 <= len(head) <= target:
                return head
    # 可断开的介词只列"删掉后主句仍完整"的。
    # `to` 故意不在列表里：`the shorter way to the same result` 断在 to 前会得到
    # `The shorter way` 这种悬空短语（way / path / route 都需要 to 补语）。
    m = re.match(r"^(.{8,}?)\s+(?:without|with|for|that|which|but|from|in|on)\s+.+$",
                 s, re.I)
    if m and len(m.group(1)) <= target:
        return m.group(1).strip(" ,;:-—")
    return ""


def _shorten(s: str, target: int, pool: list[str], avoid: set | None = None) -> tuple[str, bool]:
    """缩短标题：换一句本来就短且完整的，或断在标点/介词短语处；否则保持原句。

    返回 (新值, 是否改动)。原句仍在平台字数上限内，
    所以"不改"永远好于"改出一个投不出去的残句"。
    """
    if not isinstance(s, str) or len(s) <= target:
        return s, False
    avoid = avoid or set()
    cands = [p for p in pool if p != s and p not in avoid and 8 <= len(p) <= target]
    if cands:
        return min(cands, key=len), True
    cut = _clip_smart(s, target)
    if cut and cut not in avoid and len(cut) >= max(8, int(len(s) * 0.45)):
        return cut, True
    return s, False


def _strip_digits_safe(s: str, pool: list[str], limit: int,
                      avoid: set | None = None) -> str:
    """去数字：剥完不成句就换一句不含数字的完整句，都没有就保留原句。"""
    avoid = avoid or set()
    stripped = _strip_digits(s)
    if len(stripped) >= max(6, int(len(s) * 0.45)):
        return stripped
    cands = [p for p in pool if p != s and p not in avoid
             and not re.search(r"\d", p) and 6 <= len(p) <= limit]
    if cands:
        return min(cands, key=len)
    return s


def _headline_keys(platform: str) -> list[str]:
    return [f["key"] for f in (COPY_SCHEMA.get(platform) or []) if f["key"] in ("headline", "title")]


def _desc_keys(platform: str) -> list[str]:
    return [f["key"] for f in (COPY_SCHEMA.get(platform) or [])
            if f["key"] in ("description", "primary_text", "body")]


def _limit_of(platform: str, key: str, default: int = 40) -> int:
    for f in COPY_SCHEMA.get(platform) or []:
        if f["key"] == key:
            return f["max"]
    return default


def _edit(fields: dict, key: str, fn, limit: int) -> list[dict]:
    """对一个字段（可能是字符串或列表）应用变换，返回变更记录。"""
    v = fields.get(key)
    changes = []
    if isinstance(v, list):
        new = []
        for x in v:
            nv = _fit(fn(str(x)), limit) if x else x
            new.append(nv)
            if nv != x:
                changes.append({"field": key, "before": str(x), "after": nv})
        fields[key] = new
    elif isinstance(v, str) and v:
        nv = _fit(fn(v), limit)
        if nv and nv != v:
            fields[key] = nv
            changes.append({"field": key, "before": v, "after": nv})
    return changes


def apply_rules(fields: dict, rules: list[dict], platform: str,
                lang: str = "en", angle_key: str = "benefit",
                product: str = "", base_template: str = "",
                metrics: list | None = None) -> dict:
    """按规则改写字段。返回 {fields, applied, template, brand_color, warnings}。"""
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in (fields or {}).items()}
    applied, warnings = [], []
    template = base_template or (ANGLE_MAP.get(angle_key) or {}).get("template", "bigtype")
    brand_color = ""
    hkeys, dkeys = _headline_keys(platform), _desc_keys(platform)

    for r in rules:
        key, label, arg = r["key"], r["label"], r.get("arg") or ""
        changes = []

        if key == "shorter":
            # 候选池按字段类型隔离：标题只从标题里换，避免把描述整句搬成标题（读起来像复制）。
            hpool, dpool = _sentences_pool(out, hkeys), _sentences_pool(out, dkeys)
            used = {x for k in hkeys + dkeys
                    for x in (out.get(k) if isinstance(out.get(k), list) else [out.get(k)])
                    if isinstance(x, str)}          # 已在用的句子不再当候选，避免三条标题变同一句
            kept = 0
            for k in hkeys + dkeys:
                lim = _limit_of(platform, k)
                target = int(lim * (0.7 if k in hkeys else 0.8))
                own = [p for p in (hpool if k in hkeys else dpool) if p not in used]
                v = out.get(k)
                if isinstance(v, list):
                    new_vals = []
                    for x in v:
                        nv, changed = _shorten(x, target, own)
                        if changed:
                            changes.append({"field": k, "before": x, "after": nv})
                            used.add(nv)
                        elif isinstance(x, str) and len(x) > target:
                            kept += 1
                        new_vals.append(nv)
                    out[k] = new_vals
                elif isinstance(v, str) and v:
                    nv, changed = _shorten(v, target, own)
                    if changed:
                        changes.append({"field": k, "before": v, "after": nv})
                        used.add(nv)
                    elif len(v) > target:
                        kept += 1
                    out[k] = nv
            if kept:
                warnings.append(f"有 {kept} 条文案已经是该方向最短的完整表述，保留原句（仍在平台字数上限内）")
            applied.append({"rule": key, "label": label,
                            "note": "优先换成本来就短且完整的句子；裁得太狠（会变残句）就保留原句",
                            "changes": changes})

        elif key == "no_numbers":
            pool = _sentences_pool(out, hkeys + dkeys)
            avoid = {x for k in hkeys + dkeys
                     for x in (out.get(k) if isinstance(out.get(k), list) else [out.get(k)])
                     if isinstance(x, str)}
            kept = 0
            for k in hkeys + dkeys:
                lim = _limit_of(platform, k)
                v = out.get(k)
                if isinstance(v, list):
                    new_vals = []
                    for x in v:
                        nv = _strip_digits_safe(x, pool, lim, avoid)
                        if nv != x:
                            changes.append({"field": k, "before": x, "after": nv})
                            avoid.add(nv)
                        elif isinstance(x, str) and re.search(r"\d", x):
                            kept += 1
                        new_vals.append(nv)
                    out[k] = new_vals
                elif isinstance(v, str) and v:
                    nv = _strip_digits_safe(v, pool, lim, avoid)
                    if nv != v:
                        changes.append({"field": k, "before": v, "after": nv})
                        avoid.add(nv)
                    elif re.search(r"\d", v):
                        kept += 1
                    out[k] = nv
            if not changes:
                warnings.append("文案里已经没有数字，这条要求没有产生改动")
            if kept:
                warnings.append(f"有 {kept} 条文案去掉数字后不成句，已保留原句（仍含数字），"
                                f"需要人工改写或配置大模型")
            applied.append({"rule": key, "label": label,
                            "note": "删掉了所有数字与货币符号；proof 方向的说服力会下降",
                            "changes": changes})

        elif key == "numbers":
            metric = next((str(m) for m in (metrics or []) if m), "")
            if metric:
                for k in hkeys:
                    cur = out.get(k)
                    head = cur[0] if isinstance(cur, list) and cur else (cur if isinstance(cur, str) else "")
                    if head and metric not in head:
                        nv = _fit(f"{metric} — {head}", _limit_of(platform, k))
                        if isinstance(cur, list) and cur:
                            cur[0] = nv
                        else:
                            out[k] = nv
                        changes.append({"field": k, "before": head, "after": nv})
            else:
                warnings.append("产品事实里没有可用的量化指标，无法执行「突出数字」")
            applied.append({"rule": key, "label": label,
                            "note": "把第一个可量化指标放到标题前，数字必须能回溯到落地页",
                            "changes": changes})

        elif key == "longer":
            bodies = [x for k in dkeys for x in
                      (out.get(k) if isinstance(out.get(k), list) else [out.get(k)]) if isinstance(x, str) and x]
            for k in hkeys:
                lim = _limit_of(platform, k)
                cur = out.get(k)
                head = cur[0] if isinstance(cur, list) and cur else (cur if isinstance(cur, str) else "")
                cand = next((b for b in bodies if len(b) > len(head or "") and len(b) <= lim), "")
                if cand and cand != head:
                    if isinstance(cur, list) and cur:
                        cur[0] = cand
                    else:
                        out[k] = cand
                    changes.append({"field": k, "before": head, "after": cand})
            if not changes:
                warnings.append("现有正文里没有更具体、且放得进标题的句子")
            applied.append({"rule": key, "label": label,
                            "note": "用正文里信息量更大的一句替换标题（需在字数上限内）",
                            "changes": changes})

        elif key in ("casual", "formal"):
            table = ({"Learn more": "See how", "Discover": "Check out", "Download": "Get it",
                      "Get offer": "Grab it", "Sign up": "Join", "Shop now": "Take a look"}
                     if key == "casual" else
                     {"Get it": "Download", "See how": "Learn more", "Check out": "Discover",
                      "Grab it": "Get offer", "Join": "Sign up"})
            for k in hkeys + dkeys:      # 不动 cta：平台按钮是枚举值，改成自由文本会投不出去
                cur = out.get(k)
                if isinstance(cur, str) and cur:
                    nv = cur
                    for a, b in table.items():
                        nv = re.sub(re.escape(a), b, nv, flags=re.I)
                    if nv != cur:
                        out[k] = nv
                        changes.append({"field": k, "before": cur, "after": nv})
            if not changes:
                warnings.append("当前文案已经是模板句，没有可替换的口语/正式表达；配置大模型后可整句重写")
            applied.append({"rule": key, "label": label,
                            "note": "按口语/正式词表替换动词与 CTA", "changes": changes})

        elif key == "question":
            hooks = ((ANGLE_MAP.get(angle_key) or {}).get("hooks") or {}).get(lang) or []
            q = next((h for h in hooks if "?" in h), "")
            done = False
            for k in hkeys:
                lim = _limit_of(platform, k)
                cur = out.get(k)
                head = cur[0] if isinstance(cur, list) and cur else (cur if isinstance(cur, str) else "")
                if not head or "?" in head:
                    continue
                nv = _fit(q.replace("{p}", product).replace("{b}", head) if q else f"{head}?", lim)
                if not nv.endswith("?"):
                    nv = _fit(nv + "?", lim)
                if isinstance(cur, list) and cur:
                    cur[0] = nv
                else:
                    out[k] = nv
                changes.append({"field": k, "before": head, "after": nv})
                done = True
                break
            if not done:
                warnings.append("标题已经是问句，或没有可用的问句模板")
            applied.append({"rule": key, "label": label,
                            "note": "优先替换为该方向的现成问句钩子，没有才在原句尾加问号",
                            "changes": changes})

        elif key == "urgent":
            cur = out.get("cta")
            nv = "Get offer" if platform != "Facebook" else "GET_OFFER"
            if cur != nv:
                out["cta"] = nv
                changes.append({"field": "cta", "before": str(cur or ""), "after": nv})
            for k in dkeys:
                lim = _limit_of(platform, k)
                cur2 = out.get(k)
                if isinstance(cur2, str) and cur2 and not re.match(r"^(now|限量|now:)", cur2, re.I):
                    nv2 = _fit(f"Now: {cur2}", lim)
                    if nv2 != cur2:
                        out[k] = nv2
                        changes.append({"field": k, "before": cur2, "after": nv2})
            warnings.append("已加入时效/行动指向表述，投放前请确认活动或优惠真实存在")
            applied.append({"rule": key, "label": label,
                            "note": "CTA 换成领取类，描述前加 Now: 强化即时性", "changes": changes})

        elif key == "no_brand":
            if not product:
                warnings.append("未识别到产品名，无法执行「去掉品牌名」")
            else:
                for k in hkeys:
                    cur = out.get(k)
                    vals = cur if isinstance(cur, list) else [cur]
                    new = []
                    for x in vals:
                        if not isinstance(x, str) or not x:
                            new.append(x); continue
                        nv = _tidy(re.sub(rf"(?<![A-Za-z]){re.escape(product)}(?![A-Za-z])", "", x, flags=re.I))
                        if len(nv) < 6:
                            new.append(x)          # 删完太短，等于把标题废了
                            continue
                        if nv != x:
                            changes.append({"field": k, "before": x, "after": nv})
                        new.append(nv)
                    out[k] = new if isinstance(cur, list) else new[0]
            applied.append({"rule": key, "label": label,
                            "note": "标题里不再出现产品名（品牌仍通过画面角标呈现）", "changes": changes})

        elif key == "emphasize":
            found = False
            lim = _limit_of(platform, hkeys[0] if hkeys else "headline")
            pool = []
            for k in dkeys + hkeys:
                v = out.get(k)
                pool += v if isinstance(v, list) else [v]
            # 目标词可能写成"5-star 评分"这种中英混合，拆出能对上原文的片段
            frags = [arg] + re.findall(r"[A-Za-z0-9][A-Za-z0-9 .+\-%]{2,}", arg)
            clause = ""
            for frag in frags:
                clause = next((_tidy(str(x)) for x in pool
                               if isinstance(x, str) and frag.lower() in x.lower()), "")
                if clause:
                    break
            if not clause:      # 退一步：用命中的量化指标找原文句
                hit = next((str(m) for m in (metrics or [])
                            if str(m) and (str(m).lower() in arg.lower()
                                           or arg.lower() in str(m).lower())), "")
                if hit:
                    clause = next((_tidy(str(x)) for x in pool
                                   if isinstance(x, str) and hit.lower() in x.lower()), "")
            if (not clause and re.search(r"[A-Za-z]", arg)
                    and not re.search(r"[\u4e00-\u9fa5]", arg)
                    and len(arg) >= 8 and len(arg.split()) >= 2):
                clause = arg          # 纯英文且够长的目标短语才能直接当标题，"free" 这种单词不行
            if not clause:
                warnings.append(f"文案与事实里都没有「{arg}」的现成英文表述，已跳过这条要求")
            # 放不进标题就不替换：硬裁会出残句
            cand = clause if clause and len(clause) <= lim else ""
            for k in hkeys:
                cur = out.get(k)
                head = cur[0] if isinstance(cur, list) and cur else (cur if isinstance(cur, str) else "")
                nv = cand
                if nv and nv != head:
                    if isinstance(cur, list) and cur:
                        cur[0] = nv
                    else:
                        out[k] = nv
                    changes.append({"field": k, "before": head or "", "after": nv})
                    found = True
                break
            if not found and clause:
                warnings.append(f"「{arg}」已找到原文表述但放不进标题字数上限，已跳过")
            applied.append({"rule": key, "label": f"突出「{arg}」",
                            "note": "把该卖点提到标题第一句，原描述保留作为支撑", "changes": changes})

        elif key == "cta":
            target = arg
            if platform == "Facebook":
                enum = FB_ENUM_MAP.get(target.lower())
                if not enum:
                    enum = next((v for k2, v in FB_ENUM_MAP.items() if k2 in target.lower()), "LEARN_MORE")
                out["cta"] = enum
            else:
                out["cta"] = _fit(target, _limit_of(platform, "cta", 20))
            before = str(fields.get("cta") or "")
            if out["cta"] != before:
                changes.append({"field": "cta", "before": before, "after": out["cta"]})
            applied.append({"rule": key, "label": label,
                            "note": f"按钮文案改为「{target}」", "changes": changes})

        elif key == "template":
            template = arg
            applied.append({"rule": key, "label": label,
                            "note": f"图片版式改为 {arg}，文案结构不变", "changes": []})

        elif key == "color":
            brand_color = arg
            applied.append({"rule": key, "label": label,
                            "note": f"主色改为 {arg}，已重渲染的图片全部换色", "changes": []})
            if _luma(arg) > 200:
                warnings.append(f"主色 {arg} 偏亮，图上白字对比度可能不足，建议换同色系更深的一档")

    uniq = list(dict.fromkeys(warnings))
    return {"fields": out, "applied": applied, "template": template,
            "brand_color": brand_color, "warnings": uniq}
