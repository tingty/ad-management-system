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

## V4.9.1 管理员账号重置（邮箱登录）

- 将管理员账号登录邮箱设为 `leson@recomob.com`，密码经 PBKDF2 哈希存储（明文不落库、不写入文档）。
- 同步更新 `DEFAULT_USERS` 种子（仅作用于全新空库），其余默认账号邮箱由启动 `backfill_user_emails` 补填。
- 验证：以该邮箱 + 新密码登录 `POST /api/auth/login` 返回 200 并签发 token；错误密码 401；用户名 `leson` 兜底登录 200。

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

## V4.9.2 默认管理员启动自愈（保证线上可登录）

**问题**：线上部署环境（`info.rmdsp.com`）使用独立数据库，`seed_users()` 仅在库为空时执行一次，导致历史库里的 admin 仍是早期 `admin/Admin@123` 或邮箱被兜底为 `leson@example.com`，用统一账号 `leson@recomob.com / Tingty@123.com` 登录失败。

**交付**
- 新增 `ensure_default_admin()`：启动时**幂等**保证默认管理员（`leson@recomob.com` / `Tingty@123.com` / role=admin）存在且口令正确。
  - 命中「仍处于默认/未初始化状态」才重置密码：密码为空、邮箱为 `<user>@example.com` 兜底值、或密码等于任一历史默认口令（`Admin@123` 等）。
  - 若管理员已改为自定义密码，则**保留不动**，不被覆盖。
  - 支持环境变量覆盖：`DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_PASSWORD`。
- 在 `on_startup` 中于 `backfill_user_emails()` 之后调用。
- 同步更新 `DEPLOY.md` 默认账号表（旧文档写的 `admin/Admin@123` 已失效）。

**验收证据**
- 单元测试 4 场景：旧 `admin/Admin@123`（邮箱兜底 `admin@example.com`）、旧 `leson`+兜底邮箱、已正确（幂等）、已改自定义密码（保留不重置）——前三类登录 `leson@recomob.com/Tingty@123.com` 均 200，第四类按设计保留原密码。
- 真实 HTTP E2E：以「脏库」（旧 `admin/Admin@123`）启动 uvicorn，`POST /api/auth/login` 用统一账号返回 200 + token；错密码 401。

## V4.11 素材创作模块（图片创作 / 视频创作 双子模块）

**需求**（来源：《推广图片与视频 智能素材创作平台 产品策划说明书 V1.0》）：在「素材管理」一级菜单下新增二级菜单「素材创作」；图片创作与视频创作作为两个独立子模块，以切换方式进入；两者基于同一份落地页综合分析，共享品牌色 / 产品图 / 创意方向，保证同一落地页在两个模块下素材风格一致；权限与系统其他模块保持不变。

**交付**
- 新增 `frontend/src/pages/MaterialCreation.tsx`：
  - 顶部统一的「落地页综合分析」（粘贴 URL/正文 → `api.report` → 渲染 `ReportView`）、「投放设置与品牌风格」（平台/语言/版位/品牌色/产品图）、「创意方向」三步，与「创作工作台」使用**同一分析引擎与同一 `ReportView` 组件**（从 `Workspace.tsx` 导出复用），确保分析展示完全一致。
  - 下方 Tab 切换：**图片创作** / **视频创作** 两个独立子模块。各自调用 `api.produce` 生成独立任务（图片：`image+copy+keyword`；视频：`video+copy` 并合成完整成片），但共享同一 `framework_id` / 品牌色 / 产品图 / 选定方向 → 风格一致。
  - 结果复用创作工作台既有素材墙样式（图片缩略图、文案 `CopyBlock`、视频播放器与关键帧列表），并各提供 ZIP 导出。
- `App.tsx`：Tab 联合类型、`TABS`、`GROUP_MATERIAL` 新增 `creation`（素材创作，图标 sparkles）；`allowedTabs` 纳入（编辑及以上角色可访问，与创作工作台一致）；主区域渲染 `MaterialCreation`。
- `Workspace.tsx`：导出 `ReportView / Chips / StepHead / CopyBlock`（仅加 `export` 关键字，行为与权限不变），供新模块复用。
- `styles.css`：补充 `.mc-banner`（一致性说明）、`.mc-tabs/.mc-tab`（子模块切换）、`.mc-pane`、`.wall` 样式。
- 验证：`npm run build` 通过（45 模块）。

## V4.12 素材创作平台（一级菜单重构 + 素材提示词管理）

**需求**（来源：《素材创作模块功能优化说明书》V2.1）：① 新增一级菜单「素材创作平台」；②「素材创作」作为「素材创作平台」的二级菜单；③ 新增二级菜单「素材提示词管理」，集中展示「素材创作」功能模块的全部提示词内容；④ 不改动账号权限相关功能。

**交付**
- `App.tsx` 菜单重构：
  - 新增一级菜单分组 `GROUP_CREATION`（素材创作平台，图标 wand），其下挂两个二级菜单：**素材创作**（`creation`）、**素材提示词管理**（`mprompts`，图标 tags）。
  - 将「素材创作」从原「素材管理」一级菜单移出，归入新的「素材创作平台」。
  - 侧边栏改为数据驱动（`allGroups` / `visibleGroups` / `visibleNavItems`），三组（素材管理 / 素材创作平台 / 系统设置）统一渲染、各自独立折叠。
  - 页面标题 kicker 改为按当前 tab 自动匹配所属一级菜单。
  - 权限沿用既有规则：`mprompts` 与 `creation` 同属「编辑及以上角色可见」，未触碰角色定义、鉴权与账号管理逻辑。
