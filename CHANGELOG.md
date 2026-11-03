# 版本交付记录

按《在线营销素材管理平台-版本开发规划.docx》的顺序交付，每个版本都是可独立验收的垂直切片。

## V1.1 批量提效版

**交付**
- `Job` 模型 + `batch.py`：CSV 解析（有/无表头、多值 `| ; /` 分隔）、异步任务、进度落库、单条失败隔离、取消（保留已完成）。
- 新增接口：`POST /api/batch/parse|upload|jobs`、`GET /api/jobs`、`GET /api/jobs/{id}`、`POST /api/jobs/{id}/cancel`、`GET /api/batch/template`、`GET /api/export/batch?ids=`。
- 前端「③ 批量任务」页：CSV 粘贴/上传、解析预览、默认配置（平台/语言/类型）、进度条轮询、结果表、批量下载、历史任务。
- 素材库多选 + 批量导出 ZIP（每 Campaign 一个目录 + `batch_manifest.json`）。
- `migrations.py` schema 自愈：自动补齐缺失列 + `normalize_data()` 回填，避免旧演示库与模型漂移。

**验收证据**
- 2 行 CSV → 生成 2 个 Campaign（8 / 12 条素材），进度 `success 2/2`。
- 45 行非法数据：字典型 `landing_text` 被跳过（`skipped: 1`）、数字自动转字符串，接口未 500。
- 取消：20 行任务在第 5 条时取消 → `canceled`，已完成 5 条结果保留；25 行任务取消于第 4 条。
- 合并导出：23 个文件，两个 Campaign 目录 + 总 manifest，无重名。
- 过程中修复两个真实缺陷：批量任务跨 `await` 持有 SQLite 写事务导致 `database is locked`（改为先提交再生成 + 开启 WAL/busy_timeout）；取消响应缺字段。

## V1.2 迭代与 A/B 版

**交付**
- `Material.variant`（A/B/C…）与 `selected`（定稿标记）；版本号改为组内 `max(version)+1`，避免删档后撞号。
- 接口：`GET /api/materials/{id}/versions`（版本链）、`GET /api/materials/{id}/compare?against=`（逐字段差异 + 字数差）、`POST /api/materials/{id}/select`（同组唯一定稿）、`GET /api/campaigns/{id}/slots`（按素材位聚合）、`GET /api/export/ab/{id}?selected_only=`。
- A/B 导出结构：每个素材位一个目录，`A_v1` / `B_v2` 并列 + `ab_plan.csv`（含选用/合规/字数/描述语）。
- 前端：素材卡「版本链 / A-B」面板——版本表、A/B 选择、并排对比（变更字段高亮、字数对比）、「设为定稿」；Campaign 头「A/B 分组导出」「定稿导出」。

**验收证据**
- 西语文案 v1 → 重生成 v2：`titles/descriptions/cta` 三字段均变更，字数差 -4。
- 定稿 v2 后：组内仅 v2 `selected=true`；A/B 导出 4 个文件（A、B、plan、manifest），定稿导出 3 个（仅 B）。
- 修复：Mock 文案固定导致对比无差异（改为按调用序轮换措辞）、Mock 未遵守字数红线（现按 brief 截断）、历史行 `selected=NULL` 触发响应校验失败（新增回填）。

## V1.3 真实视觉素材版

**交付**
- `imaging.py`：Pillow 广告图合成——品牌渐变、词级折行（避免英文断词）、自适应字号、CTA 胶囊、AI 底图 cover 裁剪 + 压暗 42% 后叠字。
- 图片按平台尺寸逐张出图（`IMAGE_SIZES_PER_PLATFORM` 默认 4，主尺寸优先），每张是可直接上传的 PNG，文案由同语言 copy 注入。
- `providers.TemplateImage`（默认，无 Key 也能交付）、`OpenAIImage`（`images/generations` → 最近比例 → 裁剪目标尺寸 → 叠字）、`StoryboardVideo`（15s 四镜分镜：痛点/演示/社会证明/CTA，含画面、字幕、口播、交付物）、`ModelVideo`（可配置契约，失败回退分镜）。
- 导出命名加入尺寸，避免同素材位多尺寸重名；视频分镜以 `.json` 交付。

**验收证据**
- Facebook 单语言一 Campaign：4 张 PNG（1080x1080 / 1080x1350 / 1200x628 / 1080x1920），尺寸与文件大小校验一致；复制到 ZIP 7 个文件无重名。
- 人工目检（1080x1080、1080x1920、1200x628、320x50）：标题按词折行、副标题完整、CTA 不溢出；小 banner 单行布局。
- 修复：副标题把字体对象当字号用（TypeError）、折行按字符切断英文、内容块偏上（改为 30% 起始 + 溢出保护）。

## V2.0 平台化协作版

**交付**
- 用户与角色：`users`（PBKDF2-SHA256 12 万轮 + 随机盐）、`auth.py`（HMAC 签名 Token，12h 有效）、中间件统一鉴权（`/api/*` 默认需 Token，下载支持 `?token=`）。
- 角色门禁：`admin` 全权限；`manager` 审阅 + 规格维护；`editor` 生成/重生成/定稿；`viewer` 只读。
- 审阅流：`draft → in_review → approved / rejected`，`review_records` 记录动作/人/前后状态/意见；驳回必填原因；重新提交闭环。
- 规格后台：`PUT /api/platform-specs/{id}`（经理及以上），改动即时影响生成 Prompt 与校验；写入 `audit_logs`。
- 用户管理：增删改（停用为软删除）、禁止降级/停用最后一个管理员、`GET /api/audit-logs`。
- 前端：登录页（演示账号可点选）、角色化导航、素材库审阅操作与记录、规格库在线编辑、设置页用户管理 + 审计日志。

**验收证据**
- 未登录 `/api/campaigns` → 401；错误口令 → 401。
- viewer 生成 → 403；viewer 读素材库 → 200；editor 审批 → 403；manager 审批 → `approved`，审阅记录两条（submit/approve 含操作人）。
- 驳回无原因 → 400；填原因 → `rejected` 且带 `review_note`；再次提交 → `in_review`。
- 规格改 `title_max=10` 后重新生成，最长标题恰为 10 字且校验通过（规格链路生效）。
- 用户创建 → 停用 → 停用后登录 401；降级最后一个 admin → 400；审计日志含 `spec.update / user.create / user.deactivate`。
- 修复：审阅请求的 `action` 误设为必填（422）、规格更新返回 ORM 导致字段缺失（改为显式结构）、App 条件调用 Hook 的顺序隐患。

