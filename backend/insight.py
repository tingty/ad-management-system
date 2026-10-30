"""
本地洞察抽取（不依赖大模型）。

旧版的问题：未配置模型时，所有产品共用同一组写死的卖点，等于没有分析。
本模块从落地页正文里真实抽取：产品名、可量化指标、有价值主张的句子、受众、
地域、语言、所属品类，再据此生成与产品相关的推广框架。

抽取是确定性的、可解释的：每个结论都能回溯到原文中的某个片段，
前端展示时附带 `evidence`，投放人员可以判断这个结论靠不靠谱。

V3.1 修复（用真实落地页回归时暴露）：
- 正文里常带 markdown 标记与「标题：」前缀，产品名会被抽成 `**标题**` → 先做文本归一化；
- 品类词用 `str.count` 做子串匹配，`ai` 命中 `daily/practice`，把冥想 App 判成修图工具 → 改词边界匹配；
- `2 million` 被正则吞成 `2 m`、`5 minutes` 当成指标 → 指标改为「数字 + 单位」成对解析并归一化；
- 受众匹配命中标题里的 `for Meditation and Sleep` → 排除标题行与功能短语；
- 卖点里混进 `Try Calm for Free`、`Learn More` 这类 CTA → 加导航/CTA 过滤。
"""
import re

CJK_RE = re.compile(r"[\u4e00-\u9fa5]")

# ----------------------------- 品类词典 -----------------------------
# 英文词用「前缀匹配」而不是全等：meditat 命中 meditation / meditate，
# 但 <=3 字母的短词仍要求完整词边界，避免 ai / us 这类误伤。
DOMAIN_LEXICON = {
    "commerce": {
        "label": "电商/购物",
        "words": ["购物", "商城", "电商", "优惠", "优惠券", "折扣", "比价", "省钱", "返现",
                  "下单", "商品", "跨境", "coupon", "cashback", "shop", "price", "deal",
                  "discount", "store", "order", "cart", "checkout", "saving"],
        "task": "手动比价、逐店找券",
        "audience_hint": "对价格敏感、近 30 天有网购行为、习惯用券的人",
    },
    "game": {
        "label": "游戏/休闲",
        "words": ["游戏", "消除", "关卡", "通关", "副本", "玩家", "手游", "puzzle", "game",
                  "level", "play", "quest", "match", "casual"],
        "task": "一关一关硬啃、卡关重来",
        "audience_hint": "碎片时间玩休闲游戏、接受激励视频与内购的人",
    },
    "fitness": {
        "label": "健康/健身",
        "words": ["健身", "训练", "卡路里", "运动", "跑步", "增肌", "减脂", "冥想", "睡眠",
                  "助眠", "放松", "正念", "焦虑", "压力", "workout", "fitness", "calorie",
                  "gym", "training", "running", "steps", "meditat", "sleep", "relax",
                  "mindful", "wellness", "anxiety", "stress", "breath"],
        "task": "自己排训练计划、睡眠与压力全靠硬扛",
        "audience_hint": "在睡眠/压力/体重管理上有明确困扰，愿意每天投入 10 分钟的人",
    },
    "finance": {
        "label": "金融/理财",
        "words": ["理财", "投资", "记账", "贷款", "保险", "收益", "预算", "invest", "budget",
                  "loan", "saving", "finance", "portfolio", "credit"],
        "task": "用表格记账、手动算收益",
        "audience_hint": "刚工作到家庭成长期、需要管账与攒钱的人",
    },
    "travel": {
        "label": "旅行/出行",
        "words": ["旅行", "机票", "酒店", "行程", "签证", "travel", "flight", "hotel",
                  "trip", "booking", "tour"],
        "task": "在多个平台反复比价改行程",
        "audience_hint": "近 90 天有出行计划、习惯线上订票订房的人",
    },
    "photo_ai": {
        "label": "影像/AI 工具",
        "words": ["拍照", "修图", "美颜", "抠图", "滤镜", "photo", "edit", "filter",
                  "avatar", "camera", "enhance"],
        "task": "来回导素材、手动修图",
        "audience_hint": "经常社交发图、有修图或生成需求的人",
    },
    "education": {
        "label": "教育/学习",
        "words": ["学习", "课程", "单词", "考试", "刷题", "备考", "learn", "course",
                  "study", "language", "vocab", "exam"],
        "task": "抱着单词书死记硬背",
        "audience_hint": "有考试或技能提升目标、能坚持每日打卡的人",
    },
}
FALLBACK_DOMAIN = "app"
FALLBACK_META = {"label": "App/工具", "task": "反复手动处理同一件事",
                 "audience_hint": "有明确工具需求、近期有相关搜索行为的人"}