- 新增 `frontend/src/materialPresets.ts`：按《说明书》V2.1 第 6.2/6.3/6.4 节内置三大提示词库——**创意方向库（D01–D20，20 项）**、**创意内容风格库（S01–S26，26 项）**、**配色方案库（C01–C16，16 项）**。每项含编号、名称、说明、适用画像（图片/视频/通用）与注入生成时的「提示词指令」。P0 阶段为内置常量，与说明书 Q-M3 默认一致。
- 新增 `frontend/src/pages/MaterialPrompts.tsx`：素材提示词管理页。顶部说明 + 「创意方向库 / 内容风格库 / 配色方案库」三 Tab + 搜索框 + 适用画像筛选（全部/图片可用/视频可用/通用）；每条以卡片展示，可展开查看提示词指令；风格沿用既有设计令牌（`.card`/`.pill`/`.chip`），新增 `.mp-*` 样式。
- 验证：`npm run build` 通过（47 模块）；无账号权限逻辑改动。

## V4.13 三大提示词库接入实际生成流程（说明书 7.2 / 7.3）

**需求**（来源：《素材创作模块功能优化说明书》V2.1 第 7.2 / 7.3 节）：将创意方向库（D01–D20）、内容风格库（S01–S26）、配色方案库（C01–C16）接入「素材创作」的真实生成链路，使图片 / 视频创作**真正按所选方向 / 风格 / 配色产出**，而非仅作展示。

**后端**
- 新增 `backend/presets.py`：三大提示词库的单一数据源（与前端 `materialPresets.ts` 内容一致）；提供 `STYLE_TO_BG`（内容风格 → 渲染层背景键）、`COLOR_TO_PALETTE`（配色 → 调色板覆盖）映射，以及 `build_directives()` 把所选 方向/风格/配色/视频市场洞察 解析为 `extra_prompt`（注入文案）、`design_prompt`（注入视觉设计规范 LLM）、`design_overrides`（styles 背景键 + palette 调色板覆盖）、`video_prompt`（注入视频分镜）。
- `render.py`：
  - `render_creative` 读取 `design.palette` 覆盖 `accent/bg1/bg2/fg/sub/card/on_accent`，使配色方案真正落地到出图（验证：C13 霓虹绿均值 RGB (10,24,12) vs C15 朱红 (38,7,9) 明显不同）。
  - `STYLE_KEYS` 扩展 11 个新背景风格：`solid/ink/oil/cyber/retro/vapor/pixel/paper/neon/glitch/geo`，并在 `Canvas` 与 `paint_background` 实现对应绘制；`make_palette` 旁新增 `_apply_palette` 覆盖工具。
  - `normalize_design` 透传 palette（styles 经 STYLE_KEYS 校验）。
- `services.py`：`produce_campaign` 新增 `directives` 参数——文案生成 extra 拼接方向/风格/配色指令；设计规范以「用户所选风格/配色覆盖优先、LLM 补全 tone/layout」合并；`_design_spec` 追加 `ctx`（风格/配色约束）到提示词骨架；`_make_video` 将 `video_prompt`（含可选「借鉴市场总结再创作」）注入分镜脚本提示词。
- `schemas.py`：`ProduceRequest` 新增 `creative_direction` / `content_style` / `color_scheme` / `market_insight`。
- `routers.py`：新增 `GET /api/settings/creative-presets` 返回三库（供前端拉取，便于后续运营扩充）；`/api/produce` 接收四参数并经 `build_directives` 传入生成。

**前端**
- `api.ts`：新增 `creativePresets()` 接口与 `CreativePreset(s)` 类型；`produce` 入参扩展四字段。
- `MaterialCreation.tsx`：步骤④「素材创作」内新增「创意风格设定」区块——方向 / 风格 / 配色 三组选择器（单选 + 可清除，沿用 `.chip` 统一风格，适用画像非匹配项置灰），图片与视频共用同一份风格设定；视频子模块「借鉴市场总结再创作」开关 + 文本输入；默认配色 C12 品牌同色系（跟随品牌色，向后兼容）。选择随 `produce` 一并提交。
- `MaterialPrompts.tsx`：改为从后端 `/api/settings/creative-presets` 拉取（单一数据源），失败回退本地 `materialPresets.ts`。
- `materialPresets.ts`：`appliesTo` 参数放宽为 `{ applies: string }`，消除与后端类型的冲突。
- `styles.css`：新增 `.mc-style / .mc-style-grid / .mc-preset / .chip-row / .mc-style-summary / .mc-insight` 等，统一输入框/选项/按钮风格。

**验证**
- `py_compile` 后端全模块通过；`routers/services/presets/render` 导入正常。
- 出图像素级冒烟：6 组 方向×风格×配色 组合（含浅色方案 C04、品牌同色系 C12）均成功渲染图片与视频关键帧，无异常；调色板覆盖确实改变画面主色。
- `npm run build` 通过（47 模块）；`GET /api/settings/creative-presets` 路由可达（鉴权后）。

## V4.14 落地页分析升级：准确定位 + 九要素结构化总结 + 延伸输出

**需求**：「素材创作平台 → 素材创作」的落地页分析常把"在线营销/广告平台"误判为教育网站，且缺少对广告主/渠道/流量商需求的总结与吸引力亮点；需从通用报告升级为九要素结构化总结，并延伸输出行业/竞品/需求/差异化/优势与推荐媒体人群。