## V3.0 创意工厂（定位纠偏）

**背景**：V2.0 交付后暴露定位问题——6 个页面里 4 个是管理与配置，生成链路只有 3 次 LLM 调用
+ 1 个 Pillow 模板；83 条框架记录的卖点字段全部相同，图片是无视觉主体的文字海报，视频只有 JSON 分镜。
本版把生成内核重做，管理能力保留但退到二级导航。

**交付**
- `insight.py`：从落地页正文真实抽取产品名、可量化指标（%／万／K／金额）、价值主张句、受众、地区、品类；
  平台打法按品类区分，不再所有产品共用一套文案。中文长句按逗号二次切分，卖点在标点处收尾。
- `creative.py`：6 个创意方向（痛点直击／利益直给／社会证明／悬念好奇／真实体验／限时促动），
  每个方向含洞察、钩子、视觉方案、影响指标、适配平台；四语言（en/es/pt/id）文案模板 + 短句库；
  平台字段结构（FB：primary_text 125 / headline 40×3 / description 30 / CTA 枚举；Google RSA：headline 30×5 / description 90×3；
  Unity 30/50；AppLovin·Moloco·Mintegral 40/90；Adsterra 40/60）；
  标题优先选「本来就放得下」的候选，避免把半句话裁进素材；跨方向文案重合度 ≥75% 打「同质化」标记。
- `render.py`：6 套视觉模板（纯字体／数字主体／评分卡／折扣角标／UGC 手机框／前后对比），
  合成手机界面作为视觉主体；版位重排（banner 单行、横版左右分栏、方版与竖版上下分区）；
  品牌色驱动配色；支持上传产品图；标题按像素自适应且优先少行。
- 视频：四镜关键帧（对比 → 手机演示 → 评分卡 → CTA），信息条单独占位不压画面，首帧封面可单独下载。
- 接口：`POST /api/angles/plan`、`GET /api/frameworks/{id}/angles`、`POST /api/produce`、
  `PATCH /api/frameworks/{id}/brand`、`POST /api/assets/upload`、`GET /api/copy-schema`。
- 前端：`Workspace` 单页三步（输入 → 方向多选 → 素材墙），素材墙按方向分组、多尺寸并排、
  字段级文案与字数条、关键词块、关键帧横排、点击放大；导出改为「平台/方向」目录 + `copy.csv` + `delivery_notes.md`。

**验收证据**
- 输入 FitTrack 落地页文本 → 抽出产品 FitTrack、品类 健康/健身、指标 `200 万`/`40%`、地区 北美/欧洲、受众 25-40 岁上班族；
  卖点按逗号切分为 4 条，无模板化通用句。
- 同一框架生成 6 方向 × Facebook × en：24 张图（每方向 4 版位）+ 6 套文案 + 6 条视频分镜，耗时 4.4s。
- 目检 1080x1080 / 1080x1350 / 1200x628 / 1080x1920：同方向四个版位构图不同（非拉伸），标题完整无截断，
  对比面板与手机主体清晰；4.8s 首轮 11.7s → 视频并行渲染后降到 4.4s。
- 文案字数：FB 主文案 48/125、标题 28/40、描述 22/30，全部在限内；Google RSA 出 5 标题（均 ≤30）+ 2 描述（均 ≤90）。
- 投放包：`Facebook/pain/*.png`、`Google/benefit/keywords.txt`、`copy.csv`（platform/angle/language/field/value/chars）、
  `delivery_notes.md`，9 个文件无重名。

**本次修掉的 bug**
- `fit_headline` 用带 max_lines 的折行结果判断「能否放下」，永远为真 → 标题被静默截成一行（现用 99 行测量）。
- 关键帧信息条压在画面底部挡住 CTA → 改为独立信息带，画面区渲染在剩余高度内。
- 关键帧图片 URL 只取文件名，子目录下的 `kf*.png` 全部 404 → 按 `uploads/` 后相对路径拼接。
- 中文字体写死 `PingFang.ttc`，新版 macOS 已移除 → 中文渲染成方框；改为 STHeiti / Hiragino / Noto 依次回退（旧 `imaging.py` 一并修复）。
- Google `description` 为列表，同质化比对直接 `.lower()` → 500；统一取首条并加类型防御。
- FB description 用 `text[:30]` 硬切产生 `"…upda"` → 改为词边界裁剪 + 独立短句库。
- 品牌色直接压暗做底导致画面发土褐 → 改「近黑中性底 + 少量品牌色」。

## V3.1 真实落地页回归 + 产出量参数（用 calm.com 跑出来的问题）

**背景**：V3.0 的卖点抽取只用自己写的示例文本验证过，换成真实落地页立刻暴露问题。
本版拿 calm.com 的落地页（只给 URL，服务端抓取 15,046 字符）跑完整链路，逐项修。

**实测发现并修掉的 5 个抽取错误**

| 字段 | 修前 | 修后 | 根因 |
|---|---|---|---|
| 产品 | `**标题**` | `Calm` | 没清洗 markdown 与 `标题：` 前缀，取了首行首段 |
| 品类 | 影像/AI 工具 | 健康/健身 | 品类词用 `str.count` 子串匹配，`ai` 命中了 `daily` / `practice` |
| 指标 | `2 m`、`5 m` | `2M`、`5-star`、`500+` | 正则把 `2 million` 吞成 `2 m`、把 `5 minutes` 当时长卖点 |
| 受众 | `**标题**: Calm - The #1 App...` | `We have a library fit for both adults and kids` | 受众正则在标题行命中 `for Meditation and Sleep` |
| 卖点 | `Try Calm for Free`、`Learn More` 混入 | 原文 5 条实质句 | 没有过滤 CTA / 导航 / 订阅条款 |

修法：新增 `normalize_text` 归一化、品类改词边界匹配且按"命中词种数"计分、
指标改"数字+单位"成对解析并归一化、受众要求命中句子含人称词、卖点加 CTA/法务噪声过滤。

**新增能力**
- `POST /api/analyze` 只给 URL 时，服务端抓取正文（15s 超时 + 1 次重试，失败则明确提示"未取到正文"，不再编造卖点）。
- 框架返回 `evidence`：每个结论标注来源（`url+正文` / `标题行` / `首行` / `品类默认`），
  品类附命中的关键词，前端在"从原文里抽到的事实"下方展示一行依据。