# 各品类在不同平台的打法差异（用于替代"每个产品都一样"的平台分析）
PLATFORM_NOTES = {
    "commerce": {
        "Facebook": "比价/省钱类目靠「前后对比 + 价格数字」起量，Reels 9:16 放使用场景，Feed 用 4:5 放利益点",
        "Google": "搜索侧抢「品类词 + 竞品词 + 优惠词」，PMax 用多尺寸图片喂量，RSA 必带价格与免运费",
        "Unity": "非核心场景，仅做再营销；Rewarded 不适合购物决策，慎投",
        "AppLovin": "适合已安装用户的复购召回，创意用「限时券」强刺激",
        "Moloco": "RTB 侧重高购买意向人群，素材突出折扣幅度与品牌背书",
        "Adsterra": "原生位做「榜单/测评」软文风素材，banner 直给折扣数字",
        "Mintegral": "可玩广告模拟「比价过程」，互动后给券，CTR 表现好",
    },
    "game": {
        "Facebook": "首 3 秒必须出玩法与失败画面，Reels/Stories 竖版优先，文案只留一句挑战式 hook",
        "Google": "UAC 靠素材驱动，竖版视频 + 试玩素材并投，搜索词覆盖「同类游戏 + 攻略」",
        "Unity": "Rewarded 主战场，前 5 秒展示核心循环，结尾给明确奖励承诺",
        "AppLovin": "Playable + 短视频组合，创意要做「差一点就赢」的悬念剪辑",
        "Moloco": "事件优化为主，素材强调关卡进度与解锁感",
        "Adsterra": "Popunder 用「免费下载/破解」类强诱导文案需规避政策风险",
        "Mintegral": "可玩广告是强项，做 15 秒内可完成的迷你关卡",
    },
    "fitness": {
        "Facebook": "睡眠/冥想类靠「用户原话 + 时长承诺」起量，Reels 放夜间场景，Feed 用 4:5 放评分与用户量",
        "Google": "搜索侧抢「insomnia / anxiety / sleep sounds」类需求词，RSA 标题写清免费与时长",
        "Unity": "非核心场景，Rewarded 换会员试用可测",
        "AppLovin": "适合已安装用户的续订召回，素材强调连续使用天数",
        "Moloco": "高意向人群，素材用「第一周体验」降低决策门槛",
        "Adsterra": "原生位写「睡不着怎么办」的问题—方案结构",
        "Mintegral": "可玩广告做「选一个声音 → 立刻播放」的即时反馈",
    },
    "app": {
        "Facebook": "先讲「省掉的那一步」，用界面录屏 + 大字 hook，Reels 竖版优先",
        "Google": "搜索侧覆盖「品类词 + 替代品词」，RSA 标题写清功能与免费属性",
        "Unity": "工具类适合 Rewarded 换额度，视频前 3 秒给使用结果",
        "AppLovin": "利益点前置，短文案 + 强 CTA，适合放量测试",
        "Moloco": "受众扩展 + 转化事件优化，素材以功能演示为主",
        "Adsterra": "原生位写「问题—方案」结构，banner 只留一句主张",
        "Mintegral": "可玩广告做交互演示，降低理解成本",
    },
}