**改动**
- `backend/services.py` · `SYS_SITE_ANALYSIS` 提示词扩展：
  - 新增 `business_nature`（网站本质，新增 `is_marketing_platform` 标记）、`target_clients`（区分 toC 终端用户 与 toB 广告主/渠道/流量主，并各自总结需求）、`appeal_highlights`（吸引力亮点）。
  - 新增 `nine_elements`（行业/类型/品类/满足需求/解决方案/商业模式/优势对比/差异化特色/一段话目的总结）、`extensions`（行业分析/竞品/市场需求/差异化方案/特色优势/推荐媒体/推荐人群）。
  - 硬约束新增 9–13 条：优先判断网站本质，营销/广告/代理平台用 `adtech`/`marketing` 分类，不得因页面含教程/案例误判为教育；必须区分 toC/toB 目标客户与各自需求；先九要素再延伸输出。
  - `category_key` 集合扩至含 `adtech`/`marketing`。
  - `_local_site_analysis` 回退函数补充以上新字段占位，保证无模型/解析失败时报告仍有两段内容。
- `backend/report.py` · `build_report`：
  - 新增三个 section（ReportView 数据驱动自动渲染）：
    - `positioning_deep`（网站定位与目标客户）：网站本质、是否营销平台、终端用户/广告主/渠道/媒体四类需求、吸引力亮点；
    - `nine_elements`（九要素结构化总结）；
    - `extensions`（延伸输出 · 行业/竞品/需求与推荐）。
  - 配套三个 helper：`_positioning_deep_section` / `_nine_elements_section` / `_extensions_section`。
- `frontend/src/styles.css`：`.rv` 增加 `white-space: pre-wrap`、`.rk` 顶对齐，保证九要素/延伸输出的长文本可读。

**验证**
- `py_compile` 后端全模块通过；`build_report` 冒烟：mock 含九要素与延伸输出的 `site_analysis`，三个新 section 顺序与内容正确（定位→网站定位与目标客户→九要素→…→延伸输出）。
- `npm run build` 通过（47 模块）。

## V4.15 素材提示词管理补「落地页分析」说明 + 报告长卡片折叠

**需求**
1. 「素材提示词管理」补一个「落地页分析提示词」字段说明（网站本质/目标客户/吸引力亮点/九要素/延伸输出）。
2. 「素材创作 / 创作工作台」的九要素、延伸输出等长卡片在内容过长时支持折叠/展开。

**改动**
- `frontend/src/materialPresets.ts`：新增 `LANDING_ANALYSIS_FIELDS` 常量，结构化描述落地页分析提示词的字段（business_nature / target_clients / appeal_highlights / nine_elements 9 项 / extensions 7 项）。
- `frontend/src/pages/MaterialPrompts.tsx`：新增第 4 个 Tab「落地页分析」，展示以上字段说明（与三库 Tab 统一卡片风格，子字段以列表呈现）；预设库 Tab 保留搜索与画像筛选。
- `frontend/src/pages/Workspace.tsx` · `ReportView`：
  - 新增 `expandedSec` 状态；对行数 ≥ 6 的 section（九要素 / 延伸输出 / 网站定位与目标客户等）加折叠：默认收起并限制高度 + 底部渐隐，标题右侧出现「展开（N 项）▾ / 收起 ▴」按钮。
  - section 头部改为 `.rsec-head`（标题 + 折叠按钮），内容包进 `.rsec-body`。
- `frontend/src/styles.css`：新增 `.rsec-head`、`.rsec-toggle` 与折叠相关样式；新增 `.mp-subs`（落地页分析子字段列表）样式。

**验证**
- `npm run build` 通过（47 模块）；打包产物含「落地页分析 / 网站本质 / 九要素结构化总结 / 延伸输出 / 展开（ / 收起 ▴」等文案。
- 账号权限逻辑未改动。

## V4.16 创意方向真正驱动画面（告别"换方向画面不变"）

**根因**
- 「创意方向 D01–D20」此前只注入了文案提示词（`extra_prompt`）与 LLM 设计语气，**从未进入视觉生成**：画面主体/版式完全由另一套内部 8 个 `angle_key` 的 `template` 决定，与用户选的 D 是两套体系。因此切换不同创意方向，图片/视频看起来一模一样。
- 内容风格 S 虽能改背景，但很多 S 映射到相近背景（gradient/geo/radial），且默认配色 C12 跟随品牌色；配色 C 生效但默认也跟随品牌色——不主动改就"看起来都差不多"。

**改动**
- `backend/presets.py`：
  - 新增 `DIRECTION_TO_TEMPLATE`（D01–D20 → 渲染版式）：信任背书→rating、限时优惠/节日/稀缺/新品→promo、对比→compare、用户证言/KOL→ugc、权威数据→stat、场景代入→scenario、其余→bigtype。让"创意方向"决定画面里到底画什么。
  - 新增 `DIRECTION_TO_BG`（D→兜底背景键）：用户**未**单独选内容风格时，按方向自带背景（痛点→聚光、科技→赛博、国风→水墨…），保证只切方向背景也变。
  - `build_directives` 返回 `template` 字段；背景优先级改为「内容风格 > 创意方向兜底」。
- `backend/services.py`：`produce_campaign` 提取 `directives["template"]`，图片与视频的 `_render_spec` 均改用 `template_override or 内部 angle 默认版式`（空值向后兼容）。
- `backend/render.py`：补齐长期缺失的 `scenario` 版式分支（内部 `scenario` 角度此前被降级成大字版），实现"上场景面板 + 下文字"的沉浸构图；无产品图时用合成手机界面占位。

**验证**
- 冒烟：D04/D05/D06/D07/D13/D03/D01 分别产出 rating/promo/compare/ugc/stat/scenario/bigtype **7 种不同版式**；D09 在未选风格时回落 solid 背景（其余 S21→split），证明方向驱动背景生效。
- 配色：同方向同风格下 C13(霓虹绿)/C15(国风朱红)/C01(多彩渐变) 的 mean RGB 分别为 `[21.9,36.6,27.4]` / `[56.3,17.3,18.5]` / `[66.8,44.9,91.6]`，配色覆盖确实改变画面主色。
- `py_compile` 三个改动模块通过。