- 产出量参数化：`sizes_per_angle`（每方向每平台版位数，1–8）、`video_mode`（off / first / all）；
  新增 `POST /api/estimate` 预估，生成前就显示"预计 N 个：X 图 · Y 文案 · Z 分镜"；
  单次上限 240 个素材（`MAX_MATERIALS_PER_CAMPAIGN` 可调），超限直接 400 并说明原因；
  本次参数写入 `campaigns.options`，素材墙头部回显。
- 工作台新增"每方向版位数""视频"两个下拉，默认 4 版位 + 仅首方向出分镜。

**合规修复（真实素材里能看出来的坑）**
- 评分卡写死 `4.8`：改为只取原文评分（`5-star` → `5 / star reviews`），取不到就只画星级不写数字。
- 促销模板写死倒计时 `Ends in 02:14:33`：改为仅当调用方传入截止时间才显示。
- 促销方向文案带"限时/本周"表述：素材校验里加 warn「促销方向默认带时效表述，投放前请确认活动真实存在」。

**验收证据**
- 只给 `https://www.calm.com/`：抽出产品 Calm、品类 健康/健身（命中 anxiety/breath/meditat/mindful/relax/sleep/stress）、
  指标 `2M` `5-star` `500+` `900+` `74%`、受众 `We have a library fit for both adults and kids`。
- 中文示例 `FitTrack AI 健身 App…`：产品 `FitTrack`（去掉通用后缀 AI/App）、指标 `200万` `40%`、地区 北美、欧洲、
  受众 `面向 25-40 岁上班族，覆盖北美与欧洲`，卖点 4 条均为原文句。
- 产出量核对（6 方向）：2 版位/首方向视频 = 19（12 图 + 6 文 + 1 分镜），实际产出 19；
  4 版位/全视频 = 36，实际 36；每方向图片数均为配置值。
- 超限：6 方向 × 7 平台 × 2 语言 × 6 版位 = 504 → 预估 `over_limit=true`，下单返回
  `400 本次将生成 504 个素材，超过单次上限 240`。
- 2 版位 + 关闭视频：0.7s 出 12 图 + 6 套文案，比 V3.0 的 4 版位 + 全视频（4.4s / 36 个）快一个量级。

**已知边界**
- 本地模板不掌握活动信息，促销方向的时效表述需人工核对（已在校验里提示）。
- 抓取依赖目标站点可访问；被反爬或网关 502 时降级为"请粘贴正文"，不编造。

## V3.2 单页工作台 + 结构化分析报告 + 素材优化

**背景**：V3.1 把"分析"和"生成"放在两个页面，用户得先看报告、再跳页生成，中间结论（卖点、指标、
风险）无法带到生成参数里；且生成完只能整批重生成，没有"就这张图改一下"的入口。本版把链路压成一页五步，
并补上结构性报告与定向优化。

**单页五步（Workspace 整体重写）**

| 步 | 区块 | 关键能力 |
|---|---|---|
| ① | 产品分析 | 只填 URL → 抓整页 → 结构化报告；抓不到正文给"粘贴正文"退路（422 + 提示） |
| ② | 投放设置 | 平台 / 语言 / 每方向版位数 / 视频模式，实时预估产出量与上限校验 |
| ③ | 创意方向 | 报告里抽出的卖点直接当方向，可勾选/改标题，与①②联动 |
| ④ | 素材与优化 | 自然语言优化框 + 版本 tab（v1/v2/v3）+ 只看校验通过 |
| ⑤ | 交付下载 | 全量 ZIP / 仅合格素材 ZIP / 分析报告 Markdown |

顶部 sticky 锚点导航，改配置不用来回滚动。

**新增 `report.py`——七段结构化报告（不是字段平铺）**
- 段 1 产品与定位（品类判定 + 命中词 + 一句话定位）
- 段 2 核心价值主张（每条带类型：效率/省钱/信任/情绪/便利，和强弱评级）
- 段 3 信任与量化背书（指标拆解：`2M`→用户量、`74%`→比例、`5-star`→评分，并标注出现在哪个位置）
- 段 4 目标人群（原文依据句 + 推断）
- 段 5 落地页结构与转化路径（title/description/H1/H2/CTA 数量与首屏判断）
- 段 6 各平台投放读法（同一产品在 Meta / Google / TikTok 的切入差异）
- 段 7 风险与合规 + 信息缺口 + 下一步
- 每条结论附**原文依据**；整篇给**可信度 20–95 分 + 理由列表**（抓取字数、指标数、卖点数、正文是否缺失都会影响分数）。
- 品类合规红线按 domain 区分：健康（疗效宣称）、金融（收益承诺）、游戏（概率误导）、电商（绝对化用语）、教育（保过承诺）、App（诱导安装）。

**新增 `optimize.py`——自然语言指令 → 确定性规则**
- 规则集 13 条：`shorter` / `longer` / `no_numbers` / `numbers` / `casual` / `formal` / `question` / `urgent` / `no_brand` / `template` / `color` / `cta` / `emphasize`。
- 中文指令解析（"标题更短，去掉数字" → `shorter + no_numbers`），返回识别到的规则与未识别片段。
- 每条改动记录 `before → after`，前端逐条展示；不适用的规则给 warning 而不是静默跳过。
- 改文案 → 生成新版本 copy；改版式/配色 → 同组多尺寸**共用一个版本号**重渲染（不会出现 1080x1080 是 v2、1200x628 是 v3）。
- 语义完整保护：只允许在 `— - : ; ,` 或介词短语处截断，截不出完整句就保留原句并提示，绝不产出 `Over 2 million 5-star` 这种残句。
- 候选池消费：三条标题不能优化成同一句（`used` / `avoid` 集合）。

**新增接口**

| 接口 | 说明 |
|---|---|
| `POST /api/report` | URL 或正文 → 抓取 + 结构化报告 + 顺带规划方向 |
| `GET /api/reports/{fid}` | 取历史报告 |
| `GET /api/reports/{fid}/export.md` | 报告导出 Markdown |
| `POST /api/campaigns/{cid}/optimize` | 自然语言优化（scope: copy / image / all） |
| `GET /api/export/campaign/{cid}?only_valid=&all_versions=` | 交付包，默认每组只打最新版本 |