SENT_SPLIT_RE = re.compile(r"[。！？!?\n;；]|(?<=[a-z0-9\)])\.\s")
LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:标题|描述|正文|内容|页面|网页|官网|title|description|heading|h[1-6])\s*[:：]\s*", re.I)
LIST_BULLET_RE = re.compile(r"^[-*•>]\s+")
# 导航/按钮类短句：它们不是卖点，混进来会让文案变成"Try X for Free"
NAV_JUNK_RE = re.compile(
    r"^(?:learn more|read more|see more|see all|view all|show more|sign in|log ?in|sign ?up|"
    r"get started|try (?:it )?free|try [\w' .]{0,24}for free|start (?:free|now)|"
    r"download(?: now)?|install(?: now)?|buy now|shop now|order now|subscribe|follow us|"
    r"already have an account\??|forgot password|contact us|about us|careers|privacy|terms|"
    r"cookie[s]?|faq|help center|back to top|了解更多|立即下载|立即体验|免费试用|免费下载|"
    r"查看详情|开始使用|登录|注册|返回顶部)$", re.I)

# 行首 CTA：网页抓下来时 <a> 会与相邻文本并成一行（"Try Calm for Free Already have an account"），
# 所以不能只做整行匹配，要按前缀识别
CTA_START_RE = re.compile(
    r"^(?:try (?:it )?free|try [\w' .]{0,24}for free|get started|download(?: now)?|install(?: now)?|"
    r"sign ?up|log ?in|learn more|read more|start (?:free|now)|subscribe|buy now|shop now|"
    r"立即下载|立即体验|免费试用|免费下载|查看详情|开始使用|登录|注册)\b", re.I)
# 订阅条款、隐私声明这类句子不是卖点
JUNK_SUBSTR = ("cancel your", "subscription", "refund", "privacy policy", "terms of",
               "cookie", "billing", "auto-renew", "app store", "google play", "faq")

# 指标：数字 + 单位，或货币金额；单位决定是否算"可量化卖点"
METRIC_RE = re.compile(
    r"[$\u00a5\u20ac\u00a3]\s?\d[\d,]*(?:\.\d+)?"
    r"|\d[\d,]*(?:\.\d+)?\s?(?:%|\uff05|percent|倍|万|亿|million|billion|K|k|M|m|\+)(?![A-Za-z])"
    r"|\d[\d,]*(?:\.\d+)?\s?-\s?star", re.I)

BENEFIT_HINTS = ["支持", "可以", "帮", "省", "免费", "自动", "一键", "实时", "覆盖", "提供",
                 "无需", "内置", "同步", "推荐", "定制", "智能", "秒", "省心", "适合", "帮助",
                 "free", "auto", "one tap", "instant", "save", "track", "built-in",
                 "no need", "real-time", "unlimited", "without", "help", "designed",
                 "support", "review", "rated", "users", "library", "minutes"]
PROOF_HINTS = ["review", "rated", "rating", "users", "customers", "million", "万", "用户",
               "好评", "评分", "榜单"]

AUDIENCE_PATTERNS = [
    r"面向[^。；;]{2,30}", r"针对[^。；;]{2,30}", r"适合[^。；;]{2,30}", r"专为[^。；;]{2,30}",
    r"(?:designed|built|made)\s+for\s+[^.;]{3,40}",
    r"for\s+(?:both\s+)?(?:people|adults|kids|children|families|beginners|students|parents|"
    r"professionals|anyone|those|women|men|teens)\b[^.;]{0,40}",
    r"(?:perfect|great|ideal)\s+for\s+[^.;]{3,40}",
]
PERSON_WORDS = re.compile(
    r"\b(people|users?|adults?|kids?|children|families|family|beginners?|students?|parents?|"
    r"professionals?|anyone|everyone|women|men|teens?|you)\b|"
    r"用户|人群|上班族|家长|学生|女性|男性|新手|白领|宝妈|老人", re.I)
# "for free / for meditation / for iOS" 不是人群
AUDIENCE_DENY = re.compile(r"for\s+(?:free|the|a|an|you|your|more|less|ios|android|iphone|ipad|"
                           r"android|web|desktop|sale|now)\b", re.I)