## V4.21 文生图接入阿里 MaaS 多模态（qwen-image）专属协议

**问题**
- 用户提供了一个通义千问图像 MaaS 端点（llm-*.maas.aliyuncs.com/.../multimodal-generation/generation，模型 qwen-image-3.0）。实测验证 API 可用（Key 已绑定该工作空间），但其协议与系统现有文生图 Provider 完全不兼容：
  - 请求路径：整条 URL 即 endpoint（非 `/images/generations`）；
  - 请求体：`{"input":{"messages":[{"content":[{"text": prompt}]}]},"parameters":{"size":"W*H"}}`（messages 数组，非 `{prompt}`）；
  - 返回：签名 OSS 临时 URL（需立即下载），非 b64；
  - 仅同步（带 `X-DashScope-Async` 会被 403 拒绝）。
- 此前若直接填这个地址，系统的连通测试与出图都会失败或错配。

**新增：dashscope-maas-image 协议**
- `backend/providers.py`：新增 `DashScopeMaaSImageProvider`，POST 完整 base_url，messages 风格请求体，`parameters.size` 自动对齐到 API 支持的 1024/2048，同步返回后**立即下载签名 URL 落盘**为本地背景图；任一环节失败返回 None（Pillow 模板兜底）。
- `backend/llm_catalog.py`：新增 `qwen-image-maas` 图像预设（protocol=`dashscope-maas-image`，default_base_url=该 MaaS 完整 endpoint，models=[qwen-image-3.0, qwen-image-3.0-pro]）；新增 `_test_dashscope_maas_image` 测试器（真实出图验证，消耗额度的同步调用）并注册到 `_TESTERS`；顶部协议注释补充该协议。
- `backend/providers.py`：`get_image()` 按 `image_protocol_of` 路由到新 Provider。
- `backend/CHANGELOG.md`：本条目 + 补 V4.20。

**验证**
- `py_compile`：providers / llm_catalog 通过。
- 端到端冒烟（真实 API）：`DashScopeMaaSImageProvider.generate` 产出 1024×1024 PNG（436KB，签名 URL 下载落盘）；`get_presets("image")` 含 `qwen-image-maas`；`image_protocol_of("qwen-image-maas")="dashscope-maas-image"`。

## V4.22 落地页分析准确性 + 图片/视频背景差异化（审计与优化）

**审计结论（用户原问：哪些是固定框架、哪些真用了大模型）**

落地页分析实际由两段叠加，并非都走大模型：
- **固定框架（本地规则，非大模型）**：`insight.py` 本地抽取——`product/category/audience/geo/languages/selling_points/metrics`，以及 `platform_analysis`（各平台打法，来自 `PLATFORM_NOTES` 按品类取模板）。`geo`/`languages`/`platform_analysis` **永远**来自本地，从不被大模型覆盖。
- **真正的大模型分析（仅当配置了专用"分析"模型）**：`analyze_site` 产出 9 模块（`business_nature/nine_elements/extensions/target_clients/appeal_highlights/channel/risk/next_steps` 等）。**未单独配置"分析"模型时，整段 9 模块走 `MockLLM→_local_site_analysis` 模板占位**，且还会把 `category/audience/selling_points` 覆盖成通用模板值 → 表现为"很多维度不准确"。
- 图片/视频：配置了文生图模型后，`_build_image_prompt` 只把风格键（如 `cyber`）+ 中文内容描述丢给模型，qwen-image 无法据此产出差异化背景；且 AI 底图贴上后 `render_creative` 直接跳过 Pillow 的 `paint_background`，导致 V4.16 精心设计的「方向→背景风格」差异化不可见 → 背景千篇一律，只有文案/文字色在变。

**改动**

1. 分析模型复用（修复"只配一个模型却全程模板"）：`analyze_site` 优先专用"分析"模型；未配置但有"文案"文本模型时，复用"文案"模型驱动真实分析（`_source_usage` 如实标注）。
2. 解除本地事实锚定：`build_site_prompt` 把"以此为准，不要编造"改为"仅供参考，请以正文独立判断并纠正"，并新增 `geo`/`languages` 输出字段 + 约束（独立判断、禁止照搬本地抽取、各平台打法须按产品定制）。
3. 维度回填：`analyze_landing_page` 现在接收大模型产出的 `geo`/`languages`，并用 LLM 的 `channel`（各平台打法）按平台合并进 `platform_analysis`（缺失平台用本地模板兜底），替代"同品类共用一套打法"。`evidence._sources` 增加维度级来源标注（llm / local / local-template）。
4. 文生图提示词重写（`_build_image_prompt` + `presets.py`）：新增 `STYLE_VISUAL`（风格键→英文视觉描述）、`DIRECTION_MOOD`（创意方向→英文情绪）、`palette_prompt`（配色→hex 颜色描述）；提示词改为"方向情绪 + 风格视觉 + hex 配色 + 角度情绪"的具体可区分描述，按角度区分。
5. AI 底图叠加风格母题（`render.py`）：新增 `_style_motif`，在 AI 底图 + scrim 之上以约 13% 透明度叠加方向/风格母题（暗角/聚光/对撞/网格等），保证即使图像模型较弱也能看出方向/风格差异。**同时修复一处潜在缺陷**：AI 底图就位后原先未重绑 `c.d`，会导致后续文案画到旧图层（文字丢失）；现已在合成后重绑 `c.d`。

**验证**
- `py_compile`：services / render / presets 全部通过；`import main` 65 路由正常。
- 单元：文生图提示词生成含具体视觉词（"neon-lit cyberpunk"）与 hex（"#FF8A1E"）；`build_directives` 的 `design_overrides` 正确携带 `styles/palette`；geo/languages/platform_analysis 合并逻辑按 LLM 输出正确回填。
- 渲染冒烟：`render_creative` 在「有 AI 底图」与「纯 Pillow」两条路径均生成成功；`_style_motif` 对全部 19 种风格键无崩溃。