**渲染与交付修正**
- 副标题两行时若末行只剩一个短词，按词数均分重排，消除 `it.` 孤字行。
- `stat` 模板在没有数字指标时回退 `bigtype`，避免出现空壳手机框。
- 图面去重：`2M` 与 `Over 2 million` 视为同一数字，副标题不再重复标题里的量级。
- 交付统计改为"每组最新版本"口径，另列"含历史版本"总数；ZIP 内 `manifest.json` 增加
  `pack: {latest_only, only_valid, materials, skipped_invalid}`，`delivery_notes.md` 用中文方向名 + 版本号。

**验收证据**
- calm.com 端到端（1.9s）：产品 `Calm`、品类 健康/健身、可信度 **95/100 高**、
  指标 `2M` `5-star` `500+` `900+` `74%`、5 条带类型卖点、7 段报告、3 条合规风险（健康宣称 / 效果承诺 / 免责声明）。
- 单页全流程（CDP 截图，`page errors: []`）：分析 → 生成 4 图 + 2 文案 →
  优化"标题更短，去掉数字"（+6，v2）→ 优化"换成纯文字版式，主色改蓝"（+6，v3）→
  交付（最新 4 图 / 4 通过 / 2 文案 / 3 版本 / 18 含历史）。
- 下载核对：单张 `200 / 74,984B`；全量 ZIP 7 文件（每组最新 v3，`pack.latest_only=true`）；
  `only_valid=true` 结果一致；报告 Markdown `200 / 4,574B`。
- 修掉的问题：`analyze_landing_page` 传 `page` 时没回取正文导致报告卖点变成"未取到落地页正文"、
  `LandingPage` 存了 15,000 字全文（改为剔 `text` 再存）、"更口语"把 Meta CTA 改成非枚举值 `Get it`
  （改为 casual/formal 不处理 cta）、"突出 5-star 评分"把中文塞进英文标题（改为只取现有英文原句）。

**收尾回归又抓出的 8 个（都是"功能看着能用，实际在骗人"那类）**

| 现象 | 根因 | 修法 |
|---|---|---|
| 报告写「识别到转化按钮 Try Calm for Free」，背书却写「价格信息 未识别」，信息缺口还报「未见价格」 | `PRICE_RE` 只认 `$数字` / `free trial`，认不出纯 `for free` | 新增 `FREE_RE`（`for free` / `free trial` / `no cost` / `免费试用` / `$0`），三处共用；**故意不匹配 `free from anxiety`** 这类「摆脱焦虑」 |
| 点了「标题更短」什么都没变，却生成了 v2 全套素材 | `created` 无条件 +1，不比对是否真有改动 | 文案没变且版式配色没变就 `continue`，只出 note；交付时版本号不再被复印件顶掉 |
| 零改动时接口返回 422，前端弹红字像出错 | 把"没改动"当成了"没听懂" | 拆开：一条规则都没命中才 422；命中但无改动 → 200 + `created:0` + `noop:true` |
| `The shorter way to the same result` 被缩成 `The shorter way`（悬空短语） | `to` 在可断介词表里，但 `way / path / route` 需要 `to` 补语 | 从断点表移除 `to`；补 `_trim_filler` 优先删 `just / really / very` 这类填充词（语义等价且真能减字） |
| 缩短标题时把描述整句搬成标题，读起来像复制 | 候选池取了 `headline + desc` 全部句子 | 池子按字段类型隔离，标题只从标题里换 |
| 上一轮换的 `bigtype` 版式和蓝色，下一轮只改文案就被打回 v1 的 `stat` + 品牌橙 | `base_tpl.setdefault()` 取"第一张遇到的图"，版本无序 | 按版本号取最新：`tpl_ver / last_color / last_metric` 三个继承表，量级被 `no_numbers` 清空后也照此沿用 |
| 图片明明变蓝了，`spec_json.brand_color` 却是 `None`，再优化一次颜色就丢了 | 渲染用内存 spec，落库只写了 `template` | `spec_json` 补齐 `template / brand_color / metric / rating_value` 四项实际渲染值 |
| 指令里写 `#1E8E5A` 却被改写成 `#2F9E44`（中文"绿"的映射色） | 颜色规则只认 8 个中文色名 | 先解析 `#RRGGBB`，没有才退到色名映射；亮度 >200 时提示"白字对比度可能不足" |

回归验证（campaign 96 连续四轮）：v1 `stat/rating` → v2 `bigtype`+蓝 → v3 绿色 `#2F9E44` 且版式继承
→ v4 只重渲染 2 张确实受影响的图、版式与绿色都保留、文案 0 改动的那组直接进 `noop` 不出版本。

**已知边界**
- 优化是**规则模式**，不做大模型重写：表达多样性受现有文案池限制，池子里没有合适句子时会跳过并提示。
  实测 Calm 的三条标题（29/40、29/40、34/40）本来就在平台字数上限内、又没有安全断点，
  「标题更短」会 0 改动并说明原因——这是设计取舍，不产出投不出去的残句。
- 报告的可信度分数是启发式（依据可量化项计数），不代表投放效果预测。

## V4.0 左侧菜单版（导航改版）

**交付**
- 导航从顶部横排标签改为**统一左侧菜单栏**，两级结构：`素材管理`（创作工作台 / 批量生成 / 素材库 / 规格库）
  与 `设置`（一级，仅管理员）。`App.tsx` 改由菜单配置驱动，菜单项带图标、说明与角色过滤。
- 侧栏展开 236px / 收起 66px：收起后品牌区只留 logo（点击即展开），分组标题变成一条分隔短横线，
  图标项保留 `title` 提示；状态写入 `localStorage.admb_sidebar`，刷新后保持。
- 视口 < 1180px 自动收起；变宽时只有用户**没手动设过**状态才自动展开，不覆盖手动选择。
- 主区新增层级页头：一级名小标 + 当前页标题 + 一句说明；`document.title` 同步为「页面名 · 广告管理系统」。
- 引入 hash 路由（`#/workspace`、`#/batch`、`#/library`、`#/specs`、`#/settings`）：刷新、书签、前进后退
  都能回到同一页；首次进入无 hash 时自动补齐。
- 账号信息与退出从顶栏移到侧栏底部；`styles.css` 新增布局段（`.shell/.sidebar/.sb-*/page-head`），
  移除已无引用的 `.topbar`/`.nav` 样式。
- 顺手补 `favicon`（内联 SVG，与侧栏 logo 同色），消除控制台 404。