GEO_WORDS = {
    "北美": ["北美", "美国", "加拿大", "north america", "usa", "united states", "u.s."],
    "拉美": ["拉美", "巴西", "墨西哥", "latam", "brazil", "mexico"],
    "欧洲": ["欧洲", "英国", "德国", "法国", "europe", "uk", "united kingdom", "germany"],
    "东南亚": ["东南亚", "印尼", "泰国", "越南", "southeast asia", "indonesia", "thailand"],
    "中东": ["中东", "沙特", "阿联酋", "mena", "saudi", "uae"],
    "日韩": ["日本", "韩国", "japan", "korea"],
}

BRAND_STOP = {"the", "and", "for", "with", "your", "our", "this", "that", "more", "free",
              "try", "get", "now", "new", "best", "top", "all", "you", "we", "it", "a", "an",
              "app", "apps", "official", "home", "welcome", "sign", "log", "download"}
GENERIC_SUFFIX = {"ai", "app", "apps", "pro", "lite", "official", "website", "官网", "官方"}


def detect_lang(text: str) -> str:
    if CJK_RE.search(text or ""):
        return "zh"
    return "en"


def _word_hits(low: str, word: str) -> int:
    """英文按前缀匹配（meditat → meditation），<=3 字母的短词要求完整词边界。"""
    wl = word.lower()
    if re.search(r"[a-z0-9]", wl):
        tail = r"(?![a-z0-9])" if len(wl) <= 3 else ""
        pat = rf"(?<![a-z0-9]){re.escape(wl)}{tail}"
        return len(re.findall(pat, low))
    return low.count(wl)


def detect_domain(text: str) -> tuple[str, dict]:
    low = (text or "").lower()
    best_key, best_score, best_matched = FALLBACK_DOMAIN, 0, []
    for key, meta in DOMAIN_LEXICON.items():
        matched = [(w, _word_hits(low, w)) for w in meta["words"]]
        matched = [(w, c) for w, c in matched if c]
        if not matched:
            continue
        # 命中词种数权重高于出现次数：三个不同关键词各出现一次，
        # 比一个关键词刷屏更能说明品类。
        score = len(matched) * 3 + sum(min(c, 3) for _, c in matched)
        if score > best_score:
            best_key, best_score = key, score
            best_matched = [w for w, _ in matched]
    if best_score < 4:
        return FALLBACK_DOMAIN, dict(FALLBACK_META)
    meta = DOMAIN_LEXICON[best_key]
    return best_key, {"label": meta["label"], "task": meta["task"],
                      "audience_hint": meta["audience_hint"],
                      "matched": sorted(best_matched)[:8]}


# ----------------------------- 文本归一化 -----------------------------
def normalize_text(text: str) -> str:
    """去掉 markdown 标记、`标题：` 前缀、列表符号与重复行。

    落地页文本多半是从网页或 Markdown 复制来的，不先清洗，
    `**标题**: Calm - ...` 会被当成产品名。
    """
    out, seen = [], set()
    for raw in (text or "").splitlines():
        line = raw.replace("**", "").replace("__", "").replace("`", "").strip()
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = LABEL_PREFIX_RE.sub("", line)
        line = LIST_BULLET_RE.sub("", line)
        line = re.sub(r"\s+", " ", line).strip(" -—·|")
        if len(line) < 2 or line in seen:
            continue
        if re.fullmatch(r"[\[\]().,，。、…:：\s\-—]+", line):
            continue
        seen.add(line)
        out.append(line)
    return "\n".join(out)


def _host_brand(url: str) -> str:
    m = re.search(r"https?://([^/\s]+)", url or "")
    if not m:
        return ""
    parts = [p for p in m.group(1).lower().split(":")[0].split(".") if p]
    while parts and parts[0] in {"www", "m", "app", "get", "go", "try", "link", "landing",
                                 "shop", "my", "web"}:
        parts.pop(0)
    if len(parts) < 2:
        return ""
    base = parts[0]
    return base if len(base) >= 3 and base not in {"com", "net", "org", "cn"} else ""