## V4.23 大模型配置改为弹窗，并支持多用途 / 自定义名称 / 厂商专属附加字段

**需求**：把"大模型配置"的添加/编辑改为弹窗；字段含「名称、大模型（下拉）、模型版本、用途（多选）、模型请求链接、API Key」，并按厂商要求动态补充其它必要字段。

**改动（前端 `LLMSettings.tsx` 重写为弹窗）**
- 弹窗字段：名称（自定义配置名）→ 大模型（全量预设下拉，按 文本/文生图/文生视频 分组，选中自动带出默认地址与模型）→ 模型版本（即 Model，提示"公司与版本号"）→ 用途（多选 Checkbox）→ 模型请求链接（Base URL）→ API Key → 厂商专属附加字段（如文生图/视频的"自定义端点路径"）。
- 用途多选：按模态过滤可选项——文本模型可选「落地页分析 / 文案」可同时勾选；文生图仅「推广图片」；文生视频仅「推广视频」。
- 列表展示：名称、厂商、用途标签、模型版本、请求链接、状态、编辑/删除；遮罩点击或取消关闭弹窗。

**改动（后端）**
- `models.ModelConfig` 新增 `name`（自定义名称）与 `usages`（JSON 数组，多用途）；`usage` 保留为主用途字符串以兼容旧数据。
- `schemas.ModelConfigIn` 的 `usage` 支持 str|list；`ModelConfigOut` 新增 `name`/`usages`，并对无 `usages` 的旧数据由 `usage` 推导（避免 NULL 校验失败）。
- `routers`：`create/update` 归一化 usage 为数组写入 `usages`；"同用途仅一个激活"改为**仅停用用途被新配置完全覆盖的旧配置**（多用途配置不会被整体停用，仍服务其它用途）；`list` 返回 `usages` 数组。
- `providers._active_config`：按 usages 数组包含匹配，同用途多配置时取**最近创建（id 最大）**者，使新配置按其用途接管、旧多用途配置继续服务其余用途。
- `llm_catalog`：新增 `modality_of`（协议→text/image/video）、`get_all_presets`（全量）；`_PROTOCOL_EXTRA` 为 generic-image / generic-video 默认注入 `endpoint` 附加字段；预设接口支持 `usage=all` 并透出 `modality` 与 `extra_fields`。

**验证**
- 前端 `npm run build` 通过（47 模块）。
- 后端流程测试：创建 [analysis,copy] 文本配置 + [image] 配置 + 仅 [analysis] 配置后，getter 正确——analysis 取较新的 deepseek、copy 仍取 qwen、image 取 custom-image；旧单字符串行经 `usages` 推导正常。
- 预设接口 `usage=all` 返回 33 项，含 `modality` 与 `extra_fields`（generic-image 正确带出 endpoint）。

## V4.24 素材创作重构：落地页分析（8 字段 LLM 推理）+ 素材提示词库

**需求**
1. 「素材创作」只保留「落地页分析与评价」，删除图片/视频创作、创意方向、媒体与品牌设置等子模块，逐步重建。
2. 落地页分析必须调用大模型推理（非本地规则），输出 8 个必要字段：①网站地址（仅展示）②语言 ③行业 ④类型 ⑤对象 ⑥竞品（全球 Top3）⑦优势（≤5，提炼非罗列）⑧推广途径（≤5，含平台+推荐理由）。
3. 素材创作统一调用「大模型配置」已配置模型，按需要用正确模型，并在结果后标注本次实际调用的模型（便于持续跟踪优劣势）。
4. 删除「素材提示词管理」模块；新增二级菜单「素材提示词」，把改造后的提示词分门别类展示，可编辑/保存。

**后端**
- 新增 `PromptConfig.category` 列（`migrations.ensure_schema` 自动 ALTER 补齐）。
- `services.PROMPT_REGISTRY` 并入 5 段落地页分析提示词（`landing_framework / landing_basic / landing_competitors / landing_advantages / landing_channels`），统一 `module=素材创作（落地页分析）`、各自 `category`（分析框架 / 基础识别 / 竞争分析 / 价值提炼 / 增长推广）；运行时拼接为一份系统提示词一次调用。
- 新增 `analyze_landing_concise()`：抓取（无正文时）→ 拼接提示词 → 调用已配置「分析」模型（未配则按 V4.22 模式复用「文案」模型）→ 稳健解析 8 字段；返回 `model_info`（provider/model/role/fallback）与 `source`（llm/local）。未配置有效模型时如实标注本地兜底。
- `routers`：新增 `POST /api/landing-analysis`；`GET /api/settings/prompts` 支持 `module` 过滤；`update_prompt` 的 MARKER 强校验改为「仅对默认提示词本身含 MARKER 的提示词生效」，落地页分析等无 MARKER 提示词可自由编辑。

**前端**
- `api.ts`：新增 `LandingAnalysis / ModelInfo / LandingChannel` 类型与 `api.landingAnalysis()`；`prompts(module?)` 支持按模块过滤；`PromptConfig` 增加 `category`。
- `App.tsx`：删除 `mprompts`/MaterialPrompts，新增 `matprompts`/MaterialPromptLibrary（素材创作平台二级菜单：素材创作、素材提示词）。
- `MaterialCreation.tsx` 重写为纯落地页分析：输入 → 分析 → 展示 8 字段 + 模型信息横幅（明确"本次由哪个模型推理"）；本地兜底时提示需配置大模型。
- 新增 `MaterialPromptLibrary.tsx`：按 `category` 分门别类展示 5 段提示词，复用提示词编辑/恢复默认弹窗，保存即生效。