**验收证据**
- editor 账号：侧栏 4 项 + 无「设置」；admin 账号：多出「设置」，进入后页头为「系统 / 设置」。
- 点击收起：`offsetWidth 236 → 66`、文字标签数 0、`title` 提示 4 个齐全；点 logo 复原到 236。
- 切页后 `location.hash` 依次为 `#/library`、`#/specs`、`#/settings`；刷新后仍停在 `#/workspace` 对应页面。
- 视口 1024 → 侧栏 66、主区 958；拉宽到 1440 → 自动展开 236；收窄到 760 → 自动收起 66、主区 694。
- 素材库、批量生成、规格库、设置页在新布局下均无横向溢出；`page errors` 与 `Log.entryAdded` 均为 0。

**已知边界**
- 收起态只有图标 + 原生 `title` 提示，没有自绘浮层 tooltip（侧栏容器为滚动容器，浮层会被裁切）。
- 窄屏（< 900px）仍保留 66px 图标条，未做抽屉式侧栏；内部投放工具以桌面端为主。

## V4.1 网站核心内容分析（LLM 驱动的 9 模块产品能力）

**背景**：V4.0 之前，结构化报告中只有「部分模块」走大模型，其余靠本地规则硬写，
同一份事实在报告 / 方向 / 文案之间口径不一致；换模型或改提示词也无法整体升级分析质量。
本版把「网页内容抓取与分析」固化成一次 LLM 调用产出完整结构的产品能力。

**交付**
- `services.py` 新增 `SYS_SITE_ANALYSIS` 提示词 + `build_site_prompt` / `analyze_site`，
  重写 `analyze_landing_page`：整页抓取 → 本地已抽取事实 → 一次 LLM 调用产出 9 模块 JSON，
  落库 `Framework.site_analysis`。
- 9 模块：定位 / 核心价值主张 / 信任与量化背书 / 目标人群 / 落地页结构与转化路径 /
  各平台投放读法 / 风险与合规 / 信息缺口 / 下一步。
- 提示词硬约束：结论必须来自给定事实与正文、缺什么写进 `gaps.missing` 不编造；
  `category_key` 限定固定集合；`channel` 至少覆盖 8 个平台；结尾强制 `MARKER:SITE_ANALYSIS_JSON`。
- `report.py` 全面消费 `site_analysis`（value / proof / audience / page / channel / risk / gaps / next_steps）：
  `value_props` 带类型与强弱评级、`metric_rows` 拆解指标、`platform_rows` 带钩子 / 主推卖点 / 合规提示。
- `providers.py` Mock 按 `MARKER` 分支返回同结构 JSON；新增 `_guess_product` 从正文首句派生产品名，
  修掉默认无 Key 部署时显示 `Unknown Product` 的问题；`one_liner` 取正文首句而非写死套话。
- 无真实 Key 自动回退本地抽取，主流程不中断；`DATABASE_URL` 可隔离测试库。

**验收证据**
- 端到端 health / login / analyze / report 均 200；`analyze` 返回 `site_analysis` 9 模块齐全（`_source: mock`）。
- `report` 正确消费：`proof.metrics` 2 条、7 平台打法含 hook / selling_point / compliance_note。
- 后端 `py_compile` 全模块通过，前端 `npm run build` 通过。

## V4.2 创意方向框架 + 推荐排序增强

**交付**
- 创意方向从 6 个扩到 **8 个**：新增 `scenario`（场景代入 / 共情）与 `comparison`（对比测评）；
  每个方向带 `hook_type`（钩子类型）与 3 段 `storyboard`（时间轴 / 画面 / 口播字幕）。
- `creative.py` 重写 `build_copy_kit`：从 `fw.site_analysis` 自动注入量化指标、卖点、痛点，
  并做语言一致性校验（中文痛点不注入英文文案），storyboard 经占位符替换后产出可直接拍的分镜。
- 全链路贯通：`models.py` / `schemas.py` 增 `Angle.hook_type` / `Angle.storyboard`；
  `services.py` 落库填充后的 storyboard；`report.py` 输出；前端 `api.ts` 类型、
  `Workspace.tsx` 分镜渲染、`styles.css` 样式。
- **推荐排序增强**：`report.py` 新增 `_angle_signals` / `_rank_angles`。基础规则（有指标 / 未见价格）
  叠加 `site_analysis` 的受众痛点、人群画像、强卖点、差异化、媒体背书、合规风险、品类信号加权打分；
  每个方向输出 `score` 与 `reasons`（命中信号中文说明），Top2 打「推荐」标，解决 scenario / comparison
  等新方向在旧规则下永远沉底的问题。报告 Markdown、方向卡、报告详情三处均展示推荐依据，可逐条回溯。

**验收证据**
- `/api/angles/plan` 返回 8 方向均含 `hook_type` + `storyboard`；`/api/report` 的 `creative.angles`
  同步含且已注入 Calm / 100M、无占位符残留。
- 排序可解释：命中「页面给出明确痛点」「识别到目标人群」时 `scenario` 分数上浮并进入推荐；
  金融 / 高合规风险时 `promo` 被降权。
- 前端 `npm run build` 通过。

**已知边界**
- 推荐分是启发式加权（依据 `site_analysis` 信号计数），不代表投放效果预测；权重表集中在
  `report._ANGLE_WEIGHTS`，可按品类数据反馈调整。

## V4.3 默认大模型接入（千问大模型 / qwen-plus）

**交付**
- `main.py` 新增轻量 `.env` 加载与 `seed_default_model()`：启动时为 `analysis` / `copy` 两个文本用途
  自动播种默认模型并 `is_active=True`，设置页「AI 模型配置」可见、可编辑、可停用、可新增其它模型调试。
- 默认项：名称「千问大模型」、`model=qwen-plus`、
  `base_url=https://dashscope-intl.aliyuncs.com/compatible-mode/v1`。密钥放在 `backend/.env`
  （已被 `.gitignore` 忽略，不进仓库）或部署环境变量 `DEFAULT_LLM_API_KEY`；为空则跳过播种、回退本地 Mock。
  可用 `DEFAULT_LLM_PROVIDER` / `DEFAULT_LLM_BASE_URL` / `DEFAULT_LLM_MODEL` 覆盖。
- **地址修正**：用户给的 `/api/v1` 是 DashScope 原生协议路径，本系统走 OpenAI 兼容协议（拼接 `/chat/completions`）。
  实测 `/api/v1/chat/completions` 返回 404、`/compatible-mode/v1/chat/completions` 返回 200，故默认改用后者。
- **输出上限**：9 模块 JSON 较长，`max_tokens` 由 1500 提到 4096，并在 `OpenAICompatibleLLM` 加 3000 下限保护；
  修掉「模型成功返回但被截断、解析失败后静默回退本地」（截断时 5829 字符停在半句，调整后 7822 字符完整闭合）。