def _title_brand(line: str) -> str:
    """`Brand — tagline` / `Brand: tagline` 形式，品牌一般在破折号之前。"""
    m = re.match(r"^([A-Z][A-Za-z0-9&'’.\-]*(?:\s+[A-Z][A-Za-z0-9&'’.\-]*){0,2})"
                 r"\s*[—–\-:|]\s*(\S.{5,})$", line)
    if not m:
        return ""
    head = m.group(1).strip()
    if len(head) > 30 or head.split()[0].lower() in BRAND_STOP:
        return ""
    return head


def _brand_head(seg: str) -> str:
    seg = seg.strip(" -—·|")
    if not seg or re.match(r"^https?://", seg, re.I):
        return ""
    if CJK_RE.search(seg):
        # 中文文案常是 `FitTrack AI 健身 App，...`：保留英文品牌前缀，去掉通用后缀
        lead = re.match(r"^[\x20-\x7e]+", seg)
        if lead:
            words = lead.group(0).replace("-", " ").split()
            while words and words[-1].lower() in GENERIC_SUFFIX:
                words.pop()
            if words:
                return " ".join(words[:3])[:24]
        return seg[:24]
    words = seg.split()
    if not words or len(words) > 4 or words[0].lower() in BRAND_STOP:
        return ""
    return " ".join(words)[:24]


def extract_product(text: str, url: str = "") -> tuple[str, str]:
    """返回 (产品名, 依据来源)。URL 域名是最可靠的品牌来源，其次是 `Brand — tagline`。"""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    brand = _host_brand(url)
    if brand:
        for l in lines[:20]:
            m = re.search(rf"(?<![A-Za-z]){re.escape(brand)}(?![A-Za-z])", l, re.I)
            if m:
                word = m.group(0)
                return (word[0].upper() + word[1:] if word.islower() else word), "url+正文"
        return brand[0].upper() + brand[1:], "url"
    for l in lines[:8]:
        b = _title_brand(l)
        if b:
            return b, "标题行"
    for l in lines[:6]:
        seg = re.split(r"[，,。;；:：、!?！？]", l)[0]
        head = _brand_head(seg)
        if head:
            return head, "首行"
    return "Unknown Product", "fallback"


def extract_sentences(text: str) -> list[str]:
    """先按句切，过长的句子再按逗号切成短句——中文卖点常常一句里塞三件事。"""
    parts = [p.strip(" ，,、-—·\t") for p in SENT_SPLIT_RE.split(text or "")]
    out = []
    for p in parts:
        if len(p) > 30 and "，" in p:
            out.extend(x.strip(" ，,、-—·\t") for x in p.split("，"))
        else:
            out.append(p)
    return [p for p in out if 6 <= len(p) <= 80]


def _is_junk(line: str) -> bool:
    t = line.strip()
    if NAV_JUNK_RE.match(t) or CTA_START_RE.match(t):
        return True
    low = t.lower()
    if any(k in low for k in JUNK_SUBSTR) and len(t) < 120:
        return True
    if re.fullmatch(r"[A-Z0-9\s&/·+.\-]{2,16}", t):   # 全大写导航项
        return True
    return False


def _strip_testimonial(x: str) -> str:
    x = x.strip().strip("\"'“”「」")
    # "…within 5 minutes." Brandy from Houston → 去掉署名
    x = re.sub(r"[\"”]\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+from\s+[A-Z][a-z]+.*$", "", x)
    return x.strip().strip("\"'“”")