**验证**
- 后端 `python -m py_compile` 通过；`migrations.ensure_schema` 自动补齐 `prompt_configs.category` 列。
- 烟雾测试：5 段提示词正确播种（module/分类一致）；拼接提示词非空且含 8 字段键；`analyze_landing_concise` 返回结构经 `LandingAnalysis(**result)` 校验通过（channels→list、model_info→ModelInfo 正确）。
- 前端 `npm run build` 通过（47 模块）。

## V4.25 素材创作：营销推广的媒体平台设置模块

**需求**
1. 在「素材创作」落地页分析之后，新增「营销推广的媒体平台设置」：可基于已分析的落地页选择媒体推广平台，也可自主选择。可选平台：Facebook / Google / Mintegral / Unity / Adsterra / AppLovin / TikTok 等，默认仅可选其一。
2. 选中平台后展示该平台支持的图片素材数量、规格、尺寸；可设置生成图片的数量、版位（按常规方案默认）。
3. 生成图片必须依据网站落地页分析结论（8 字段），由大模型完成图片生成任务，并在结果中标注实际调用的模型。
4. 生成前可先选择图片风格 / 样式 / 颜色等（尽量丰富的选项），以产出更吸引用户的推广图。
5. 广告文案生成需结合落地页分析结论；文案即时显示、可编辑，编辑后的文案最终呈现在推广图中。
6. 布局按流程展示：设置媒体平台 → 展示文案 → 生成推广图片。