- **错误归因修复**：`FallbackLLM` 增加 `used_fallback` 标记；`analyze_site` 只有真实模型确实成功才标
  `_source=llm`，`analyzer` 也改按实际来源标注。此前「配了模型就标 llm」，即便调用 404 回退 Mock 也谎报。
- 设置页表头 `Provider` 改为「模型名称」，显示「千问大模型」；`SYS_ANGLE` 提示词由 6 方向改为覆盖 8 个 key
  （含 scenario / comparison），避免开启真实模型后新增方向拿不到模型润色。

**验收证据**
- 启动日志：`[seed] 默认大模型已启用：千问大模型 / qwen-plus @ https://dashscope-intl.aliyuncs.com/compatible-mode/v1（analysis, copy）`。
- `GET /api/settings/models` 返回 analysis / copy 两条且 `is_active=true`；
  `POST /api/settings/models/test` → `{"ok":true,"latency_ms":1291,"reply":"OK"}`。
- `POST /api/analyze` → `analyzer=llm+local`、`site_analysis._source=llm`、9 模块齐全、channel 覆盖 8 平台。
- `POST /api/report` → 8 方向均带 `score`，推荐 Top2 由分析信号驱动（真实模型下为 pain + comparison）。
- 回退场景（环境变量覆盖为 `/api/v1`）：`analyzer=local`、`_source=mock`，如实标注、主流程仍 200 不中断。
- `py_compile` 全模块通过；`npm run build` 通过（42 modules）。

**已知边界**
- 密钥以明文存于 `backend/.env` 与 SQLite（均被 gitignore），本机可用；部署到新环境需注入环境变量，代码内不含密钥。
  设置页 `GET /api/settings/models` 会明文返回 `api_key` 供编辑，属既有设计。
- 默认只覆盖 `analysis` / `copy` 文本用途；`image` / `video` 不预置，可在设置页自行接入其它模型调试。

## V4.5 完整视频生成（投放设置 → 视频展示 → 下载）

**交付**
- **投放设置新增「生成完整视频（MP4 成片）」开关**：按媒介广告位类型（规格库 `video_spec`）判定，
  仅当视频模式非「不出」且所选媒介中存在支持视频广告位者时显示；开关下方提示支持视频的媒介清单。
- **视频素材展示模块**：视频卡片内嵌播放器（可播放完整视频、首帧封面为 poster）、
  「下载完整视频 MP4」「下载封面图」按钮、AI 分镜脚本表（时间/镜头/画面/字幕/旁白）、关键帧逐镜下载。
- **完整视频生成链路**（`services._make_video` 重构）：
  1. 新增 `SYS_VIDEO` 提示词（注册进「提示词管理」，key=`video`，名称「视频分镜脚本」），
     由大模型按创意方向与产品事实产出 15s 四镜脚本（钩子/演示/证明/CTA，含画面/字幕/旁白），
     失败回退内置分镜，绝不阻断。
  2. 关键帧按分镜逐镜渲染（版式轮换），再经 **imageio-ffmpeg 自带静态 ffmpeg** 合成
     H.264/yuv420p 无声 MP4（`+faststart`，各平台播放器兼容），每镜时长取自分镜时间码。
  3. 素材 `file_path` 指向 MP4，`/api/materials/{id}/download` 直接下载成片；
     合成失败时降级为关键帧 + 分镜交付并在内容中标注原因。
- `requirements.txt` 新增 `imageio-ffmpeg`；`full_video` 存入 campaign.options，视频重生成沿用该配置。

**验收证据**
- 播种日志 `系统提示词已初始化：site_analysis, angle, copy, video`；提示词管理页 4 条，video 缺 MARKER 编辑被 400 拦截。
- 端到端（Calm / TikTok / pain / full_video=true）：`provider=llm_storyboard`（真实模型分镜）、
  4 镜 + 4 关键帧、MP4 233KB（`ftyp` 头校验通过）、下载接口 200 `video/mp4`、`/files/` 静态路由 200。

**已知边界**
- 完整视频为关键帧逐镜合成的无声成片（信息流静音自动播放场景可直投）；如需真人实拍/口播，
  分镜与旁白可直接交剪辑使用。接入 `video` 用途的文生视频模型后，`ModelVideo` 仍可替换为真视频。
- 视频提示词编辑同样受「保留 MARKER」约束，编辑后对后续生成即时生效。

## V4.4 设置菜单拆分 + 提示词管理

**交付**
- 左侧菜单「设置」拆分为独立的「系统设置」分组，含 4 个子页面：
  - **大模型配置**：原 AI 模型 API 配置独立成页（按用途配置、热切换、连通性测试）。
  - **账号**：账号与角色管理独立成页，创建/编辑改为**弹窗**（显示名、角色、密码重置），支持停用/启用。
  - **日志**：审计日志独立成页，支持条数选择（50/100/300/1000）、关键词过滤、刷新。
  - **提示词管理**（新增能力）：统一管理各功能模块的大模型提示词。
- 后端提示词管理：
  - 新增 `PromptConfig` 表（key/name/module/description/content/is_active/updated_at），启动播种 3 条系统提示词。
  - `services.get_prompt(db, key)`：调用时优先读取 DB 中启用的提示词，未配置/停用/读取失败回退内置默认——**编辑保存即生效**，无需重启。
  - 新接口：`GET /api/settings/prompts`（按注册表顺序，未落库以默认兜底展示）、`PUT /api/settings/prompts/{key}`（编辑，写入审计 `prompt.update`）、`POST /api/settings/prompts/{key}/reset`（恢复默认，写入审计 `prompt.reset`）。
  - 编辑防护：内容为空拒绝；**删除 MARKER 标记拒绝保存**（Mock 兜底路由与日志定位依赖它）。
  - 三处模型调用点（`analyze_site` / `plan_angles` / `_angle_copy`）全部改为 `get_prompt` 动态读取。
- 前端提示词管理页：每条提示词展示**所属功能模块**、更新时间、用途说明、规范化内容预览（可展开全文），编辑在**宽弹窗**中完成（等宽字体编辑器），支持停用与恢复默认。
- 移除旧的 `Settings.tsx` / `AdminUsers.tsx`（能力已拆入 4 个页面）。