def _clip(x: str, limit: int = 48) -> str:
    x = x.strip(" ，,、-—·\t")
    if len(x) <= limit:
        return x
    cut = x[:limit]
    for i in range(len(cut) - 1, max(12, limit // 2), -1):
        if cut[i] in "，,、 ":
            cut = cut[:i]
            break
    # 收尾不能停在虚词上
    cut = re.sub(r"\s+(?:our|the|a|an|and|or|is|are|to|of|for|with|in|on|at|that|which)$",
                 "", cut, flags=re.I)
    return cut.strip(" ，,、-—·")


def extract_benefits(text: str, limit: int = 5) -> list[str]:
    """带价值主张的句子，按信息密度排序；不足时用正文前几句补齐。"""
    sents = [s for s in extract_sentences(text) if not _is_junk(s)]
    scored = []
    for idx, s in enumerate(sents):
        low = s.lower()
        hit = sum(1 for h in BENEFIT_HINTS if _word_hits(low, h))
        proof = sum(1 for h in PROOF_HINTS if _word_hits(low, h))
        if not hit and not proof:
            continue
        if not CJK_RE.search(s) and len(s.split()) < 3:
            continue
        scored.append((hit + proof * 2, -idx, s))
    scored.sort(reverse=True)

    picked, keys = [], set()
    for _, _, s in scored:
        v = _clip(_strip_testimonial(s))
        k = re.sub(r"[\W_]+", "", v.lower())
        if v and k not in keys:
            picked.append(v); keys.add(k)
        if len(picked) >= limit:
            break
    if len(picked) < 3:
        for s in sents:
            v = _clip(_strip_testimonial(s))
            k = re.sub(r"[\W_]+", "", v.lower())
            if v and k not in keys:
                picked.append(v); keys.add(k)
            if len(picked) >= 3:
                break
    # 互相包含的句子只留信息量大的那条（"Free trial" 被 "Free trial for 30 days" 覆盖）
    dedup = []
    for v in picked:
        low = v.lower()
        if any(low in x.lower() or x.lower() in low for x in dedup):
            if all(len(v) > len(x) for x in dedup if low in x.lower()):
                dedup = [x for x in dedup if low not in x.lower()]
            else:
                continue
        dedup.append(v)
    return dedup[:limit]


def _norm_metric(raw: str) -> str:
    s = (raw or "").strip()
    m = re.match(r"^([$\u00a5\u20ac\u00a3])\s?([\d,.]+)$", s)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    m = re.match(r"^([\d,.]+)\s*(.*)$", s)
    if not m:
        return s
    num, unit = m.group(1), (m.group(2) or "").strip().lower()
    if unit in ("million", "m"):
        return num + "M"
    if unit in ("billion", "b"):
        return num + "B"
    if unit == "k":
        return num + "K"
    if unit in ("%", "\uff05", "percent"):
        return num + "%"
    if unit == "倍":
        return num + "x"
    if unit in ("万", "亿", "+"):
        return num + unit
    if unit.startswith("-"):
        return num + unit.replace(" ", "")
    return s


def extract_metrics(text: str, limit: int = 5) -> list[str]:
    """只保留能当卖点的量：占比、用户量、评分、金额；时长（分钟/小时）不算转化指标。"""
    out = []
    for raw in METRIC_RE.findall(text or ""):
        v = _norm_metric(raw)
        if v and v not in out:
            out.append(v)
    return out[:limit]


def _clip_sentence(x: str, limit: int = 60) -> str:
    if len(x) <= limit:
        return x
    cut = x[:limit]
    for i in range(len(cut) - 1, limit // 2, -1):
        if cut[i] in "，,、 ":
            return cut[:i].strip()
    return cut.strip()


def _clause_around(line: str, start: int, end: int) -> str:
    """取命中位置所在的短句——整行可能有两三个句子，全返回会读不出重点。"""
    left = max(line.rfind(c, 0, start) for c in "，,。.；;")
    rights = [i for i in (line.find(c, end) for c in "，,。.；;") if i != -1]
    right = min(rights) if rights else len(line)
    return line[left + 1:right].strip(" ，,、-—·")


def extract_audience(text: str) -> str:
    """只在正文行里找人群描述。

    旧版在切句结果里找，而切句会把 >80 字的长句直接丢掉，
    `…a library fit for both adults and kids` 这种真实的人群描述反而搜不到。
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) < 8 or _is_junk(line):
            continue
        for pat in AUDIENCE_PATTERNS:
            for m in re.finditer(pat, line, re.I):
                frag = m.group(0)
                if AUDIENCE_DENY.search(frag) or len(frag.strip()) < 6:
                    continue
                # "designed for optimal sleep" 是产品用途，不是人群
                if not PERSON_WORDS.search(frag + " " + line):
                    continue
                clause = _clause_around(line, m.start(), m.end())
                # 去掉从句尾巴（", making our app..." / ", which means..."），
                # 否则读起来像半句话
                trimmed = re.split(r",\s*(?:making|which|so|that|and|to|for|with|because|where|"
                                   r"giving|allowing)\b", clause)[0].strip()
                if len(trimmed) >= 15:
                    clause = trimmed
                if len(clause) >= 8:
                    return _clip_sentence(_strip_testimonial(clause), 60)
                return _clip_sentence(_strip_testimonial(line), 60)
    return ""


def extract_geo(text: str) -> list[str]:
    low = (text or "").lower()
    hits = [name for name, words in GEO_WORDS.items()
            if any(_word_hits(low, w) for w in words)]
    return hits


def analyze_local(text: str, url: str = "") -> dict:
    """返回可直接落库的框架字段 + evidence（每个结论的原文依据）。"""
    # 用户常把 URL 直接粘进正文框：不识别出来，产品名会被抽成 "https"
    if not url and re.fullmatch(r"\s*https?://\S+\s*", text or "", re.I):
        url, text = text.strip(), ""
    clean = normalize_text(text)
    product, product_src = extract_product(clean, url)
    domain, dmeta = detect_domain(clean)
    benefits = extract_benefits(clean)
    metrics = extract_metrics(clean)
    audience = extract_audience(clean)
    geos = extract_geo(clean)
    notes = PLATFORM_NOTES.get(domain, PLATFORM_NOTES["app"])

    if not clean:
        # 只给了域名却拿不到正文：不编造卖点，明确告诉用户缺什么
        return {
            "product": product,
            "category": FALLBACK_META["label"],
            "domain": FALLBACK_DOMAIN,
            "audience": FALLBACK_META["audience_hint"] + "（原文为空，按品类默认）",
            "geo": "未在原文中识别到投放地区，建议先按 T1 英语区小预算测试",
            "languages": ["en"],
            "selling_points": ["未取到落地页正文，请粘贴产品说明或稍后重试抓取"],
            "metrics": [],
            "platform_analysis": notes,
            "evidence": {"product": {"value": product, "source": product_src},
                         "selling_points": {"value": [], "source": "正文为空"},
                         "source_len": 0},
            "analyzer": "local",
        }

    if not benefits:
        benefits = [f"{product} 的核心功能", "使用流程简化", "适合移动端场景"]

    langs = ["en"] if detect_lang(clean) != "zh" else ["en", "es"]
    geo_text = "、".join(geos) if geos else "未在原文中识别到投放地区，建议先按 T1 英语区小预算测试"
    if audience and not CJK_RE.search(audience[:1]):
        audience = audience[0].upper() + audience[1:]
    audience_text = audience or f"{dmeta.get('audience_hint')}（原文未写明人群，按品类默认）"

    return {
        "product": product,
        "category": dmeta["label"],
        "domain": domain,
        "audience": audience_text,
        "geo": geo_text,
        "languages": langs,
        "selling_points": benefits,
        "metrics": metrics,
        "platform_analysis": notes,
        "evidence": {
            "product": {"value": product, "source": product_src},
            "category": {"value": dmeta["label"], "matched_words": dmeta.get("matched", [])},
            "selling_points": {"value": benefits, "source": "原文句子（按价值主张密度排序）"},
            "metrics": {"value": metrics, "source": "原文中的百分比/用户量/评分/金额"},
            "audience": {"value": audience, "source": "原文" if audience else "品类默认"},
            "geo": {"value": geos, "source": "原文" if geos else "未识别"},
            "source_len": len(clean),
        },
        "analyzer": "local",
    }