**后端**
- 新增 `backend/media_platforms.py`：7 平台规格单一数据源 `MEDIA_PLATFORMS`（Facebook/Google/Unity/AppLovin/Adsterra/Mintegral/TikTok），每平台含 `image_sizes / recommended_sizes / recommended_count / copy_limits / usage / cta_options / placements[]`；导出 `list_media_platforms()` / `get_media_platform()` / `MEDIA_PLATFORM_MAP`。
- 新增 `backend/media_ad.py`：
  - `MEDIA_COPY_SCHEMA` 在 `creative.COPY_SCHEMA` 基础上补齐 TikTok（headline≤40 / body≤100 / cta≤20）。
  - `generate_media_copy(db, analysis, platform, lang)`：以落地页 8 字段分析结论为生成依据，调用已配置「文案」模型，逐字段 `fit_text` 按平台字数上限裁剪；返回 `fields / schema / char_table / validation / model_info`（provider/model/role/fallback）/ brand`。
  - `generate_media_images(db, analysis, platform, lang, copy_fields, style_opts, slots)`：`build_directives` 解析风格/样式/配色 → 取 `STYLE_TO_BG / DIRECTION_TO_BG / COLOR_TO_PALETTE` → `get_image(db)` 出 AI 背景（未配图像模型则 Pillow 模板兜底）→ `render_ad_png` 叠加文案 → 返回 `images[{url,file,size,w,h,placement}] / image_model / note / count`；`image_model` 如实标注（有图像模型用 provider/model，否则标注 template 兜底）。
  - `_analysis_context()` 将 8 字段拼为生成依据；`_media_image_prompt()` 结合落地页结论与风格选项；`_overlay_text()` / `_cleanup_ai_bgs()` 管理叠加与临时文件。
- `schemas.py`：新增 `MediaCopyRequest{analysis,platform,lang}` / `MediaImageSlot{size,placement}` / `MediaImageRequest{analysis,platform,lang,copy_fields,style_opts,slots}`；`LandingAnalysis` 加 `protected_namespaces=()` 消除 `model_` 前缀警告。
- `routers.py`：新增 3 端点（均 `require_roles(*CAN_EDIT)`）：
  - `GET /api/media-platforms` → `list_media_platforms()`
  - `POST /api/media-campaign/copy` → `generate_media_copy(...)`
  - `POST /api/media-campaign/images` → `generate_media_images(...)`

**前端**
- `api.ts`：新增 `MediaPlacement / MediaPlatform / MediaCopyResult / MediaImageItem / MediaImageResult` 类型与 `api.mediaPlatforms()` / `api.mediaCopy()` / `api.mediaImages()`。
- `App.tsx`：Tab 体系新增 `'media'`（营销推广设置，icon `broadcast`），`allowedTabs` 的 canEdit 组加入 `'media'`；`MaterialCreation` 分析完成后通过 `onOpenMedia` 跳转；新增 `MediaAdStudio` 接入。
- 新增 `pages/MediaAdStudio.tsx`：三步流程页（设置媒体平台 → 展示文案 → 生成推广图片）；Step1 选单平台卡片并展示规格/版位多选/数量/语言；Step2 可编辑文案字段 + 品牌名 + 风格/样式/颜色下拉（数据取自 `api.creativePresets()`）；Step3 网格展示生成图并标注 `ModelBadge`（fallback 标 warn）。
- `MaterialCreation.tsx`：分析 `ResultView` 末尾新增「进入营销推广的媒体平台设置 →」按钮，携带 `LandingAnalysis` 跳转。
- `styles.css`：追加媒体工作室样式（`.media-studio / .stepper / .mstep / .model-badge / .platform-grid / .platform-card / .spec-panel / .placement-card / .copy-grid / .copy-field / .style-panel / .img-grid / .img-card / .la-next` 等），步骤条类名独立以避免与素材创作模块冲突。

**验证**
- 后端 `python -m py_compile` 通过；前端 `npx tsc --noEmit` 退出码 0。
- 端到端烟雾测试：7 平台列表正常返回；文案生成实际使用真实模型（千问大模型 / qwen-plus，fallback=False），字段由落地页分析结论推导；3 张图片按 1080x1080/1080x1350/1080x1920 生成，经 `/files/` 访问返回 HTTP 200，image_model 如实标注（未配图像模型时为 Pillow 模板兜底）。

**修正（模块位置）**
- 原 V4.25 将「营销推广设置」作为独立一级菜单（tab `media`）承载，与分析结论脱节。按需求改为：**嵌入「素材创作」模块内部**，作为落地页 8 字段分析完成之后的下一步，流程为「落地页分析 → 营销推广设置（选平台 → 文案 → 生成推广图片）」。
- `App.tsx`：移除 `media` 一级 tab（`Tab`/`TABS`/`GROUP_CREATION`/`allowedTabs` 同步移除），删除 `mediaSeed`/`openMedia` 状态与 `MediaAdStudio` 独立渲染；`MaterialCreation` 不再接收 `onOpenMedia`，直接渲染且不再跳转。
- `MaterialCreation.tsx`：`ResultView` 末尾的「进入营销推广的媒体平台设置 →」按钮改为页内滚动到下方嵌入区；分析出 `data` 后在同一页面内渲染 `<MediaAdStudio initialAnalysis={data} />`，其 `onGotoCreation` 改为滚动回顶部重新分析。
- `styles.css`：新增 `.media-studio-section`（顶部 2px 分隔线 + 间距），在视觉上将「分析结论」与「营销推广设置」划分为同一模块内的两个连续步骤。

## V4.20 403 提示识别 MaaS 工作空间 access_denied

- `backend/llm_catalog.py`：`_classify_error` 的 403 分支检测 body 中的 workspace / access_denied，给出 MaaS 工作空间专属 Key 指引（ws-*.maas.aliyuncs.com / llm-*.maas.aliyuncs.com 需绑定工作空间的专用 Key，且区域需一致）。

## V4.19 通义千问国际站预设 + 404 提示增强

**问题**
- 用户配置 DashScope 国际站（`dashscope-intl.aliyuncs.com`）时，Base URL 误填为 `/api/v1`（正确为 `/compatible-mode/v1`），导致连通测试 `404 not_found`。原 `qwen` 预设默认是国内站地址，国际站用户需手动改路径，易踩坑。

**修复**
- `backend/llm_catalog.py`：新增 `qwen-intl` 预设（通义千问 DashScope 国际站），默认 `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`，模型含 qwen-plus/qwen-max/qwen-turbo 等，setup_guide 明确国际站路径；`_classify_error` 的 404 提示补充"国际站 dashscope-intl 误用 /api/v1"的易错点。
- `CHANGELOG.md`：本条目。

## V4.18 文生图大模型配置模块 + 文生图真正接入生成链

**问题**
- 排查发现 `providers.py` 早已定义 `OpenAIImage`（文生图），但 `services.py` 的素材生成流程**从未调用 `get_image()`**——所有图片都是 Pillow 模板（`render_creative`）渲染。这是"图片/视频背景内容都一样"的更深根因之一（另一根因"创意方向不驱动画面"已在 V4.16 修复）。
- 现有"大模型配置"界面只有文本 LLM 目录（`LLM_PRESETS`），**文生图/文生视频没有专属模型目录**，用户无法像配文本模型那样选择文生图模型名称并填 Key/请求链接。

**新增：文生图 / 文生视频模型配置模块（与现有大模型配置界面一致）**
- `backend/llm_catalog.py`：新增 `IMAGE_PRESETS`（dalle3 / azure-dalle / 通义万相 wanx / 智谱 cogview / Stable Diffusion / Flux-Replicate / 即梦 / 自定义）与 `VIDEO_PRESETS`（runway / 可灵 keling / pika / 即梦视频 / 自定义），字段含 key/name/protocol/default_base_url/models/api_key_label/docs_url/setup_guide/notes；新增 `get_presets(usage)`、`image_protocol_of`/`video_protocol_of`、协议感知测试的 `openai-image`/`generic-image`/`generic-video` 分支（图像做最小出图验证，视频/异步厂商验证可达性与鉴权）。
- `backend/schemas.py`：`ModelTestIn` 增加可选 `endpoint`（通用图像端点）。
- `backend/routers.py`：`GET /settings/models/presets` 支持 `?usage=` 返回对应目录；`POST /settings/models/test` 透传 `endpoint`。
- `frontend/src/api.ts`：`modelPresets(usage?)` 支持按用途拉取。
- `frontend/src/pages/LLMSettings.tsx`：预设选择器**按用途切换目录**（文本/文生图/文生视频）；新增用途分段标签与文生图/视频专属说明横幅；图像/视频模型显示"自定义端点路径（可选）"输入；保存与测试携带 `endpoint`。
- `frontend/src/styles.css`：新增 `.usage-tabs` / `.usage-tab` 及图像/视频协议徽标配色。

**核心修复：文生图大模型接入生产链**
- `backend/providers.py`：`OpenAIImage` 改为"只产出背景底图路径"；新增 `GenericImageProvider`（按 `params.endpoint` 兼容万相/CogView/SD/Replicate/即梦等）；`get_image(db)` 按目录协议选择 provider，**未配置时返回 `None`**（由 Pillow 模板兜底）。
- `backend/render.py`：`render_creative` 支持 `data["bg_path"]`——AI 背景覆盖式贴底 + 上浅下深品牌色 scrim 保证文字可读，并跳过 Pillow 渐变背景；全部版式（评分卡/折扣角标/对比/手机框/场景/大字）在 AI 背景上正常合成。
- `backend/services.py`：`produce_campaign` 取 `img_provider = get_image(db)`；图片与视频关键帧在配置文生图模型后，按创意方向/风格/配色合成文生图 prompt（`_build_image_prompt()`）调用模型生成背景并传入渲染；新增 `_cleanup_ai_bgs()` 清理中间背景图。

**验证**
- `py_compile`：llm_catalog / providers / services / routers / render / schemas 全部通过。
- 冒烟：文生图目录 8 项、视频目录 5 项字段完整；`image_protocol_of("sd")="generic-image"`、`image_protocol_of("dalle3")="openai-image"`；`_build_image_prompt()` 正确拼接；`render_creative` 在 7 种版式下带 `bg_path` 均正常出图且与原图有差异。
- `npm run build`：47 模块编译通过，0 错误。
- 配套分析文档：`文生图与模型提示词归类分析.html`（文生图调用模块、模型类型归纳、提示词/大模型管理归类总表）。

## V4.17 创作工作台同样接入三大设置（与素材创作统一）

**问题**
- 排查发现「素材管理 → 创作工作台」与「素材创作平台 → 素材创作」共用同一套生成后端（`POST /api/produce`），但创作工作台的 `produce` 调用**从未传入 `creative_direction / content_style / color_scheme`**，且整个页面**没有**三大设置的选择 UI。
- 结果：用户在三大提示词库里配置的创意方向/内容风格/配色方案，在创作工作台里完全不生效——图片/视频只走内部 8 个 `angle_key` 的默认版式，配色只随框架品牌色，与"按设置的方向/风格出图"的预期完全脱节（与 V4.16 修复前素材创作的症状同源，但更严重：连选择入口都没有）。

**改动**
- `frontend/src/pages/Workspace.tsx`：
  - 新增导入 `CreativePreset` 与三大库常量 `DIRECTIONS/STYLES/COLORS/appliesTo`。
  - 把 `PresetSelect` 组件**上提并导出**到创作工作台（单一数据源），「素材创作」改为从创作工作台复用，消除重复实现与潜在漂移。
  - 组件内新增三大设置状态（`directionId/styleId/colorId`，配色默认 `C12` 品牌同色系）与 `api.creativePresets()` 拉取（失败回退本地常量）。
  - 在「② 投放设置」新增「创意风格设定」区块（三个 `PresetSelect` + 说明文案，解释它和「③ 创意方向（叙事角度）」是两层叠加关系）。
  - `produce` 调用补齐 `creative_direction/content_style/color_scheme`，使其与素材创作行为一致。
- `frontend/src/pages/MaterialCreation.tsx`：移除本地 `PresetSelect`，改从创作工作台 `import`（复用同一组件）。
- `frontend/src/styles.css`：新增 `.mc-style-block` / `.mc-style-title`（创作工作台创意风格设定区块样式）。

**验证**
- `npm run build`：47 模块编译通过，0 错误。
- 后端无需改动——`POST /api/produce` 早已从 `req` 读取三大参数并 `build_directives`（V4.13/16），创作工作台传参后即触发 V4.16 的版式/背景/配色覆盖逻辑。

## V4.10 全球主流大模型可配置化（目录 + 协议感知测试 + 引导）

**需求**：用户可填写主要 API 配置即可完成大模型调用测试与配置；添加时选择大模型名称，选中后显示可配置字段，保存后首次调用并给出成败与具体错误引导。

**交付**
- 新增 `backend/llm_catalog.py`：覆盖 18 个主流厂商的预设目录（OpenAI / DeepSeek / 通义千问 / Kimi / 智谱GLM / 百川 / MiniMax / 硅基流动 / Groq / OpenRouter / Together / Perplexity / Mistral / Ollama / vLLM / Anthropic / Gemini / 自定义）。每项为：协议、默认 Base URL、常见 Model、必填字段标签/占位、官方文档链接、中文配置步骤、注意事项。
- 协议感知连通测试 `test_llm_connection()`：按 provider 查目录决定协议，真正发起最小调用——
  - `openai`：`/chat/completions`（覆盖绝大多数兼容网关）；
  - `anthropic`：自有 `/v1/messages`（x-api-key 头）；
  - `gemini`：`/v1beta/models/{model}:generateContent?key=`。
  - 失败结构化诊断：`error_type`（auth/permission/not_found/rate_limit/network/bad_request/unknown）+ 中文引导 + 该厂商官方文档链接 + 原始错误（可折叠）。
- 接口：`GET /api/settings/models/presets` 返回目录；`POST /api/settings/models/test` 改用 `ModelTestIn`（不强制 usage），返回结构化结果。
- 运行期 `providers.get_llm` 按目录协议分发到 `AnthropicLLM` / `GeminiLLM` / `OpenAICompatibleLLM`，使配置的真实模型在分析/文案场景真正可用，失败时回退 Mock。
- 前端 `LLMSettings.tsx`：「＋ 添加大模型」→ 目录选择（搜索 + 协议徽标）→ 自动带出默认 Base URL / Model 建议 / 字段标签 → 填 Key 即完成 →「保存并测试」先落库再首次真实调用 → 成功显示延迟与回包；失败显示错误类型、中文引导与官方文档链接。已配置列表按目录名称展示。
- `api.ts` 增加 `modelPresets()` 与 `ModelPreset` / `ModelTestResult` 类型；`styles.css` 补充目录卡片、协议徽标、Model 建议 chip、配置引导、文档链接、原始错误等样式。

**验收证据**
- `py_compile` 全过；`import main` 64 路由正常。
- 单元：目录完整性（18 项、协议映射正确）；错误分类 401/404/429/ConnectError 均产出正确 `error_type` 与文档标签。
- HTTP E2E（token 鉴权后）：`/presets` 返回 18 项；`/test` 坏 Base URL → `network`+中文引导+文档链接；缺字段 → `bad_request`；`POST /settings/models` 创建成功。
- `npm run build` 前端 44 模块通过。