**验收证据**
- 启动日志：`[seed] 系统提示词已初始化：site_analysis, angle, copy`。
- `GET /api/settings/prompts` → 3 条，含 key/name/module/content（1680/337/144 字符）。
- 编辑 site_analysis 注入「V99」标记 → `get_prompt` 运行时读回含标记；`/api/analyze` 主流程仍 200；reset 后标记消失。
- 删除 MARKER 的内容 → `400 提示词需保留结尾 MARKER 标记…`。
- 账号创建/编辑（含密码重置与角色变更）→ 200；审计日志记录 `user.create / user.update / prompt.update / prompt.reset`。
- `py_compile` 全模块通过；`npm run build` 通过（44 modules）。

**已知边界**
- 提示词为全局生效（不分用户/工作区）；编辑质量由使用者把关，可随时「恢复默认」回退。
- MARKER 校验只拦截「完全不含 MARKER 字样」的内容，若改动标记名称仍可能导致 Mock 兜底解析失败（回退本地构造，不报错）。

## V4.6 素材墙上下布局 + 创意方向差异化视觉

**交付**
- **素材墙改为上下分区**（`.wg-body` 从 `1fr + 340px` 双栏改为纵向堆叠）：
  「图片区 → 视频区 → 文案与关键词区」三段独立卡片，各带标签、标题与虚线分隔；
  图片区浅灰底、视频区冷色底 + 深色边框、文案区白底，界限清晰；视频播放器最大宽度 360→420、
  高度 560，不再被 340px 侧栏挤压，分镜表与关键帧也获得整行宽度。
- **创意方向差异化视觉（新能力）**：
  - 新增提示词 `image`「素材视觉设计指导」（注册进提示词管理，第 5 条）：LLM 按创意方向输出
    `styles`（背景风格 2-3 个，枚举 9 种）/`layout`（4 种）/`font_scale`/`tone`（设计意图）。
  - `render.py` 新增 9 种背景风格：`gradient / radial / split / wave / halftone / stripes /
    spotlight / light_panel / vignette`；4 种文字版式：`default / side_left / bottom_stack / centered`
    （centered 整块水平居中；竖版自动回退 default，避免窄幅侧栏不可读）。
  - **按方向内置预设** `ANGLE_DESIGN`：pain→暗场聚光、benefit→波浪、proof→浅色面板+居中、
    curiosity→点阵+侧栏、ugc→斜纹、promo→对撞分割+大字号、scenario→暗角+上下分区、
    comparison→分割+侧栏；LLM 字段非法/缺失时自动合并预设，**无模型也保证方向间视觉不同**。
  - 图片用 `styles[0]`；视频关键帧按分镜序号轮换 `styles`（`_shot`），四帧不再像同一张图复制。
  - 设计规范落库可回溯：图片写入 `spec_json.design`，视频写入 `content.design`；
    素材墙图片区展示「视觉：<tone> · <style>」标签。
- **顺带修复两个真实缺陷**：
  1. 浅底风格（light_panel / rating）仍用白字 → 切换浅色文字方案（白底白字不可读）。
  2. 标题+副标+CTA 总高超文本框时 CTA 被画到画布外 → `draw_text_block` 改为「测量→整体缩字号→绘制」，
     长文案压力场景验证不再裁切。

**验收证据**
- 全组合渲染回归：9 风格 × 4 版式 × 6 模板 × 4 尺寸 = **864 张 0 失败**。
- 端到端（Calm / TikTok / pain+proof+promo+scenario，真实千问）：4 张图片 `design` 各不相同
  （spotlight+centered / light_panel+centered / spotlight+split / vignette+light_panel），
  文件哈希两两不同；`[design] llm failed` 计数 0。
- 视频链路回归：pain / benefit 各 1 条视频，4 关键帧哈希全不同，MP4 250KB，下载 200 `video/mp4`。
- 提示词播种日志 `site_analysis, angle, copy, video, image`；`py_compile` 通过、`npm run build` 44 modules。

**已知边界**
- 视觉差异化由「背景风格 + 版式 + 字号节奏」实现，字体族仍用系统字体（未内置多字体族）；
  如需字体级差异需引入字体包并在 `_font()` 增加选择逻辑。
- 背景为程序化绘制（渐变/几何/点阵/光效），非 AI 生成位图；接入 `image` 用途的图像生成模型后
  可再叠加真实背景图。

## 全局技术改进

- SQLite 开启 WAL + `busy_timeout=30000`，读写不互斥。
- 写事务不再跨模型调用（先提交再生成），并发取消/查询不被锁死。
- `migrations.ensure_schema` + `normalize_data`：模型演进不再需要删库。
- 前端 `api.ts` 统一带 Token、401 自动清登录态并跳登录页。

## V4.7 成片级关键帧（视频素材去标注）

**问题**
视频关键帧把内部标注烧进了像素：底部信息条写着镜号、时间码、本镜说明和进度条。
这种帧合成为 MP4 后，交付投放前必须人工二次裁切，等于「生成的视频不能直接用」。

**交付**
- `render_keyframe` 重写为**只输出广告画面**：满画幅渲染，删除信息条、镜号、时间码、
  进度条与 `caption` 说明文字；旧调用塞进来的 `caption` 一律丢弃，杜绝说明再次进画面。
- 满画幅安全区：成片模式（`data.video_frame`）下文字框底边上收到画面 88% 处，
  竖版投放时避开平台 UI（行动按钮 / 字幕 / 进度）遮挡。
- 逐镜文案推进 `_shot_payload`：钩子帧只留主标题（大字抓停）→ 演示帧补副标 →
  证明帧给证据（副标或指标）→ 收口帧换成 CTA 端卡。每帧只出现该镜该说的广告文案。
- 逐镜差异不再依赖角标：背景风格按 `design._shot` 轮换、模板轮换、文案推进三者叠加。
- 分镜说明改由素材墙在**图片右侧逐帧标注**：镜号 / 镜头名 / 时间码与时长 / 画面说明 /
  建议字幕 / 旁白，附「查看原图」「下载该帧」；视频区顶部写明「说明不写入图片，也不进成片」。
- 视频提示词（`video`）补硬性字段分工：`visual` 只写拍摄说明，`text` 必须是可直接上屏的
  广告字幕、禁止写镜头解释，`shot` 用 3-8 字镜头名；同步写回「提示词管理」。
  新增 `sync_prompt_defaults`：升级时元信息跟随版本，正文只在库里仍是旧默认快照时刷新，
  用户编辑过的内容保留（启动日志打印被升级的 key）。
- 顺带修复两处影响投放的缺陷：
  1. 成片时长多一镜（concat demuxer 的 duration 必须在末尾重复最后一帧，那一帧再占一镜时长，
     15s 脚本输出 18s）→ 改为「每镜单独按秒编码 + concat 无损拼接」，实测 15.00s。
  2. 副标超两行时被硬砍成 "…with guided tools for adults and" 半句话 →
     `_clip_line` 收口到整词并补省略号，同时剔除结尾悬空连词。

**验收证据**
- 端到端（Calm / TikTok / pain，真实千问分镜）：`frame_mode=clean`、`provider=llm_storyboard`；
  4 帧 1080×1080 底部 12.5% 区域均非信息条（颜色数 14-227，无 (9,11,16) 整块深底），
  画面内只有品牌标记 / 标题 / 产品界面 / CTA。
- 成片校验：`Duration 00:00:15.00`、H.264 / yuv420p / 1080×1080 / 30fps / 184KB；
  从 9.5s 抽帧确认画面只有广告内容（评分卡 + 标题 + 副标），无任何标注。
- 提示词接口 `GET /api/settings/prompts` 返回新版 video 正文（含「3-8 个字的镜头名」约束）；
  迁移单测：旧默认内容 → 升级为新版，用户自定义内容保持不变。
- 渲染回归：8 方向 × 9 风格 × 4 版式 × 5 模板 = **1440 次渲染 0 失败**；`py_compile` 通过、
  `npm run build` 44 modules。
- 布局截图核验：图片左、说明右，标题行与时间码同行，长镜头名两行截断不挤压时间码。

**已知边界**
- 成片仍为无声 MP4（分镜旁白供后期配音用），不生成 TTS 音轨。
- 建议字幕（`text`）只作为剪辑参考展示在图片旁，不烧进画面；如需上屏需在剪辑阶段叠加。

## V4.8 素材库批量删除历史素材

**需求**：在「素材库」增加批量删除操作，可一次性清理历史素材（方案 + 其下素材 + 磁盘文件）。

**交付**
- 后端新增 `DELETE /api/campaigns/batch`，请求体 `{"ids": [int...]}`：
  - 角色门禁 `admin / manager / editor`（viewer 无权限，返回 403）。
  - 先收集每个方案下所有素材的磁盘文件（图片 `file_path`、视频关键帧 `content.keyframes[].file`、
    成片 `content.video_file`、封面 `content.cover`），逐个 `os.remove` 文件、`shutil.rmtree` 关键帧目录。
  - 清理关联审阅记录（`review_records.campaign_id` 无 ORM 级联，手动删避免孤儿行）。
  - 再 `db.delete(campaign)`，由 `Campaign.materials` 的 ORM 级联（`all, delete-orphan`）删除全部素材。
  - 返回 `{ok, deleted_campaigns, deleted_materials, deleted_files}`。
  - 边界：空 id 列表 → 400；全部 id 不存在 → 404；单条文件缺失不影响整体（逐条 try/except）。
- 前端 `api.ts` 增加 `deleteCampaigns(ids)`（`DELETE` + JSON body）。
- 素材库选择栏新增「批量删除所选」按钮（仅 `isEditor` 可见，与「批量导出所选 ZIP」并列）：
  - 点击弹出二次确认，文案含「将删除 N 个方案、约 M 条素材及磁盘文件，且不可恢复」；
  - 成功后 `alert` 回显删除数量并刷新列表、清空选择。

**验收证据**
- 隔离库端到端：植入 1 方案 / 2 素材（图片 PNG + 视频关键帧目录 + MP4），调用后
  `deleted_campaigns=1, deleted_materials=2, deleted_files=4`，DB 中 campaign/material/review 行归零，
  磁盘 PNG、MP4、关键帧目录全部移除。
- 边界单测：空 ids → 400；不存在 ids → 404。
- `py_compile` 通过，`npm run build` 44 modules。

**已知边界**
- 删除为物理删除、不可恢复，仅前端二次确认 + 角色门禁兜底，无回收站；如需要「软删除 / 回收站」可后续迭代。
- 按方案维度批量删除（与「批量导出」同粒度），删除后该方案下所有素材一并清除，无法只删部分素材。

## V4.9 登录改邮箱校验 + 移除登录页默认账号

**需求**：登录界面去掉默认信息与各角色账号展示，必须由用户自主输入；账号模块创建需邮箱+密码，登录按邮箱+密码校验。

**交付**
- 登录页 `Login.tsx`：
  - 删除 `DEMO` 角色账号表与「演示账号（点击填入）」展示；删除默认 `admin / Admin@123` 预填值。
  - 表单改为空值起步，字段由「用户名」改为「邮箱」，提交前校验非空并提示「请输入邮箱和密码」。
- 用户模型 `models.User` 新增 `email`（nullable + 唯一索引，由 `ensure_schema` 自动 ALTER 补齐旧库）。
- 登录 `POST /api/auth/login`：`LoginRequest` 改 `email`；按 `email OR username` 查找（邮箱为主，用户名兜底，避免历史账号被锁）。
- 创建账号 `POST /api/users`：`UserCreate` 增加必填 `email`，校验格式（含 @ 与域名点号）、邮箱唯一、派生并去重 `username`；`user_dict` / `UserOut` 带回 `email`。
- 启动 `backfill_user_emails()`：为历史无邮箱账号补填 `<username>@example.com`，使其可用邮箱登录（幂等，每次启动仅补 NULL 行）。
- 账号页 `Accounts.tsx`：新建表单加「邮箱（登录账号，必填）」、编辑态只读展示邮箱；列表「用户名」列改为「邮箱」；`modalValid` 要求邮箱非空 + 密码≥6。

**验收证据**
- 隔离库 E2E：启动日志「已为 5 个历史账号补填邮箱」；`admin@example.com` 登录 200 并获 token；`admin` 用户名兜底登录 200；错密码 401。
- 创建 `newuser@company.com` 成功（派生 username=newuser）；重复邮箱/非法邮箱/短密码均 400；新用户邮箱登录 200。
- `py_compile` 通过，`npm run build` 44 modules。

**已知边界**
- 历史账号邮箱为 `<username>@example.com` 占位（非真实邮箱），如需真实邮箱由管理员在账号页「编辑」暂不提供改邮箱入口（创建时设定）；如需编辑邮箱可后续在 `UserUpdate` 增加。
- 登录同时接受用户名兜底，属兼容性设计；如要「严格仅邮箱」可移除 `OR username` 分支。
