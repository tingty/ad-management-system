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

## V4.26 大模型配置：厂商目录扩容 + 下拉兜底

**问题**
- 「大模型配置 → 添加大模型」的「大模型」下拉为空（无可选厂商）。排查确认：后端 `/api/settings/models/presets?usage=all` 正常返回、且每条带 `modality`，前端按 `modality` 分组渲染逻辑正确；空下拉多为部署侧未同步最新后端/前端构建所致。同时按需求扩充可选厂商。

**交付**
- `backend/llm_catalog.py`：厂商目录由 33 家扩容至 **60 家**（文本 32 / 文生图 16 / 文生视频 12）。新增国产与海外主流厂商：
  - 文本：豆包/火山方舟、腾讯混元、百度文心一言(千帆)、零一万物 Yi、阶跃星辰 StepFun、Cohere、xAI Grok、NVIDIA NIM、Cloudflare Workers AI、Novita、Upstage、Lemonfox、PPIO。
  - 文生图：Stability AI(SD3.5)、Ideogram、Recraft、腾讯混元图像、Lemonfox 图像、302.AI 图像、MiniMax 图像。
  - 文生视频：Luma Dream Machine、PixVerse、Haiper、Vidu(生数)、腾讯智影、Higgsfield、302.AI 视频。
  - 每家均带默认 Base URL、常见模型名、Key 标签、setup_guide 与官方文档链接，选中即带出。
- `frontend/src/pages/LLMSettings.tsx`：下拉分组 `(p.modality || 'text')` 兜底，避免个别预设缺 `modality` 字段时整组消失、下拉为空。

**验证**
- `python -m py_compile` 通过；认证调用 `GET /api/settings/models/presets?usage=all` 返回 60 条，全部带 `modality`（text 32 / image 16 / video 12）。
- 前端 `tsc --noEmit` 退出码 0。
- 注：若线上仍为空，请确认已 `git pull && docker compose up -d --build` 同步最新构建，并在浏览器 Network 中确认 `/api/settings/models/presets` 返回 200 与数据。

## V4.27 素材创作：展示文案竖向布局 + 品牌 Logo 抓取/选择/合成

**需求**
1. 「素材创作 → 营销推广设置 → 展示文案」子模块中，推荐文案的展示布局改为从上到下的竖向流（原为双列网格）。
2. 落地页分析新增品牌 Logo：从网站抓取品牌/公司 logo 并展示，支持选择是否使用抓取的 logo，也支持手动上传本地 logo；所选 logo 用于后续推广图片合成。

**交付**
- 文案布局：`frontend/src/styles.css` 将 `.copy-grid` 由 `display:grid` 双列改为 `display:flex; flex-direction:column` 单列竖向流，字段依次从上向下排布。
- 品牌 Logo 抓取（后端）：
  - `backend/services.py`：`fetch_page` 现一并返回原始 `html`；新增 `extract_logo(html, base_url)`，按优先级（含 'logo' 关键字的 `<img>` > apple-touch-icon > og:image > favicon）启发式提取品牌/公司 logo 并解析为绝对 URL；`analyze_landing_concise` 在抓取后计算 `logo` 并随 8 字段一并返回（兜底路径同样返回，便于后续合成复用）。
  - `backend/schemas.py`：`LandingAnalysis` 新增 `logo: str = ""`。
- 品牌 Logo 合成（后端）：
  - `backend/imaging.py`：`render_ad_png` 新增 `logo_path` 参数，将 logo 合成到广告图右上角安全区（小 banner 贴右中）；自动处理透明通道，并对无透明通道的 JPG 做近白背景去除。
  - `backend/media_ad.py`：`generate_media_images` 新增 `logo` 入参，支持 `/files/...`（已上传）与远程 http(s) URL 两种来源，下载/映射到本地后传入合成；`_cleanup_ai_bgs` 一并清理临时下载的 `_mlogo_*`。
  - `backend/schemas.py`：`MediaImageRequest` 新增 `logo: str = ""`；`backend/routers.py`：`/api/media-campaign/images` 透传 `req.logo`。
- 品牌 Logo 展示与选择（前端）：
  - `frontend/src/api.ts`：`LandingAnalysis` 增加 `logo` 字段；`mediaImages` 入参增加 `logo`。
  - `frontend/src/pages/MaterialCreation.tsx`：分析结论 `ResultView` 新增「⑨ 品牌 Logo」区块——展示抓取的 logo、提供「使用抓取到的 Logo 合成图片」开关（默认开启）、以及「上传本地 Logo」按钮（复用 `api.uploadAsset`）；选中的 logo 经 `selectedLogo` 传入 `MediaAdStudio`。
  - `frontend/src/pages/MediaAdStudio.tsx`：接收 `selectedLogo`，在「生成推广图片」时随请求携带。
  - `frontend/src/styles.css`：新增 `.la-logo` / `.logo-preview` / `.logo-img` / `.logo-toggle` / `.logo-upload` 等样式。

**验证**
- 单元：`extract_logo` 正确优先抓取 logo 图、跳过空与 data: URI；`render_ad_png` 方版与 banner 均能合成 logo 不出错。
- 后端 `py_compile` 通过；前端 `tsc --noEmit` 退出码 0、`npm run build` 通过。
- 端到端：① `POST /api/landing-analysis` 响应含 `logo` 字段；② `POST /api/media-campaign/images` 传 `logo=''` 与 `logo='/files/不存在'` 均优雅出图；③ 上传真实 PNG → 返回 `/files/...` → 生成图片成功，像素校验确认 logo 已落到图片右上角。

## V4.28 大模型配置：修复厂商下拉为空 + 补齐 17 家主流厂商

**需求**
- 「大模型配置 → 添加大模型」弹窗中，厂商下拉框无法选择、且不显示任何可选项；要求修复，并把主流大模型厂商（GPT / Claude / Gemini / Grok / Command R / Llama4 / Mistral / Gemma / 通义千问 / Kimi / DeepSeek / GLM / 文心一言 / MiniMax / 豆包 / 腾讯混元 / 百川大模型）显示在下拉选项中。
- 配置时按每家厂商的要求显示必要的输入字段；现有设计（名称 / 模型版本 / 用途 / Base URL / API Key / 厂商专属附加字段）已覆盖，缺失则补充。

**根因**
- 弹窗用原生 `<select>` + `<optgroup>` 渲染厂商列表；在弹窗/内嵌 webview 中，原生 select 下拉常被裁剪或不弹出，导致用户看不到、也点不开选项（数据本身正常：接口始终返回 60+ 厂商）。

**交付**
- 目录补全（后端 `backend/llm_catalog.py`）：
  - 新增 `Llama 4（Meta）`、`Gemma（Google 开放权重）` 两个厂商（均为 OpenAI 兼容，标注其开放权重托管方式）。
  - 新增 `MAINSTREAM_KEYS` 集合（上述 17 家），`get_all_presets()` / `get_presets()` 在返回时统一注入 `mainstream` 标记；现有 15 家（OpenAI/Anthropic/Gemini/xAI/Cohere/Mistral/通义千问/Kimi/DeepSeek/GLM/文心一言/MiniMax/豆包/腾讯混元/百川）已含在内。
  - `backend/routers.py` 的 `/api/settings/models/presets` 输出新增 `mainstream` 字段。
- 前端下拉改造（`frontend/src/pages/LLMSettings.tsx`）：
  - 用自定义浮层下拉 `ProviderSelect` 替代原生 `<select>`：绝对定位浮层渲染，保证在弹窗内一定可见、可点选；支持关键词搜索；分组为「★ 主流大模型（推荐）」置顶 + 文本大模型（其他）+ 文生图 + 文生视频。
  - `load()` 将 `api.models()` 与 `api.modelPresetsAll()` 解耦，任一处失败都不会清空厂商候选列表。
  - `frontend/src/api.ts`：`ModelPreset` 接口增加 `mainstream?: boolean`。
  - `frontend/src/styles.css`：新增 `.provider-select / .ps-trigger / .ps-pop / .ps-search / .ps-list / .ps-group / .ps-opt / .ps-proto / .ps-empty` 等样式。

**验证**
- 后端 `py_compile` 通过；`get_all_presets()` 返回 62 家，其中 `mainstream=True` 17 家，且 17 家关键厂商全部存在。
- 认证调用 `GET /api/settings/models/presets?usage=all` 返回 62 条，每条均含 `mainstream` 与 `modality`，17 家主流标记正确。
- 前端 `tsc --noEmit` 退出码 0、`npm run build` 通过（48 模块）。

## V4.29 推广图中文乱码（tofu 方块）根治

**发布日期**：2026-11-06

**需求**
- 生成的推广图片中，中文文案被渲染成一排排空方块（豆腐块/tofu），英文（Apple / Genius Bar / Trade In）正常。要求排查主因、给出修复方案，并避免今后再次出现此类乱码文案。

**根因**
- `backend/imaging.py` 的字体候选列表硬编码了 macOS 字体路径（STHeiti / Hiragino / PingFang 等）。在 macOS 本机这些字体存在、中文可正常渲染；但部署到 Linux 服务器（生产环境）后，这些路径全部不存在，最终回退到 `ImageFont.load_default()`——该内置字体仅含基础拉丁字母，于是所有中文字符被渲染成空方块。
- 该失败是**静默**的：既不报错，也无告警，图片照常产出，导致乱码文案上线才被发现。

**交付**
- 动态字体发现：保留常见 macOS/Linux 路径，新增 fontconfig `fc-list` 兜底发现系统字体；候选顺序将 CJK 字体排在拉丁字体之前，确保中文优先命中 CJK 字体。
- 逐字符字体回退：`_draw_text()` 对每个字符独立挑选能渲染它的字体，中英文混排不再串字体、不再出方块。
- 精确缺字检测：引入 `fontTools` 读取字体字符映射（cmap）判断字符是否真实存在；内置默认字体仅视为含 ASCII。缺字字符被**安全跳过**（而非渲染成方块），并打出 `WARNING` 明确指出被跳过的字符，便于定位与避免静默乱码。
- `backend/requirements.txt` 增加 `fonttools>=4.38` 依赖。

**验证**
- 正常环境（含 CJK 字体）：1080x1920 / 1200x628 / 320x50 三种尺寸混合中英文渲染均无方块，中文完整可读。
- 退化环境 A（部署机零字体 → 仅 `load_default`）：原 bug 场景，现不再出方块，改为跳过中文并输出 `WARNING` 指明缺失字符（如「苹果以旧换新」「天才吧」等）。
- 退化环境 B（部署机仅有拉丁字体如 DejaVu/Arial Bold）：CJK 字符经 cmap 检测确认缺字后同样被跳过并告警，杜绝静默豆腐块。
- 字形检测准确性：STHeiti 对 `中` → True；默认字体对 `中` → False；默认字体对 `A` → True。
- `backend/imaging.py` `py_compile` 通过；已提交并推送 `e00390b`。

**线上仍需运维配合**
- 若部署服务器（Linux）本身未安装任何 CJK 字体，代码会跳过中文而非显示方块——要真正显示中文，需在部署机安装 CJK 字体（如 `apt-get install -y fonts-noto-cjk` 或 `fonts-wqy-zenhei`），重启后端即可被自动发现。

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

## V4.30 系统设置新增「新版通知」：版本发布公告

**发布日期**：2026-11-06

**需求**
- 每次有新版本发布时，在系统内展示版本更新的内容；更新通知入口放在系统设置菜单栏，新增「新版通知」一项。
- 每次发版时整理更新内容，并同步到 git。

**根因**
- 此前版本更新内容只沉淀在仓库 `CHANGELOG.md`，用户无法在系统里直接看到，需要主动去翻文档，发版信息触达不到使用方。

**交付**
- 后端 `release_notes.py`：解析 `CHANGELOG.md` 的 `## Vx.y 标题` 段落为结构化数组（含版本号、标题、发布日期、正文），按版本号降序返回最新在前；带 mtime 缓存，文件变更自动刷新。
- 后端 `routers.py` 新增 `GET /api/system/release-notes`（任意已登录角色可访问），单一数据源即 `CHANGELOG.md`，无需额外维护一份公告数据。
- 前端 `App.tsx`：在「系统设置」分组下新增「新版通知」导航项（bell 图标）；并以红点 badge 提示存在未读新版本（基于 localStorage 记录上次已读版本号）。
- 前端 `pages/ReleaseNotes.tsx`：版本发布列表页，最新版本置顶并标注「新」；正文用轻量 Markdown 渲染（标题/加粗/列表/分段），纯前端实现无额外依赖。
- 发版工作流固化：今后每次发版，只需在 `CHANGELOG.md` 追加一条 `## Vx.y 标题` 段落（可含 `**发布日期**：YYYY-MM-DD`），「新版通知」即自动展示，并提交推送 git 即完成同步。

**验证**
- `python3 release_notes.py` 解析正确，`latest=V4.30`，按版本号降序、最新在前。
- `GET /api/system/release-notes` 返回 `{latest, notes[]}`，`notes[0].version == V4.30`。
- 前端「系统设置 → 新版通知」可打开列表，最新版本带「新」标记；存在未读版本时菜单项显示红点，点击查看后红点消失。
- `backend/imaging.py`、`backend/routers.py` `py_compile` 通过；前端 `tsc`/`build` 通过。

**线上运维配合**
- 无。公告内容完全来自 `CHANGELOG.md`，发版即更新、提交即同步，无需额外配置。

## V4.31 大模型配置：移除「大模型名称」选择，改为「接口协议」直配

**发布日期**：2026-11-06

**需求**
- 在「大模型配置」模块中，添加 / 编辑大模型时，删除「大模型（厂商）选项」，不再强制选择大模型名称；
  用户直接按填入的配置（模型版本 / Base URL / API Key 等）发起测试与保存。

**根因**
- 原「添加大模型」弹窗第一步强制在 62 个厂商目录里挑一个厂商名称，才能继续填写 Key / Model；
  但多数用户（自建 GPU / vLLM / 第三方网关 / 国内模型）只是想直接填接口信息，厂商选择既多余又阻碍快速接入。

**交付**
- 前端 `LLMSettings.tsx`：用紧凑的「接口协议」选择器替换原「厂商大模型」下拉（`ProtocolSelect`），选项仅 7 种协议：
  OpenAI 兼容 / Anthropic / Gemini / 文生图·OpenAI / 文生图·阿里 DashScope / 文生图·通用 / 文生视频·通用。
  选中协议自动带出默认 Base URL 与常见 Model 建议，模型版本（Model）由用户自由填写。
- ModelConfig.provider 字段改为直接存储协议串（如 openai / gemini / openai-image）。
- 验证时显式传递 `protocol`，后端 `test_llm_connection()` 据此选对鉴权方式。
- 后端 `llm_catalog.py` 新增 `_resolve_protocol()`：provider 若为协议串原样返回；否则回退到厂商目录解析（兼容旧数据）；
  并用于 `get_llm` / `get_image` / `test_llm_connection`，确保运行时与测试对新旧配置都正确。
- 移除原「厂商标定地址不可修改」「厂商专属文档链接」等厂商耦合逻辑；通用图像/视频协议的「自定义端点」字段保留。

**验证**
- 后端 `_resolve_protocol` 单测：协议串（openai/anthropic/gemini/openai-image/generic-image/dashscope-maas-image/generic-video）原样返回；
  旧厂商 key（google→gemini、dalle3→openai-image、wanx→generic-image）正确回退。
- 前端 `tsc --noEmit` 与 `npm run build` 通过（49 模块）。
- `llm_catalog.py` / `providers.py` / `routers.py` `py_compile` 通过。

**线上运维配合**
- 无。旧配置（provider 存厂商 key）仍可正常解析与运行，无需迁移。

## V4.32 修复「大模型配置不显示」+ 千问 qwen-plus 对接

**发布日期**：2026-11-06

**需求**
- 排查：在「大模型配置」中添加并测试成功的大模型，列表却无法显示。
- 对接：千问文本大模型 qwen-plus，URL `https://llm-nqw1vl6mhnuxv7d5.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`，Key `sk-80af895cd9f2410d82fd65b8d735ef25`。

**根因（列表不显示）**
- `schemas.ModelConfigOut` 用 `mode="before"` 校验器在 `usages IS NULL` 时回填 `usages`；但该校验器仅在入参为 dict 时生效，对 ORM 对象（FastAPI `from_attributes` 路径）不触发。
- 旧数据（早期 UI 写入）`usages` 列为 NULL，导致 `/api/settings/models` 列表接口整体 500，前端 `load()` 捕获异常后列表恒为空——表现为"测试成功却看不到模型"。
- 测试接口 `/settings/models/test` 不序列化 `ModelConfigOut`，故不受此影响，解释了"测试成功、列表不显示"的割裂现象。

**交付**
- `schemas.ModelConfigOut`：`usages` 改为 `Optional[List[str]]`，校验器改为 `mode="after"`，始终保证返回 list（旧数据由 `usage` 推导），彻底消除 `usages=None` 引起的序列化 500。
- 数据修正：原 2 条脏数据（provider 存中文名"千问大模型"、URL 为旧 `dashscope-intl` 国际版、params 为 JSON 字符串、usages 为 NULL）合并并纠正为 1 条：
  - name=千问文本大模型，provider=openai（compatible-mode=OpenAI 兼容），model=qwen-plus，
  - base_url=新 MaaS 地址，usages=\[analysis, copy\]，params={}（JSON 对象），is_active=true。
- 实测连通：`test_llm_connection` 对 qwen-plus 返回 `ok=True`（延迟 ~595ms），对接生效。

**验证**
- `ModelConfigOut.model_validate(orm, from_attributes=True)` 对两条旧脏数据均通过，列表接口不再 500。
- 连通测试 `ok=True`，确认新 MaaS 端点与密钥可用。
- `schemas.py` `py_compile` 通过。

**线上运维配合**
- 无。代码修复后任意 `usages` 缺失的配置都能正常显示；新 MaaS 地址与密钥已写入 DB，部署机 `git pull` 后重启后端即可在「大模型配置」看到千问文本大模型。

## V4.33 大模型配置：千问 MaaS 预设快捷项 + 测试已保存配置 + 防重复添加

**发布日期**：2026-11-09

**需求**
- 把「千问文本大模型」在 UI 里做成像 GPT / Claude 那样的预设快捷选项：选中即带出专属 MaaS 地址与 `qwen-plus`，只需补填 Key 即可。
- 增加一个「测试某个已保存配置」的按钮：无需重新填写/保存，直接对列表中的落库配置发起一次真实连通测试。
- 同一大模型配置只能添加一次；若检测到重复添加，提醒「已添加」。

**交付**
- 后端 `llm_catalog.py`：新增 `qwen-maas` 预设（协议 `openai`，默认 Base URL 为 `https://llm-nqw1vl6mhnuxv7d5.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`，`model_placeholder=qwen-plus`），并加入 `MAINSTREAM_KEYS`，使其在「预设快捷选项」中默认置顶展示。
- 前端 `LLMSettings.tsx`：
  - 弹窗新增「预设快捷选项」chips（`quickPresets`），按当前模态过滤主流/部署；点击 `onPickPreset` 即带出该预设的 Base URL、建议 Model（`qwen-plus`）、默认用途，体验等同直接选 GPT / Claude。
  - `ProtocolSelect` 在 `form.provider` 为预设 key（如 `qwen-maas`）时回退到 `allPresets` 显示预设名，避免显示空白。
  - 列表每行新增「测试」按钮，打开只读摘要弹窗，基于落库值（含保存的 API Key）直接调用 `/api/settings/models/test` 发起最小真实调用，不改任何配置。
- 后端 `routers.py`：新增 `_norm_model_key`（provider 经 `_resolve_protocol` 统一为协议串 + 链接去尾斜杠小写 + 模型小写）与 `_dup_model_config`；在 `create_model` / `update_model` 中检测 `(协议, 链接, 模型)` 完全相同的配置，命中即返回 `409 已添加`。
- 前端 `save()`：捕获到含「已添加」的异常时，给出明确提醒「已添加：该大模型配置已存在，请勿重复添加。」，而非笼统的「保存失败」。

**验证**
- `_resolve_protocol('qwen-maas') == 'openai'`，因此经预设添加的千问 MaaS 配置与既有的 `provider=openai` 同地址同模型配置会被正确判为重复，杜绝二次添加。
- `_norm_model_key` 单测：`qwen-maas` + MaaS URL（带/不带尾斜杠） + `qwen-plus` 归一后与 `openai` + 同 URL + `qwen-plus` 完全一致（判重），与 `gpt-4o` 不一致（不误判）。
- 前端 `tsc --noEmit` 通过；后端 `routers.py` / `llm_catalog.py` `py_compile` 通过。

**线上运维配合**
- 无。部署机 `git pull` 后重启后端即可生效；既有千问配置不受影响，若再次以预设方式添加同地址同模型会被「已添加」拦截。

## V4.34 大模型连通性健康：每日自动测试 + 状态/log + 测试成功优先选配

**发布日期**：2026-11-09

**需求**
- 每天针对**已保存**的大模型自动做一次 API 接口连通性测试，测试完反馈状态（成功 / 失败）。
- 若测试失败，显示最后一次测试的 log，主要展示获取到的 **HTTP code** 与**服务器返回的错误信息**。
- 同一用途保存了多个大模型、且其中有测试成功的，系统功能默认使用「测试成功」的那条。
  （需求原文「同一种用户」按「同一种用途 usage」理解实现，见下方说明。）

**交付**
- 数据层 `models.py` / `migrations.py`：`ModelConfig` 新增 `last_test_ok`(NULL/True/False)、`last_test_at`、`last_test_http_code`、`last_test_error`、`last_test_latency_ms`；新增 `system_state` KV 表存放每日执行日期戳。启动时由 `ensure_schema()` 自动 `ALTER TABLE ADD COLUMN`，旧库无需手工迁移。
- 测试链路 `llm_catalog.py`：`_classify_error` 与 `test_llm_connection` 统一补齐 `http_status`（真实 HTTP code；网络层失败为 0），供落库与展示。
- 新模块 `model_health.py`：
  - `test_one()` 用落库值发起真实最小调用并写回状态；失败时把「HTTP Code + 错误类型 + 服务器返回的错误信息 + 中文诊断 + 文档」拼成 `last_test_error` log。
  - `run_all()` 串行测试全部配置并返回汇总（total / ok / failed / 逐条结果）。
  - 后台协程 `_daily_loop()`：FastAPI startup 启动、shutdown 取消，**每天只跑一次**（`system_state` 原子条件 UPDATE 抢占日期戳，天然兼容多 worker）；支持 `LLM_DAILY_TEST_HOUR`（默认 3 点）与 `LLM_DAILY_TEST_ENABLED`（默认开）；进程在目标时刻之后启动会当天补跑。无新增依赖。
- 接口 `routers.py`：`GET /settings/models/health`（运行信息）、`POST /settings/models/test-all`（手动全量测试，admin）、`POST /settings/models/{id}/test`（按 id 测试并写回状态，不依赖前端回填 Key）；`GET /settings/models` 额外返回 `in_use`（是否为该用途当前实际生效的配置）。
- 选配 `providers.py`：新增 `_pick_config()` / `effective_config_ids()`。同一用途候选按「**测试成功 > 激活 > id 最大**」优先级挑选；全部未测试或全部失败时完全退回原逻辑（仅激活、取 id 最大），不破坏既有部署；`is_active` 不再单独决定谁生效。
- 前端 `api.ts` / `LLMSettings.tsx` / `styles.css`：
  - 卡片顶部显示每日自动测试开关/执行时刻/上次自动测试时间，新增「⟳ 立即测试全部」按钮与全量测试汇总。
  - 列表新增「连通状态」列：未测试 / 成功（HTTP code + 延迟 + 时间）/ 失败（HTTP code + 查看日志 + 时间）；状态列新增「系统采用」标记。
  - 失败可打开 log 弹窗，集中展示 HTTP Code、服务器返回的错误信息、诊断、请求链接与测试时间，并支持「重新测试该配置」。
  - 「保存并测试」「测试已保存配置」改为调用按 id 的测试接口，使状态写回并即时刷新列表。
  - `last_test_at` 序列化补 `+00:00` 时区，避免前端按本地时区显示差 8 小时。

**验证**
- 后端全量 `py_compile` 通过；前端 `tsc --noEmit` 与 `vite build` 均通过。
- DB 副本集成测试：自动补列 5 个字段 + 建 `system_state` 表成功；全量测试 4 条（3 成功 1 失败），失败条 `last_test_http_code=401` 且 log 含 HTTP Code 与服务器返回的 `{"error":...Invalid API key...}`。
- 选配 5 场景实测：A 失败 / B 失败 / C 成功 → 采用 C；全部失败 → 退回激活；全部未测试 → 退回激活；多条成功 → 优先激活；激活配置缺 Key 但 C 成功 → 采用 C。
- TestClient HTTP 实测：`/health`、`/models`、`/presets`、`/test-all`、`/{id}/test` 均 200，不存在的 id 返回 404；状态、`http_status`、`in_use`、log 均正确返回。
- 每日调度：首次抢占成功、同日再次抢占失败（不重复跑）、跨天补跑判定正确。

**运维配置（可选环境变量）**
- `LLM_DAILY_TEST_ENABLED=0` 关闭每日自动测试（手动测试仍可用）。
- `LLM_DAILY_TEST_HOUR=3` 每天执行时刻（本地时间，0–23，默认 3）；当天该时刻之后启动会补跑一次。

**说明**
- 「同一种用户」按「同一种用途（usage：analysis / copy / image / video）」理解；若确需按用户维度隔离配置，需另行设计多租户模型归属字段。
- 部署机 `git pull` 后重启后端即自动补列并启动调度；重启后约 10 秒进行当天首次判定。

## V4.35 素材提示词：全量统一目录 + 双维度分类 + 优秀提示词总结库

**发布日期**：2026-11-09

**需求**
1. 把「素材创作」模块涉及的**所有提示词**全部展示、整理到「素材提示词」子模块。
2. 按「功能类型」「使用类型」两套维度分门别类管理与区分，方便今后修改与查阅。
3. 针对直接影响最终结果的「广告推广文案」「广告推广图片」建立**提示词总结库**，收集整理市面优秀提示词，可按**类型 / 风格 / 场景 / 覆盖对象**等维度选择系统默认的提示词类型。

**根因（改造前）**
- 提示词散落 4 处：`services.py` 注册表 10 条、`presets.py` 预设库 62 条、`media_ad.py` 硬编码的文案/图片提示词、前端 `materialPresets.ts` 副本。
- 「素材提示词」页只过滤 `module='素材创作（落地页分析）'`，仅展示 5 条；62 条预设与广告文案/图片提示词**完全不可见、不可改**。
- 只有单一 `category` 字段，没有功能类型 / 使用类型维度；也不存在可选默认模板的机制。

**交付**

*统一目录与分类（需求 1 + 2）*
- 新模块 `backend/prompt_catalog.py`：定义 8 个**功能类型**（落地页分析 / 广告推广文案 / 广告推广图片 / 视频分镜 / 创意方向库 / 内容风格库 / 配色方案库 / 通用素材生产）与 5 个**使用类型**（系统提示词 / 用户提示词 / 输出约束 / 提示词片段 / 生成指令），并给既有 10 条提示词逐条打标（不改内容）。
- 把 `media_ad.py` 里硬编码的 3 条提示词抽成可管理模板：`media_copy_sys`（广告推广文案主提示词）、`media_context`（分析结论注入）、`media_image_sys`（推广图片文生图背景提示词）。
- 三大预设库 D01–D20 / S01–S26 / C01–C16 共 62 条以 `preset_<编号>` 纳入同一注册表。`PROMPT_REGISTRY` 由 10 条扩为 **75 条**，`seed_prompts()` 启动时自动播种、`sync_prompt_defaults()` 回填元数据。
- `PromptConfig` 新增 `func_type` / `usage_type` 两列，`migrations.ensure_schema()` 自动补列，旧库无需手工迁移。
- 预设片段编辑后经 `load_preset_overrides(db)` 覆盖 `presets.build_directives()` 的注入文本，编辑真正影响生成（此前只读）。

*优秀提示词总结库（需求 3）*
- `prompt_catalog.BEST_PRACTICES` 收录 **20 条**业界公认框架的成体系提示词：文案 AIDA / PAS / BAB / FAB / 4P / Hook-Story-Offer / 社会证明 / 稀缺紧迫 / Before-After / 本地化；图片 Hero Shot / Lifestyle / 分屏对比 / UGC / 极简留白 / 数据权威 / 大促氛围 / 情绪人像 / 3D CGI / 本地文化。
- 每条带四维标签（类型 / 风格 / 场景 / 覆盖对象，各 8 个选项）+ 适用平台 + 方法论来源 + 摘要 + 完整提示词正文，支持四维交集筛选与关键词检索。
- 「设为系统默认」把选中模板正文写入对应系统提示词（`media_copy_sys` / `media_image_sys`），生成链路经 `get_prompt()` 读取 —— **保存即生效，无需重启**；`system_state` 记录当前选择，`customized` 标记可识别管理员后续在目录里的手改。
- 模板采用 `[[NAME]]` 安全占位符（不用 `str.format`，避免提示词正文里的 JSON 花括号被误解析）；模板不含结构占位符时，系统自动追加**输出契约块**（字段结构 / 字数红线 / 语言 / no-text 等硬约束），保证更换模板不丢失底线规则。
- `media_ad.py` 三处运行时接入改由 `get_prompt()` 读取；`_analysis_context` / `_media_image_prompt` 保留无 db 的内置兜底。

*API 与前端*
- `GET /api/settings/prompts` 支持 `scope` / `func_type` / `usage_type` / `module` 筛选；菜单对 editor 可见，因此**读取放宽为所有已登录角色**，写操作仍限 admin。
- 新增 `GET /api/settings/prompt-taxonomy`（两套维度 + 各类计数）、`GET /api/settings/prompt-library`（四维筛选 + 当前默认）、`PUT /api/settings/prompt-defaults`（设为默认 / 恢复内置）。
- `MaterialPromptLibrary.tsx` 重写为两大视图：**全量提示词目录**（分类 chips + 使用类型筛选 + 关键词检索 + 分组折叠 + 编辑/停用/恢复默认，编辑弹窗可调整双维度）、**优秀提示词总结库**（当前系统默认卡片 + 类别切换 + 四维筛选 + 模板卡片 + 正文弹窗 + 一键设为默认）。
- `Prompts.tsx`（系统设置 → 提示词管理）改用 `scope=core`，仍只显示 13 条系统级提示词，避免被 62 条预设淹没。
- `App.tsx` 更新菜单描述并传入 `isAdmin`：非管理员为只读视图，不显示写操作按钮。

**验证**
- 后端全量 `py_compile` 通过；`import main` 无循环导入，注册表 75 条分类统计正确（6/2/2/1/20/26/16/2）。
- 前端 `tsc --noEmit` 与 `vite build` 均通过。
- DB 副本 TestClient 实测：全量目录 200 且 75 条（含 `media_copy_sys` / `media_image_sys` / `media_context` / `preset_D01`…）；`scope=core` 13 条无预设；`func_type=ad_copy` 2 条、`usage_type=fragment` 62 条；分类总览计数一致。
- 总结库筛选：`ad_copy` 10 条；`痛点唤醒 + 情绪张力` → `copy_pas`；`大促节点` → `copy_scarcity` + `img_promo`。
- 「设为默认 → 生成链路生效」端到端：设 `copy_pas` 后 `get_prompt(media_copy_sys)` 含 PAS、合成提示词自动补出输出契约；设 `img_hero` 后实际文生图提示词含 Hero Shot + no-text 契约、无残留占位符；分析结论注入读自 `media_context`。恢复内置默认后回到内置模板。
- 权限：editor 三个 GET 均 200，两个 PUT 均 403。
- 预设编辑：`PUT /prompts/preset_D01` 后 `load_preset_overrides` 生效，`build_directives(D01)` 的 `extra_prompt` 含自定义指令。

**说明 / 默认约定**
- 总结库内容按「公开营销方法论 + 合规写作准则」整理为可直接投放的提示词模板，非逐字复制任何厂商内部提示词；涉及折扣、倒计时、评分与案例均要求**只用落地页真实出现的信息**，避免生成违规文案。
- 设为默认后仍可在「全量提示词目录」里继续手改正文，此时总结库卡片会标注「已在目录中自定义」。
- 部署机 `git pull` 后重启后端：自动补 `func_type` / `usage_type` 列、播种 65 条新提示词；既有提示词正文不受影响（仅元数据同步）。
- 「提示词总结库」当前为内置精选集（20 条）；若后续需要运营自行增补条目，可扩展为独立数据表，现有 API 结构无需改动。

## V4.36 推广图片查阅 / 下载 + 新增「素材历史」子模块

**发布日期**：2026-11-09

**需求**
1. 「素材创作」里已生成的推广图片可以**点击放大查阅**、**点击下载**；既能**一键打包全部下载**，也能**勾选某几张下载**。
2. 「素材创作平台」一级菜单新增「素材历史」子模块，归档**已分析整理的网站 + 已生成的文案与素材**，供反复查阅与再下载，节约时间、降低重复生成。
3. 「素材历史」支持**批量删除**历史信息。

**根因（改造前）**
- `MediaAdStudio.tsx` Step 3 只有缩略图 `<img>`，无任何放大、下载、勾选能力。
- 「素材创作」的分析 / 文案 / 图片**完全不落库**（`landing_analysis` 注释明确写「结果不落库」），图片仅写入 `uploads/`，刷新页面即无法找回；因此不存在可查阅的「历史」。
- `generate_media_images` 的文件名由 `hash((placement, size, headline, sub))` 决定：**同一文案重复生成会得到完全相同的文件名并直接覆盖旧 PNG**，即使落库也会让旧会话的图片被无声替换。

**交付**

*数据层*
- 新增 `creation_history` 表（`models.py`，启动时 `create_all` 自动建表，旧库无需手工迁移）：一次创作会话 = 落地页分析 + 广告文案 + 推广图片 + 风格 / 模型信息 + 归属人 + 时间戳，按步骤增量写回。
- 新增 `backend/creation_history.py`：统一序列化（UTC 时区显式化，避免前端显示差 8 小时）、标题 / 站点名推断、uploads 文件名安全解析、ZIP 打包（图片 + 文案 TXT/JSON + 分析 TXT/JSON + 生成信息 + 清单）、删除后孤儿图片清理。
- `media_ad.py` 图片文件名加入随机后缀，两次同文案生成得到不同文件且旧图保留，历史可追溯。

*API*（`routers.py`）
- `GET /api/media-files/download?file=` 单张图片下载；`GET /api/media-files/zip?files=` 任意图片列表打包（一键全部 / 勾选几张共用）。
- `POST /api/creation-history` 建会话；`GET /api/creation-history` 列表（关键词 / 平台筛选 + 分页）；`GET /api/creation-history/{id}` 详情；`PUT /api/creation-history/{id}` 增量写回（图片默认**追加**，保留每次重新生成的产物，单会话上限 80 张）。
- `DELETE /api/creation-history`（body `{ids}`）批量删除并清理不再被引用的磁盘图片；`GET /api/creation-history/{id}/export.zip` 整条再下载；`GET /api/creation-history/export?ids=` 批量打包；`GET /api/creation-history/{id}/copy.txt` 单独下载文案。
- 下载类接口用 query token（浏览器 `<a>` 无法带 Header），在 `auth_guard` 验签之外额外校验角色；`safe_image_path` 只接受纯文件名并做 realpath 前缀校验，阻断 `../` 与绝对路径穿越。

*前端*
- `MediaAdStudio.tsx` Step 3：图片点击放大（lightbox，ESC / ← → / 点遮罩关闭，可直接下载当前图）、每张卡片「下载」按钮、复选框多选、工具条「一键打包全部」与「打包所选（N）」；文案 / 图片生成后增量写回历史并显示归档提示。
- `MaterialCreation.tsx`：分析完成即创建历史会话并传递 `historyId`；支持从「素材历史」**复用分析继续创作**（sessionStorage + 自定义事件握手），跳过重复抓站与大模型推理，直接进入推广设置。
- 新增 `MaterialHistory.tsx`：搜索 / 平台筛选 / 加载更多、卡片缩略图、展开查看 8 项分析结论与广告文案、图片放大与单张下载、整条打包（含文案与分析）、仅打包图片、批量打包、批量删除（二次确认并提示将清理的文件数）、单条删除、「复用分析继续创作」。
- `App.tsx` 新增 `history` Tab / 菜单项 / 图标 / 权限 / 页面渲染；`styles.css` 补齐工具条、lightbox 与历史页样式。

**验证**
- 后端全量 `py_compile` 通过；新路由 7 条全部注册；`safe_image_path` 对 `../etc/passwd`、`/etc/hosts` 均返回 `None`。
- DB 副本 TestClient 端到端：建会话 → 写回文案 / 图片 → 列表 / 搜索 / 详情 → 单张下载（`Content-Disposition: attachment`）→ 任意图片 ZIP（含 `清单.json`）→ 整条 ZIP（7 个条目，文案含品牌名、分析含行业）→ 文案 TXT → 双记录批量导出（含 `历史清单.json`）→ 批量删除（2 条记录 + 2 个磁盘文件清理）。
- 权限：无 token / 非法 token 均 401；viewer 下载、读历史、删历史均 403。
- 文件名唯一性：同文案连续生成两次得到不同文件名，两个文件均存在，旧图不再被覆盖。
- 前端 `tsc --noEmit` 与 `vite build` 均通过（50 模块，298 kB JS / 59.6 kB CSS）。

**说明 / 默认约定**
- 「素材历史」与「素材创作」一致，仅投放执行及以上角色可见；只读账号不可访问，也不允许通过直链下载。
- 历史写入失败不会阻断分析与生成主流程（前端捕获后仅提示），避免本地 DB 异常影响出图。
- 一次会话内反复「重新生成」的图片会**累积**归档（上限 80 张），方便回看每一版；删除历史时才统一清理磁盘文件。
- 部署机 `git pull` 后重启后端即自动建表；此前的分析与图片因原本未落库，不会自动补录为历史，新产生的会话才开始归档。

## V4.37 精简「素材管理」模块 + 新版通知结构化发版流程

**发布日期**：2026-11-09
**变更类型**：删除 / 优化 / 新增 / 发布
**涉及模块**：素材管理、素材创作平台、系统设置、新版通知、发版流程
**变更摘要**：整体下线「素材管理」的四个子模块与系统设置中的「提示词管理」，清理对应的前后端代码、接口、数据模型与失效提示词；同时把「新版通知」升级为按模块 / 变更类型结构化发布的版本内容，并新增发版前校验脚本与 pre-push 钩子，保证每次 git 更新前都整理并发布对应的版本通知。

**更新要点**
- 下线「素材管理」的四个子模块与系统设置中的「提示词管理」，清理相关页面、接口与数据模型。
- 新版通知改为按模块 / 变更类型结构化发布，每次发版前整理更新内容并校验。
- 提示词统一由「素材创作平台 → 素材提示词」管理。

**本次优化与更改的功能 / 模块**
- 【删除】素材管理 / 创作工作台：移除 `Workspace.tsx`、旧分析报告 / 优化 / 素材墙相关页面与组件，菜单中不再出现「素材管理」一级分组，默认落地页改为「素材创作」。
- 【删除】素材管理 / 批量生成：移除 `Batch.tsx` 与 `batch.py`，删除 CSV 解析、异步任务、任务轮询、批量导出相关接口（`/api/batch/*`、`/api/jobs*`）。
- 【删除】素材管理 / 素材库：移除 `Library.tsx`、版本链 / A-B 对比 / 审阅流组件，删除 `/api/campaigns*`、`/api/materials*`、`/api/export/*` 等 Campaign 生产链路接口。
- 【删除】素材管理 / 规格库：移除 `Specs.tsx` 与 `specs_data.py`，删除 `/api/platform-specs` 维护接口与启动时规格播种；「素材创作」使用的媒体平台规格仍由 `media_platforms.py` 独立提供。
- 【删除】系统设置 / 提示词管理：移除 `Prompts.tsx` 菜单项与页面；提示词统一由「素材创作平台 → 素材提示词」管理，`/api/settings/prompts` 等接口保留并去掉 `scope=core` 旧参数。
- 【优化】素材创作平台 / 菜单与权限：仅保留「素材创作 / 素材提示词 / 素材历史」三个子模块；「新版通知」对所有登录角色开放（含只读账号），未读新版本继续以菜单红点提示；只读账号提示文案同步更新。
- 【优化】素材创作平台 / 提示词目录：移除只服务旧模块的 5 条失效系统提示词（`site_analysis` / `angle` / `copy` / `video` / `image`）及其分类维度，启动时清理库内残留行；目录由 75 条精简为 70 条，仍按功能类型 / 使用类型分类、支持优秀提示词总结库与系统默认。
- 【优化】后端 / 代码精简：`services.py` 仅保留提示词注册表、落地页抓取与 8 字段分析；`routers.py` 保留 40 条有效接口（从原 60+ 条降至 40 条）；`models.py` 移除 8 个旧业务表；`schemas.py` 移除 20 个旧请求模型；删除 `render.py` / `validation.py` / `report.py` / `optimize.py` / `creative.py` / `insight.py`，把仍使用的 `fit_text` 抽为 `text_utils.py`；清理 267 条无用 CSS 规则与 `imageio-ffmpeg` 依赖。
- 【优化】新版通知 / 版本内容：`release_notes.py` 支持解析「发布日期 / 变更类型 / 涉及模块 / 变更摘要 / 本次优化与更改的功能 / 影响范围 / 验证」结构化字段；历史版本自动降级为「摘要要点 + 完整发版记录」，不丢内容。
- 【优化】新版通知 / 查阅体验：`ReleaseNotes.tsx` 新增版本总数与结构化版本统计、关键词搜索、按涉及模块 / 变更类型筛选、变更卡片按类型着色、影响范围与验证结果分区展示、完整发版记录可折叠查看。
- 【新增】发版流程 / 发版前校验：`scripts/prepare_release.py` 提供 `--draft`（按 git 变更文件自动归纳涉及模块并生成版本通知骨架）、`--write`（写入 CHANGELOG）、`--check`（校验结构化字段完整性、模块覆盖、CHANGELOG 是否随代码改动同步更新）；`scripts/hooks/pre-push` + `scripts/install_hooks.sh` 在 push 前自动执行校验，可用 `SKIP_RELEASE_CHECK=1` 应急跳过。
- 【发布】新版通知 / V4.37：本条即为按新规范整理并发布的版本内容，发版前由校验脚本核对模块覆盖后再同步 git。

**影响范围**
- 前端：一级菜单由 3 组缩为 2 组（素材创作平台 / 系统设置），Tab 由 12 个缩为 7 个；删除 7 个页面、3 个组件与 `materialPresets.ts`；`api.ts` 删除 40 个旧接口与 27 个旧类型；`styles.css` 从 1420 行精简至 915 行。
- 后端：删除 8 个 Python 模块与 8 个 ORM 表定义；`/api/analyze`、`/api/generate`、`/api/produce`、`/api/campaigns`、`/api/platform-specs`、`/api/batch/*`、`/api/jobs`、`/api/export/*`、`/api/meta` 等旧接口统一返回 404。
- 数据：旧业务表（campaigns / materials / frameworks / angles / platform_specs / jobs / review_records 等）在历史库中保留但不迁移、不被使用；`prompt_configs` 中 5 条失效提示词在启动时清理；`creation_history` / `model_configs` / `prompt_configs` / `users` / `audit_logs` / `system_state` 完全不受影响。
- 权限：「新版通知」对所有登录角色可读；素材创作、素材提示词、素材历史仍仅 admin / manager / editor 可用；系统设置其余页仍仅 admin 可用。
- 兼容性：旧浏览器收藏的 `#/workspace`、`#/batch`、`#/library`、`#/specs`、`#/prompts` hash 会自动跳转到当前角色可用的首个页面，不会白屏。

**验证**
- 后端全量 `compileall` 通过；`import main` 无循环导入，注册路由 40 条（含 `/api/health`）；版本号升至 4.37.0。
- DB 副本 TestClient 实测：登录 / 鉴权、提示词目录（70 条、旧 5 条无残留）、分类总览、总结库、创意预设、大模型配置、新版通知、素材历史、媒体平台、落地页分析（真实模型与本地兜底）全部 200；9 个已删接口全部 404。
- 启动清理验证：日志输出「已清理下线模块提示词：angle, copy, image, site_analysis, video」，库中残留为 0。
- 权限验证：viewer 可读 `/api/system/release-notes`（200），访问 `/api/creation-history` 被拦截（403）。
- 前端 `tsc --noEmit` 与 `vite build` 均通过（41 模块，229 kB JS / 38 kB CSS），无旧页面、旧接口、旧样式引用残留。
- 发版校验：`prepare_release.py --check` 对本版结构化字段、模块覆盖与 CHANGELOG 同步状态校验通过后才允许 push。

**说明 / 默认约定**
- 自 V4.37 起，每次优化或修改都按「一个版本 = 一条结构化 CHANGELOG 段落」发布；`scripts/prepare_release.py --draft` 会从改动文件自动归纳涉及模块，避免漏写模块总结。
- 历史版本段落保持原样不重写，前端自动降级展示，保证版本记录可追溯。
- 部署机 `git pull` 后重启后端即完成旧提示词清理；旧业务表不删除、不迁移，若确认无需保留可在单独维护窗口手工归档。
- `git` hook 需执行一次 `bash scripts/install_hooks.sh` 安装到本机 `.git/hooks/`（hook 不随仓库同步）；紧急发布可用 `SKIP_RELEASE_CHECK=1 git push` 跳过，但事后须补齐版本通知。

## V4.38 素材创作：创意文案选用 + 跨页面任务不中断

**发布日期**：2026-11-09
**变更类型**：新增 / 优化 / 发布
**涉及模块**：素材创作平台、创意文案、推广图片、素材历史、前端与菜单、后端接口、数据模型、系统设置、发版流程
**变更摘要**：「素材创作」生成广告文案后，可在出图前逐条勾选哪些文案作为创意素材，并按文案组合轮换生成推广图片；同时把整条创作链路升级为跨页面常驻会话，切换其它菜单时任务不中断，可在任意页面查阅实时进度、返回继续调整，刷新或重新登录也能恢复现场。

**更新要点**
- 生成图片前可勾选使用哪些创意文案，并预览每张图对应的文案组合。
- 切换到其它页面时创作任务不中断，可在任意页面查看进度并继续调整。
- 刷新或重新登录可恢复创作现场。
- 新增「素材历史」，可查阅、放大与再次下载已分析网站、文案和图片。

**本次优化与更改的功能 / 模块**
- 【新增】创意文案 / 逐条选用：Step 2 每条文案（含多值字段的每一条标题、描述、正文、CTA）都带勾选框，默认全选；提供「全选 / 清空 / 仅选每组首条」快捷操作与「已选 X / Y 条」计数，勾选状态与文案编辑内容互不干扰。
- 【新增】创意文案 / 组合预览：生成图片前展示由勾选文案拼出的「创意文案组合」卡片（标题 / 副标 / CTA），并说明第 n 张图使用哪一组；未勾选任何文案时禁止出图并给出明确提示，未勾选的文案仍保留在文案库与「素材历史」中。
- 【优化】推广图片 / 按组合出图：`POST /api/media-campaign/images` 新增 `copy_variants`，后端按版位顺序轮换叠加文案；此前所有图片固定使用「每个字段第 1 条」文案，现在每张图可使用不同文案。每张图片回传 `variant` 与 `copy`，结果卡片与放大预览可核对所用文案；不传 `copy_variants` 时完全兼容旧调用。
- 【优化】后端 / 入参防护：`MediaCopyVariant` 请求模型对组合条数上限 40、标题 / 副标 200 字、CTA 60 字做截断，CTA 枚举自动还原为可读文案；`generate_media_images` 同步说明与返回字段更新，版本号升至 4.38.0。
- 【新增】素材历史 / 选用可追溯：历史会话的文案记录新增 `selected_copy` 与 `copy_variants`，导出的 `copy.txt` 增加「本次选用的创意文案」和「图片使用的文案组合（按版位轮换）」两段；图片元数据保留所用组合，便于回溯哪张图用了哪条文案。
- 【新增】前端与菜单 / 跨页面创作会话中枢：新增 `creationSession.ts`，用 `useSyncExternalStore` + `localStorage`（按登录用户隔离）承载分析输入、落地页结论、历史 id、Logo 选择、工作台三步状态、文案与勾选、图片与下载勾选、任务阶段和进度日志；提供任务开始 / 结束 / 失败 / 日志与恢复清洗能力。
- 【优化】前端与菜单 / 常驻挂载：`App.tsx` 不再按 Tab 卸载「素材创作」，切换菜单只隐藏容器，正在进行的落地页分析、文案与图片请求继续执行，结果完整写回；「素材历史 → 复用分析继续创作」的握手在任何页面都能即时生效。新增「新建创作会话」可清空工作台（任务进行中禁用，不影响已归档历史）。
- 【新增】前端与菜单 / 全局创作任务浮窗：`CreationTaskDock.tsx` 在右下角常驻显示任务状态、耗时和图片张数；展开后可查看状态、说明、三阶段里程碑、平台 / 语言 / 选用文案 / 图片 / 历史会话 / 当前步骤统计与最近 5 条进度日志，并支持「查看素材历史」「返回素材创作」。
- 【优化】系统设置 / 会话恢复：切换账号不会串用会话；页面刷新或关闭时正在执行的请求无法续跑，恢复时自动把 `running` 归零并标注「上次任务未完成」，保留中断前的全部分析与产物，可直接继续调整或重试。
- 【优化】前端与菜单 / 登录页：把已下线的「素材库 → 批量 → 审阅协作」链路文案更新为当前的「落地页分析 → 创意文案选用 → 推广图片生成 → 素材历史归档」；任务进行中禁用平台切换、版位选择与「新建创作会话」，避免结果写回错乱。
- 【发布】发版流程 / V4.38：本条按 V4.37 建立的结构化规范整理本次优化与更改的功能和模块，发版前由 `prepare_release.py --check` 校验后再同步 git。

**影响范围**
- 前端：新增 `creationSession.ts`、`CreationTaskDock.tsx`；`MaterialCreation.tsx` / `MediaAdStudio.tsx` 全面改用会话状态，页面级 `useState` 只保留媒体平台与创意预设目录；`api.ts` 增加 `CopyVariant`、`copy_variants` 与图片 `copy` / `variant` 字段；`styles.css` 增加文案勾选、组合预览与任务浮窗样式；`App.tsx` 常驻挂载并按用户绑定会话。
- 后端：`schemas.py` 增加 `MediaCopyVariant` 与 `copy_variants`；`media_ad.py` 按版位轮换文案并回传所用组合；`routers.py` 透传组合；`creation_history.py` 导出文本追加选用记录；`main.py` 版本号 4.38.0。
- 数据：`creation_history.copy_json` 新增两个可选键，`images_json` 图片项新增 `variant` / `copy`；均为增量字段，旧记录不受影响，无需数据库迁移。
- 兼容性：`/api/media-campaign/images` 不传 `copy_variants` 时行为与 V4.37 完全一致；旧浏览器里不存在 V4.38 会话键时按空会话启动。
- 权限：创作会话与任务浮窗仅 admin / manager / editor 可见；只读账号登录后不会挂载创作组件，也不会出现浮窗。

**验证**
- 后端全量 `compileall` 通过；`import main` 正常，版本号 4.38.0。
- DB 副本 TestClient 实测：`copy` 生成 3 条标题；传 3 组文案 + 4 个版位 → 生成 4 张 PNG，组合按 `组合 1 / 2 / 3 / 1` 轮换且每张 `copy` 正确、PNG 真实落盘；不传组合 → 4 张图仍统一用首条文案（旧行为兼容）；超长标题 / 副标 / CTA 被截断为 200 / 200 / 60 字；历史 `copy.txt` 含「本次选用的创意文案」与「图片使用的文案组合」两段；媒体平台、创意预设、素材历史、新版通知、模型配置、提示词目录均 200。
- 前端 `tsc --noEmit` 与 `vite build` 通过（43 模块，246 kB JS / 47.7 kB CSS）；`MaterialCreation` 无组件内业务状态残留，旧 props / 旧接口无引用。
- 会话中枢 Node 单元测试 17 项全通过：任务开始 / 结束 / 日志、里程碑、刷新恢复归零并保留现场、账号隔离、全选与逐条勾选、文案组合轮换、清空勾选后禁止出图、新建会话重置。
- 无头 Chrome 实测：登录页 React 正常挂载；注入登录态与会话快照后，「素材创作」Step 3 图片卡片显示所用文案组合，切到「新版通知」页时创作组件仍常驻（容器 `display:none`）、右下角任务浮窗显示「图片已生成 · 2 张」；展开面板可见三阶段里程碑、选用文案 5/6、历史会话、最近进度与「返回素材创作」。
- 发版校验：`prepare_release.py --check` 校验结构化字段、模块覆盖与 CHANGELOG 同步状态通过后才允许 push。

**说明 / 默认约定**
- 「任务不中断」的作用域是应用内切换菜单：组件常驻挂载，请求继续运行。关闭浏览器或整页刷新会中断网络请求，此时恢复现场并明确标注「上次任务未完成」；如需跨设备 / 跨会话的后台任务，后续可升级为服务端任务队列 + 进度轮询。
- 文案组合按「标题池 / 副标池 / CTA 池」各自按序配对，组合数取最长池长度，上限 40；图片数超过组合数时循环复用，未勾选的文案只留档、不出图。
- 会话快照按登录用户 id 隔离存于浏览器本地，不上传服务端；「新建创作会话」只清本地工作台，已写入「素材历史」的记录与图片文件保持不变。

## V4.39 AI 改造第 1 期：输入与输出可信度（F01 / F02 / F10）

**发布日期**：2026-11-10
**变更类型**：修复 / 新增 / 优化 / 发布
**涉及模块**：素材创作平台、落地页分析、广告文案、推广图片、行业适配、大模型配置、数据模型、后端接口、前端与菜单、新版通知、发版流程、改造追踪、系统设置
**变更摘要**：按《广告素材平台问题诊断与AI改造实施说明书》启动分期改造，第 1 期修复 3 个确定性缺陷——超长文案不再被裁成残句还判合格、品牌与 Logo 不再从追踪域名 / 原始 URL 错误推导、模型展示与真实调用归因一致；同时建立行业 / 品类通用主干与局部配置，让电商、订阅之外的行业走同一链路，并在「新版通知」顶部显示当前版本号与主要更新内容、统一展示各期改造进度。
**改造期次**：第 1 期（F01 / F02 / F10）

**更新要点**
- 文案超字数不再被误判合格，压缩时保留价格、订阅限制等关键语义。
- 品牌与 Logo 从页面证据读取，不再从域名或追踪跳转地址猜测。
- 实际调用的模型、来源与回退在调用结束后定稿，停用配置不会被误用。
- 建立行业 / 品类画像；电商与订阅只是其中两个配置，其它行业局部调整即可复用全链路。
- 新版通知开始显示当前版本号、主要更新内容与分期改造进度。

**本次优化与更改的功能 / 模块**
- 【新增】改造追踪 / 问题追踪表与分期路线图：新增 `docs/REMEDIATION_TRACKER.md`，逐项记录 F01–F12 的说明书状态、当前代码核对结果、触发输入、修改文件、验收用例与实施状态；12 个问题按「每期 3 个、独立提交、独立版本通知」拆成 4 期，并标明每期的行业适配落点。说明书中的 Product / Offer / Evidence / Concept / VisualBrief / SpecProfile / GenerationJob / CreativeAsset 归为新增设计需求，不占用问题配额。
- 【新增】行业适配 / 通用主干 + 局部配置：新增 `backend/industry_profiles.py`，提供电商零售、订阅 / SaaS、App / 游戏、B2B、旅游 / 本地生活、教育、金融合规与通用共 8 个画像；每个画像只定义价值维度、必须保留的语义、需核验的事实类型、视觉主体与文案重点。主干链路对所有行业一致，未命中关键词时回落 `general`，不猜产品事实、不编造价格或功效。新增 `GET /api/industry-profiles` 供前端局部调整。
- 【优化】行业适配 / 局部调整真实生效：行业画像进入文案生成依据（价值维度与文案重点）与文生图背景提示词（主视觉 + 「不得虚构商品外观、标签、价格、评价与效果数据」约束）；切换电商 / 旅游等画像后，同一通用链路产出不同的表达重点与主视觉，无需改代码。完整的 CreativeConcept / VisualBrief 与商品参考图入口仍属第 3 期 F03，本版不宣称已完成。
- 【修复】广告文案 / F01 残句判定：`_build_fields_checked` 保留原始模型输出与逐条裁剪状态；超长文案改为有限次「语义压缩」（单字段最多 2 次、单次生成最多 6 次调用），必须保留否定词、价格 / 折扣、期限、试用 / 续费 / 退款 / 取消限制，且输出完整短句。压缩仍失败则返回 `needs_revision`（`valid=false`），字段保留完整原文并明确阻断，不再出现 "Book in minutes." 被裁成 "Book in" 却判合格的情况。
- 【修复】推广图片 / F01 图内文字预算：平台正文与图内文字分离，新增 `build_overlay_text` + `imaging.text_budget`，按版位尺寸估算标题 / 副标 / CTA 可容纳字符；`render_ad_png` 增加 `strict_text`，放不下时抛 `TextOverflowError` 而不是追加省略号。超预算版位标记 `needs_revision` 并阻止生成，返回 `status=partial_success` / `issues` / `skipped`；前端 Step 2、Step 3 分别展示待修改文案与未生成版位。保留 `style_opts.strict_text=false` 作为上线应急开关。
- 【修复】落地页分析 / F02 品牌与最终地址：`_brand_of` 不再用 host 倒数第二段推导品牌（`convert.ctypy.com` → Ctypy、`shop.example.co.uk` → Co）；品牌只来自结构化数据、官方页面资料（JSON-LD Organization / og:site_name）或用户明确确认，无法确认时标为 `needs_input` / `unverified` 并给出候选与原因。`fetch_page` 分别保存 `input_url` / `final_url` / `redirect_chain` / `status` / `content_type` / `fetch_quality`，所有相对链接与 Logo 以最终地址解析；`og:image` 不再被无条件当作 Logo，自动来源一律标注「待核验」。
- 【修复】大模型配置 / F10 路由与归因：`_pick_config` 候选先过滤 `is_active`，停用但历史测试成功的配置不再被自动调用；新增 `get_llm_with_info` / `resolve_analysis_llm` / `finalize_invocation`，展示与真实调用共用同一 `config_id` / `request_id`，`fallback` 与 `source` 在 `chat()` 结束后刷新，Mock 返回可解析 JSON 不再被误标为 `source=llm`；`FallbackLLM` 记录 timeout / auth / rate_limit / network / upstream 错误分类，调用快照不含任何凭据。
- 【新增】素材创作 / 可核验信息面板：分析结果新增「输入可信度与行业适配」区块，展示输入链接、最终落地页、跳转次数、抓取质量、模型调用来源与快照、品牌状态、Logo 来源与核验原因；品牌可手动确认（写入后视为 `confirmed`），行业 / 品类可下拉切换，并展示该画像的价值维度、需核验事实与视觉主体。
- 【新增】新版通知 / 当前版本与主要更新内容：`release_notes.py` 解析 `**改造期次**`、输出 `current`（版本号、日期、标题、摘要、主要更新内容要点、本期问题）与 `roadmap`（4 期 × 3 问题，完成状态由已发布版本自动驱动）；`ReleaseNotes.tsx` 顶部新增当前版本高亮卡片与「系统改造进度」面板，历史版本列表保留原有筛选与完整发版记录，并在版本卡片上标注改造期次。
- 【优化】发版流程 / 每期闭环：`prepare_release.py` 增加改造期次校验（必须恰好 3 个问题、编号属于路线图同一期、版本号与期次一致），并把 `docs/REMEDIATION_TRACKER.md` 纳入模块覆盖；`backend/main.py` 版本号升至 4.39.0，README 同步当前版本与改造说明。

**影响范围**
- 前端：`api.ts` 增加行业画像、调用快照、文案 `needs_revision` 与图片 `issues` 类型；`MaterialCreation.tsx` 增加可信度面板与品牌 / 行业局部调整；`MediaAdStudio.tsx` 展示待修改文案与未生成版位；`creationSession.ts` 增加 `imageIssues`；`ReleaseNotes.tsx` 增加当前版本卡片与改造进度；`styles.css` 增加对应样式。
- 后端：新增 `industry_profiles.py`、`roadmap.py`；`text_utils.py`、`imaging.py`、`media_ad.py`、`services.py`、`providers.py`、`schemas.py`、`routers.py`、`release_notes.py`、`main.py` 按上述修复调整；`LandingAnalysis` / `ModelInfo` 增加可选字段，`/api/landing-analysis` 响应体新增证据字段。
- 数据：无数据库迁移。分析结果不落库（仅写入素材历史的 `analysis_json`，旧记录缺新字段时按空值展示）；模型配置不新增列。
- 兼容性：`/api/media-campaign/copy` 与 `/images` 的入参、返回结构保持向后兼容，新增字段均为可选；不传 `copy_variants` 时仍按旧行为出图，但同样受图内文字预算约束；`style_opts.strict_text=false` 可临时恢复宽松排版。
- 行为变化：品牌不再由域名自动填充，未确认时图片品牌条为空并标注「未确认品牌」；超长且压缩失败的文案 / 版位不会作为合格素材导出，页面会明确列出待修改项。
- 权限：新增 `/api/industry-profiles` 对所有登录角色可读；新版通知仍对所有登录角色（含 viewer）开放。

**验证**
- 后端全量 `compileall` 通过，`import main` 正常，版本号 4.39.0。
- DB 副本确定性回归 33 项断言全通过，覆盖 T01 / T02 / T03 / T04 / T13 / T14：残句阻断与语义压缩成功 / 失败两条路径、否定与价格及订阅限制保留、追踪域名与多级后缀品牌、跳转后相对 Logo 与 og:image 待核验、停用配置不可选、超时回退归因与 Mock 不误标 llm。
- DB 副本 TestClient 端到端 22 项断言全通过：新版通知 `current`（V4.39 + 主要更新内容）与 `roadmap`（3/12 已完成）、行业画像接口、落地页分析证据字段、文案调用快照、短文案 4 版位 PNG 真实落盘、超预算版位 `partial_success` 且不出残图、旧调用兼容、`strict_text=false` 应急开关、素材历史与 viewer 权限。
- 行业局部调整纯函数断言：8 个画像共用主干，电商与旅游画像的背景提示词 / 文案依据分别包含各自视觉主体与价值维度且互不相同，事实边界约束存在。
- 前端 `tsc --noEmit` 与 `vite build` 通过（43 模块，253.88 kB JS / 52.51 kB CSS）；`prepare_release.py --check` 通过且无警告（含改造期次 3 问题 / 版本一致性校验）。详细命令与结果见 `docs/REMEDIATION_TRACKER.md` 第 1 期验证记录。
- 未验证 / 未实施：F03–F09、F11、F12 属第 2–4 期，本次未改动；未运行真实付费模型调用、未测量投放效果，不承诺任何 ROAS / CPA 提升；新增媒体规格、真实商品图与效果反馈链路均留待对应期次并附官方来源与核验日期。

## V4.40 AI 改造第 2 期：任务与规则可靠性（F07 / F08 / F11）

**发布日期**：2026-11-10
**变更类型**：修复 / 新增 / 优化 / 发布
**涉及模块**：素材创作平台、创意文案、推广图片、媒体规则、行业适配、素材历史、后端接口、数据模型、前端与菜单、新版通知、发版流程、改造追踪、系统设置
**变更摘要**：按《广告素材平台问题诊断与AI改造实施说明书》推进第 2 期，修复 3 个 P1 问题——版位清单不再被数量静默截断、文案按「概念」整体配对而不机械混池；媒体规则升级为带广告产品 / 资产角色 / 版本与来源的版本化目录，异常请求在调用模型前被明确拒绝；并发生成的临时文件按批次隔离、供应商限流与超时生效，逐图标注成功 / 回退 / 失败，批次可为 partial_success 或 failed。行业画像继续以局部配置方式提供版位偏好，主干对所有行业一致。
**改造期次**：第 2 期（F07 / F08 / F11）

**更新要点**
- 推广图片任务矩阵覆盖全部所选版位，预算不足时明确提示，不再静默截断任务。
- 媒体规则按平台 / 广告产品 / 资产角色版本化管理，异常尺寸与超额请求在调用模型前拒绝。
- 批次临时文件按批次隔离，供应商并发与超时可控，逐图返回成功 / 回退 / 失败与批次部分成功状态。

**本次优化与更改的功能 / 模块**
- 【修复】推广图片 / F07 任务矩阵完整覆盖：删除 `MediaAdStudio.buildSlots` 的 `slice(0, count)`，新增前端纯函数模块 `taskMatrix.ts`，把「选中版位 × 尺寸」全量展开成可确认的任务矩阵。默认 Facebook 4 个任务含 Stories 1080x1920、Google 保留 UAC 竖版、Unity 的两个同尺寸全屏任务按「尺寸 + 资产角色」自动合并；预览表格的每行（版位 / 尺寸 / 广告产品 / 资产角色 / 概念）与实际请求完全一致。生成预算改为任务数上限，预算不足时明确提示并提供「按清单补足预算」，禁止静默截断。
- 【修复】创意文案 / F07 概念一致性：`buildConcepts` 让同一概念的主标题、证据副标与 CTA 取自同一来源位置，字段条数不足时复用首条而不是按 `i % len` 回绕错配；平台正文 `primary_text` 不再混入图内副标，也不与 description / body 混池。新增「使用概念数 / 每概念标题变体数 / 概念分配方式（先覆盖版位 · 每个概念覆盖全部版位）/ 保留同尺寸不同广告产品」四个独立控制量，任务逐行带 `concept_index`，后端按该索引取文案，旧调用不带索引时兼容按序轮换。
- 【新增】媒体规则 / F08 版本化目录：`media_platforms.py` 为每个版位补充 `platform` / `ad_product` / `placement` / `asset_role` / `os` / `spec_version`，并把规则分成 `hard`（服务端强制）/ `policy`（业务政策）/ `advisory`（建议）；新增 `SPEC_VERSION=2026-11-10.2`、`SPEC_SOURCE`、`SPEC_VERIFIED_ON`（空值=尚未按官方文档核验）与免责说明。Google RSA 配图与 UAC 素材分别标注广告产品，文案接口支持按 `ad_product` 选择独立 schema，不再把 RSA 长描述当应用广告图片素材。新增 `GET /api/media-rules` 暴露规则与行业版位偏好。
- 【新增】后端接口 / F08 模型调用前强校验：`validate_task_matrix` 在调用任何模型或文生图前重新解析尺寸，校验允许尺寸、边长、单张像素、任务数（≤24）、累计像素（≤40 MP）、`concept_index` 与规则版本一致性；未知平台（如 Moloco）显式返回 422 与可读原因，不静默套用其它平台 schema。`MediaImageSlot` 增加 `placement_id` / `concept_index` / `concept_id`，`MediaImageRequest` 增加 `spec_version` / `total_pixels` 供一致性核对；前端错误提示支持展开结构化原因。
- 【修复】推广图片 / F11 批次隔离与失败处理：新增 `batch_workspace.py`，每批独立 `_mabatch_<id>/` 目录并维护自有文件清单，只清理本批文件；替换掉按目录通配符删除全部 `_mabg_*` / `_mlogo_*` 的旧实现，远程 Logo 下载也写入本批目录。新增超时遗留目录回收（TTL 1 小时），运行中的批次不被误清。`asyncio.gather` 增加供应商级信号量（默认并发 4）、单任务超时（默认 200s）与本地渲染有限重试（不重复发起已计费的模型调用）；逐图返回 `status` / `ai_background` / `fallback_reason` / `model` / `retries` / `batch_id`，批次回传 `task_results` 与 `status=ok|partial_success|failed`，失败项不计入合格素材。
- 【优化】行业适配 / 版位偏好局部调整：`industry_profiles.py` 新增 `PLACEMENT_PREFERENCES`，8 个画像各自登记建议版位 id（如电商 feed/stories/in_feed、App 游戏 uac/rewarded、B2B display_mrec），经 `GET /api/industry-profiles` 与 `/api/media-rules` 下发；「素材创作」版位卡片标注「行业建议」，只做提示不自动勾选、不写死电商版位，任务矩阵与规则主干对所有行业一致。
- 【优化】素材历史 / F08 导出标记：每张图片把 `ad_product` / `asset_role` / `spec_version` / `batch_id` 写入历史元数据；`copy.txt` 增加「适用广告产品与规则版本」段落，历史导出 `生成信息.json` 增加产品、资产角色、规则版本与批次列表，一键打包下载的 `清单.json` 也标注规则版本与核验说明。
- 【优化】前端与菜单 / 逐图状态可见：Step 3 图片卡片显示「AI 底图 / 模板兜底」、概念编号与适用规则；未生成任务按「失败 / needs_revision」分别以 error 与 warning 展示并说明「仅重试失败项、不重复计费或归档」；任务浮窗结束日志写明成功数、AI 数、兜底数、失败数与规则版本。Step 1 展示规则版本、来源、核验日期与单批上限。
- 【优化】发版流程 / 新版通知当前版本：沿用 V4.39 建立的单一数据源，`**改造期次**：第 2 期（F07 / F08 / F11）` 使「新版通知」顶部当前版本自动切换为 V4.40 并展示主要更新内容，改造进度由 3/12 自动更新为 6/12；无需在页面或路线图里手工维护完成状态。`main.py` 版本号升至 4.40.0，README 与追踪表同步。
- 【优化】改造追踪 / 第 2 期验证记录：`docs/REMEDIATION_TRACKER.md` 把 F07 / F08 / F11 标为已修复，追加第 2 期验证记录与未验证边界；分期路线图第 2 期状态由已发布版本驱动，不在此表手工改写。
- 【发布】发版流程 / V4.40：本条按结构化规范整理本次优化和更改的功能与模块，发版前由 `prepare_release.py --check` 校验模块覆盖、字段完整性与「每期 3 个问题 / 版本一致」后再同步 git。

**影响范围**
- 前端：新增 `taskMatrix.ts`；`MediaAdStudio.tsx` 的任务矩阵、概念预览、控制量与逐图状态全面替换旧的 `buildSlots` 与取模轮换；`creationSession.ts` 增加 4 个控制量并让 `buildCopyVariants` 委托概念构造；`api.ts` 增加 `MediaRules` / `mediaRules()`、图片状态与规则字段、结构化错误展开；`styles.css` 增加矩阵表格、规则说明与状态标签样式。
- 后端：新增 `batch_workspace.py`；`media_platforms.py` 升级为版本化规则目录与校验入口；`media_ad.py` 重构出图批次、并发与逐图结果；`routers.py` 增加 `/api/media-rules` 与模型调用前校验；`schemas.py` 扩展任务行与请求字段；`creation_history.py` 导出标注；`industry_profiles.py` 增加版位偏好；`main.py` 版本 4.40.0。
- 数据：无数据库迁移。素材历史 `images_json` 与 `copy_json` 新增可选元数据键，旧记录按空值展示，不回填、不重新生成；`model_configs`、`users`、`prompt_configs` 不受影响。
- 兼容性：`/api/media-campaign/images` 不传 `copy_variants` / `concept_index` / `spec_version` 时保持旧行为；`style_opts.strict_text=false` 应急开关保留。行为变化：未知平台、不在允许清单的尺寸、超任务数 / 超像素与规则版本不一致现在返回 422 而不是静默出图；前端默认预算改为完整版位任务数（Facebook 由 3 变 4）。
- 权限：`/api/media-rules` 与 `/api/industry-profiles` 对所有登录角色可读；生成类接口仍仅 admin / manager / editor 可用；新版通知仍对所有登录角色开放。
- 部署：可通过 `AD_MAX_IMAGE_CONCURRENCY`、`AD_IMAGE_TASK_TIMEOUT`、`AD_BATCH_STALE_TTL` 调整供应商并发、任务超时与遗留目录回收窗口，无需改代码。

**验证**
- 后端全量 `compileall` 通过，`import main` 正常，版本号 4.40.0，注册路由 49 条。
- T09（F07）前端纯函数回归 40 项断言全通过：Facebook 默认 4 任务含 Stories、Google UAC 不被截断、Unity 1080x1920 重复任务被合并且可显式保留、概念标题与证据同源、平台正文不入图、预算 3 时仍保留 4 任务且明确提示、full_cover 模式 2×4=8、边界空清单。
- T10（F08）服务端规则回归：未知平台、异常尺寸、非法格式、尺寸不在清单、任务数超限、累计像素超限、`concept_index` 越界、规则版本不一致、文案接口未知平台全部在调用模型前返回 422 并给出可读原因；合法任务矩阵解析出广告产品 / 资产角色 / 规则版本，行业版位偏好随规则接口下发。
- T15（F11）批次隔离回归：批次 A 清理后 B 的临时文件仍在、超时遗留目录被回收而运行中批次不被误清；混合批次 3 个任务逐项得到 ok / fallback / failed，`status=partial_success`、`task_results` 3 条、AI 与模板回退分别标注且不按整批成功计；两批并发用屏障交错执行，双方临时底图均未被对方删除，结束后无临时目录残留。
- HTTP 端到端（DB 副本 + TestClient）85 项断言全通过：7 个平台目录、规则接口、异常请求 422、合法 4 任务出图且 PNG 真实落盘、概念按矩阵分配、旧调用兼容、Google UAC 独立 schema、新版通知 / 行业画像 / 素材历史 / 大模型配置接口未受影响；历史导出与打包清单的规则版本标记通过 ZIP 内容断言。
- 会话中枢 Node 回归 19 项断言全通过：新增控制量默认值、概念组合同源与平台正文隔离、刷新恢复归零与数值边界清洗、账号隔离。
- 前端 `tsc --noEmit` 通过；`vite build` 44 模块，263.40 kB JS / 54.41 kB CSS；`docs/REMEDIATION_TRACKER.md` 记录第 2 期验证明细。
- 所有回归在数据库副本、临时 uploads 目录与模拟供应商上执行，测试 PNG 与临时库已清理；未修改生产数据、未读取或输出任何密钥。

**说明 / 默认约定**
- 媒体尺寸与政策是**内部整理**，`SPEC_VERIFIED_ON` 为空表示尚未按各平台官方文档核验；正式投放前须复核并更新 `SPEC_VERSION` 与核验日期，导出只标注内部规则版本，不宣称符合平台审核规范。Moloco 等未入库平台需先核实实际业务与官方规则再新增，不静默回退。
- 未运行真实付费文生图 / 文本模型调用，未做真实样本逐图人工抽检，未测量投放效果，不承诺 ROAS / CPA 提升；供应商并发与超时为默认保护值，需按实际供应商配额调整。
- 服务端持久任务队列、幂等 `job_id`、真实商品图参考编辑、CreativeConcept / VisualBrief 完整结构与效果反馈链路仍属第 3–4 期（F03–F06、F09、F12），本版不宣称已完成。
- 下发改动时先 `git pull` 再重启后端；前端重新构建即可。刷新页面会重新拉取媒体规则，浏览器缓存旧 `spec_version` 时会收到明确的「规则版本不一致」提示而非静默降级。

## V4.41 AI 改造第 3 期：创意与视觉表达（F03 / F04 / F05）

**发布日期**：2026-11-10
**变更类型**：修复 / 新增 / 优化 / 发布
**涉及模块**：素材创作平台、创意文案、推广图片、素材提示词、行业适配、素材历史、后端接口、数据模型、前端与菜单、新版通知、发版流程、改造追踪、系统设置
**变更摘要**：按《广告素材平台问题诊断与AI改造实施说明书》推进第 3 期，修复 3 个 P1 问题——文生图提示词改为「先选创意概念、再生成视觉简报、最后构建逐任务背景描述」，不同购买理由得到不同主体动作与证据，同一概念跨尺寸保持同一承诺；新增 `ResolvedCreativeConfig` 作为预设解析的唯一来源，管理员编辑过的方向 / 风格 / 配色文本原样进入文案与供应商请求，纯视觉字段明确不进入文案大模型，配置 ID / 版本 / 哈希与最终提示词哈希随每张图和素材历史归档；渲染层解除固定排版与固定色板，按内容需求选择五种版式、按品牌 token 上色、先预留 Logo 安全区、保留白色 Logo 细节并改用局部遮罩保护商品原色。行业画像继续只提供视觉主体与价值维度的局部配置，主干对所有行业一致。
**改造期次**：第 3 期（F03 / F04 / F05）

**更新要点**
- 创意概念先于背景提示词确定，同一概念跨尺寸保持画面主体与承诺一致。
- 管理员编辑过的方向 / 风格 / 配色完整进入文案与出图请求，并随图归档不可覆盖的配置快照。
- 推广图片新增五种内容版式、品牌色同步与 Logo 安全区，白色 Logo 细节不再丢失。
- 支持传入真实商品参考图；供应商未声明参考编辑能力时改为本地合成并明确标注能力限制。

**本次优化与更改的功能 / 模块**
- 【修复】推广图片 / F03 概念驱动画面：新增 `creative_config.py` 的 `CreativeConcept` 与 `VisualBrief`，先确定受众情境、购买阻力、核心承诺、证据、主体、动作、场景与构图，再构建文生图提示词。`generate_media_images` 把「计算背景提示词」移到选定文案组合之后，逐任务调用 `_media_image_prompt(analysis, platform, config, brief, db)`；清洗演示与通勤场景得到不同的主体动作与场景，同一 `concept_key` 跨尺寸仍携带相同的核心承诺与证据。每个版本绑定 `concept_id` / `concept_key` / `prompt_hash`。
- 【新增】推广图片 / F03 商品参考图能力边界：`style_opts.reference_image` 可传入用户上传的真实商品图 / UI；供应商声明 `reference_image` 能力时把原图交给参考编辑，未声明时改为本地合成到主体区并在 `capability_note`、`reference_mode`、图片元数据与导出中明确标注「这不是 AI 参考编辑」。未提供参考图时提示词只使用落地页事实与行业视觉约束，不虚构商品外观、标签、规格与评价。
- 【修复】创意文案 / F04 预设编辑全量生效：新增 `ResolvedCreativeConfig` 与 `resolve_creative_config()`，把 `build_directives` 的结果收口成唯一一份解析结果；删除 `media_ad` 里按预设 ID 重建的 `STYLE_TO_BG` / `COLOR_TO_PALETTE` 重复映射。`direction_text` / `style_text` / `color_text` / `design_prompt` 原样写入文生图请求，`strategy_block` 注入文案系统提示词（自定义模板无对应模板变量时自动追加），`compose_copy_prompt` 增加 `creative` 参数。纯视觉字段（调色板 / 版式 / 背景键）不进入文案大模型，不改变字段结构与字数红线。
- 【新增】素材历史 / F04 不可覆盖的配置快照：`config_snapshot` 输出 `config_id` / `version` / `hash` / `preset_ids` / `custom_fields` / `visual`，写进文案结果、每张图片、批次结果与历史 `style_opts_json`；`copy.txt` 与 `生成信息.json` 增加「本次生成实际生效的创意配置（历史快照）」、版式、概念、配置 ID 与提示词哈希。后续修改预设会生成新的 `config_id`，不会覆盖旧任务的归档。
- 【修复】推广图片 / F05 动态版式与品牌 token：`imaging.py` 增加 `LAYOUT_SPEC` 五种版式（商品主视觉 hero / 使用演示 demo / 细节 detail / 优惠 offer / 评价 review）与小横幅专用单行版式，按概念关键词、创意方向与版位比例选择；`resolve_palette` 把十六进制品牌 token 解析为完整渲染色板，作用于渐变底图、CTA、强调线与卡片，切换配色同时改变背景与排版元素。F01 的文字预算改为按所选版式与 Logo 预留框计算，`strict_text` 严格阻断不回退。
- 【修复】推广图片 / F05 Logo 与商品颜色保护：`logo_metrics` 在排版之前算出 Logo 安全区，320x50 下标题 / CTA / Logo 三段依次预留并保证边界不重叠；`_composite_logo` 默认完整保留透明源与白色品牌内容，近白背景去除改为显式开关且只作用于无真实透明通道的源。`_prepare_bg` 用文字区局部渐变遮罩替代「整幅混合 42% 暗色」，主体区商品颜色不被改动；`_composite_product` 在不支持参考编辑时把真实商品图合成到版式预留的主体区。
- 【优化】前端与菜单 / 配置快照与视觉简报可见：`MediaAdStudio.tsx` 生成文案时也传 `style_opts`，「生成推广图片」Step 3 顶部显示本批实际生效的配置 ID / 版本 / 哈希 / 自定义预设，图片卡片显示版式与逐图画面动作、参考图模式；`api.ts` 增加 `CreativeConfigSnapshot` / `VisualBrief` 类型与文案、图片、任务结果的对应字段；历史写入保存配置快照。`styles.css` 增加配置快照卡与视觉简报样式。
- 【优化】系统设置 / 新版通知当前版本与进度：`**改造期次**：第 3 期（F03 / F04 / F05）` 让「新版通知」顶部当前版本自动切换为 V4.41 并展示本期主要更新内容，改造进度由 6/12 自动更新为 9/12；`main.py` 版本升至 4.41.0，README 与追踪表同步，页面与路线图无需手工维护完成状态。
- 【优化】素材提示词 / 模板变量兼容：`MEDIA_COPY_SYS` 增加 `[[CREATIVE]]` 模板变量，`compose_copy_prompt` 对没有该变量的自定义模板自动追加创意表达倾向块，保证管理员在「素材提示词」里保存的自定义主提示词同样能收到编辑过的预设。
- 【优化】改造追踪 / 第 3 期验证记录：`docs/REMEDIATION_TRACKER.md` 把 F03 / F04 / F05 标为已修复，追加第 3 期验证记录与未验证边界；分期路线图第 3 期状态由已发布版本驱动。
- 【发布】发版流程 / V4.41：本条按结构化规范整理本次优化和更改的功能与模块，发版前由 `prepare_release.py --check` 校验模块覆盖、字段完整性与「每期 3 个问题 / 版本一致」后再同步 git。

**影响范围**
- 前端：`api.ts` 增加类型与 `mediaCopy` 的 `style_opts`；`MediaAdStudio.tsx` 文案与图片调用都传预设、Step 3 展示配置快照与视觉简报、历史写入保存快照；`styles.css` 增加两类展示样式。任务矩阵、版位规则、跨页面会话中枢与素材历史交互不变。
- 后端：新增 `backend/creative_config.py`；`media_ad.py` 重排「概念 → 简报 → 提示词 → 合成」链路并改用统一配置；`imaging.py` 增加版式规格、品牌 token、局部遮罩、Logo 安全区与商品图合成；`prompt_catalog.py` 增加模板变量与 `creative` 参数；`schemas.py` 的 `MediaCopyRequest` 增加 `style_opts`；`routers.py` 把风格选项透传给文案生成；`creation_history.py` 导出配置快照；`main.py` 版本 4.41.0。
- 数据：无数据库迁移。素材历史 `style_opts_json` / `images_json` 新增可选元数据键，旧记录按空值展示，不回填、不重新生成；`model_configs`、`users`、`prompt_configs` 不受影响。
- 兼容性：`/api/media-campaign/copy` 不传 `style_opts` 时按内置默认预设解析；`/api/media-campaign/images` 不传 `copy_variants` / `concept_index` / `reference_image` 时保持旧行为；`render_ad_png` 旧调用的 11 个位置参数与 `text_budget` 默认口径不变；`style_opts.strict_text=false` 应急开关保留。行为变化：同一批次不同概念不再共用同一背景描述；所选配色与版式现在会真正改变成图；小横幅有 Logo 时标题可排版宽度变小，超预算会明确返回 `needs_revision` 而不是与 Logo 挤在一起。
- 权限：文案与图片生成接口仍仅 admin / manager / editor 可用；新版通知、媒体规则、行业画像对所有登录角色可读；本次没有新增对外接口。
- 部署：无新增依赖与环境变量；`git pull` 后重启后端、前端重新构建即可。

**验证**
- 后端全量 `compileall` 通过，`import main` 正常，版本号 4.41.0，注册路由 49 条。
- T05（F03）回归：两个概念产生不同 `concept_key`、不同主体动作与场景，两条实际发给模拟供应商的请求字面不同且各自包含自己的核心承诺与 `concept_id`；同一概念在 1080x1080 与 320x50 下仍携带相同承诺与证据；提示词哈希可区分概念；事实边界约束存在。
- T06（F04）回归：唯一标记写进方向预设后，进入 `ResolvedCreativeConfig.strategy`、`strategy_block`、`visual_text_block`、文案系统提示词与文生图请求；无对应模板变量的自定义主提示词同样收到该标记；纯视觉调色板十六进制值不出现在文案提示词中但出现在图片提示词中；相同配置解析结果稳定、修改预设后 ID 改变、旧任务快照不被覆盖；HTTP 文案与图片调用均验证供应商请求含该标记。
- T07（F05）回归：切换配色后模板底图与 CTA / 强调元素同步变化；五种版式产出五种不同构图；白色 Logo 细节默认保留、近白去除改为显式开关且只作用于不透明源；320x50 下标题 / CTA / Logo 三段边界互不重叠且文字预算扣除 Logo 预留框；局部遮罩不改动主体区商品颜色、文字区仍有可读性处理；旧调用参数与默认 `text_budget` 口径保持兼容。
- 后端回归共 71 项断言全通过（临时数据库 + TestClient + 模拟供应商）：文案 / 图片接口 200、两个概念各出一张 PNG 且真实落盘、逐图 `concept_id` / `visual_brief` / `creative_config` / `prompt_hash` / `layout` 齐备、批次返回配置快照、未知平台仍在调用模型前 422；商品参考图在供应商未声明能力时标注本地合成、超预算版位被阻断且整批无可用素材（F01 / F11 未回退）；媒体规则、行业画像、新版通知、素材历史、大模型配置接口未受影响；新版通知当前版本为 V4.41、改造进度 9/12。
- 前端 `tsc --noEmit` 通过；`vite build` 通过；`prepare_release.py --check` 通过（含改造期次 3 问题 / 版本一致性 / 模块覆盖校验）。
- 所有回归在临时数据库、临时 uploads 目录与模拟供应商上执行，测试 PNG 与临时库已清理；未修改生产数据、未读取或输出任何密钥。

**说明 / 默认约定**
- 本期修复的是「概念 → 提示词 → 合成」的表达链路，不等于已验证投放效果。未运行真实付费文本 / 文生图模型调用，未做真实样本逐图人工抽检，未测量 CTR / CPA / ROAS，不承诺效果提升。
- 商品参考图只在供应商声明支持时作为参考编辑输入；当前内置供应商均未声明该能力，因此默认走本地合成并如实标注能力限制，不宣称做了 AI 参考编辑。主体保护框、比例适配与居中裁切问题（F06）仍属第 4 期，本期保留原有 cover 裁剪，未宣称修复。
- `CreativeConcept` / `VisualBrief` / `ResolvedCreativeConfig` 在本期以「生成链路中的结构化解析结果」落地；产品事实、报价、证据 ID、服务端持久任务与效果反馈闭环（批次 B / C / D 的完整数据模型）仍属第 4 期及后续，不把本期结构等同于完整数据模型。
- 媒体尺寸与政策仍是内部整理，`SPEC_VERIFIED_ON` 为空；正式投放前须按平台官方文档复核。新版通知的当前版本与改造进度完全由 CHANGELOG 的发版记录驱动，改代码不改发版文案不会更新进度。

## V4.42 AI 改造第 4 期：事实与工程化（F06 / F09 / F12）

**发布日期**：2026-11-10
**变更类型**：修复 / 新增 / 优化 / 发布
**涉及模块**：素材创作平台、创意文案、推广图片、素材提示词、行业适配、素材历史、后端接口、数据模型、前端与菜单、新版通知、发版流程、改造追踪、系统设置、大模型配置
**变更摘要**：按《广告素材平台问题诊断与AI改造实施说明书》完成第 4 期，也是四期改造的收官期，修复 3 个问题——F06 建立供应商尺寸能力目录与按比例构图，宽高不再各自吸附成方形，渲染端用主体保护框与极端版位扩图替代无条件 cover 居中裁切，逐图归档请求尺寸、实际返回尺寸与真实裁切参数；F09 把落地页正文从「只送前 4000 字符」改为首尾窗口加关键条款区块的预算内采样，新增证据编号、采样覆盖、已验证事实 / 营销假设 / 资料缺口分离，空页、抓取失败、薄内容与过期优惠在调用模型之前明确阻断为 needs_input；F12 把长耗时出图与归档整体搬到服务端，新增持久 `GenerationJob` 与不可变 `CreativeAsset` 两张表，任务创建立即返回 `job_id` 且按幂等键去重，刷新 / 关闭浏览器后按任务 ID 恢复，失败 / 取消状态真实可见，仅重试失败子任务，历史素材超过 80 张仍可按页读取早期记录。四期共 12 个问题全部完成，行业 / 品类适配继续只作为通用主干上的局部配置。
**改造期次**：第 4 期（F06 / F09 / F12）

**更新要点**
- 出图按供应商真实尺寸能力请求，渲染端用主体保护框与扩图避免裁掉主体；每张图可查看请求尺寸、返回尺寸与裁切参数。
- 落地页分析改为带编号的证据链采样，关键条款不再因正文过长丢失；空页、抓取失败或含过期优惠会在调用模型前阻断。
- 出图与归档改为服务端持久任务，刷新或关闭浏览器仍可恢复进度，支持取消与仅重试失败项。
- 素材历史改为不可变资产记录，超过 80 张仍可分页查看早期素材；导出补充构图与事实证据信息。
- 四期 AI 改造的 12 个问题全部完成。

**本次优化与更改的功能 / 模块**
- 【新增】推广图片 / F06 供应商尺寸能力目录：新增 `backend/image_capabilities.py`，用 `PROVIDER_CAPABILITIES` 声明各文生图供应商的尺寸候选、参考图、局部编辑、透明图、并发上限与核验日期。默认候选只沿用代码内已有实测说明的 1024 / 2048 方形尺寸，其它比例须由部署方通过 `params.size_candidates` 显式配置并附 `size_verified_on`；`GET /api/image-capabilities` 下发能力清单，核验日期为空时明确标注未核验，不编造 API 已支持的尺寸。
- 【修复】推广图片 / F06 按比例请求与构图目标：`providers.py` 给每个供应商加 `capability_key`，`DashScopeMaaSImageProvider.generate` 改用 `plan_generation_size()` 把宽高作为一个比例整体选候选，废弃「两个 `_snap()` 拼成方形」的旧做法（1200×628 不再被静默请求为 1024×1024）。`composition_goal()` 按横版 / 竖版 / 方版 / 极端比例写入「主体放安全区、给文字留白」的构图目标，随每条文生图请求发出。
- 【修复】推广图片 / F06 主体保护裁切与扩图：`imaging.py` 新增 `COMPOSITION_REGIONS`（每种版式的主体保护区与文字区）与 `_prepare_bg` 的主体保护构图；`plan_composition()` 计算能完整保留主体框的裁切锚点并按文字区避让，源图比例与目标差异过大或极端横幅时走 contain 扩图加边缘延展，源图一个像素都不裁。T08 用带中心与四角颜色标记的测试图验证四角标记全部保留。
- 【新增】推广图片 / F06 逐图可核对的比例记录：每张图片回传 `request_size` / `target_size` / `returned_size` / `composition`（mode、crop、anchor、subject_box、text_box、protected、ratio_gap）与 `size_capability`；`task_results`、批次 `composition` 汇总、`copy.txt` 与历史 `生成信息.json` 同步记录。前端图片卡片显示构图模式、底图与请求尺寸。
- 【新增】落地页分析 / F09 分区采集与证据链：新增 `backend/evidence.py`，`split_sections()` 按标题 / 段落切出带字符区间的区块，`key_clauses()` 定位价格、退货、订阅、试用、运费、保证与优惠有效期，`build_evidence_index()` 为每条区块生成 `evidence_id`、原文、来源地址、区块、字符位置、核验状态与适用范围；`verified` 只表示有原文可引用，不代表商业真实性背书。
- 【修复】落地页分析 / F09 不再截前 4000 字符：`select_evidence_budget()` 改为「首尾窗口 + 关键条款区块」的预算内采样并如实返回 `coverage` 与 `dropped_chars`；`build_landing_prompt()` 输出带 `[E###]` 编号的分段正文，要求模型把 facts / assumptions / gaps 分开、每条价格或承诺引用证据编号、竞品只来自正文且独立研究附来源、不从域名猜产品事实。`schemas.LandingAnalysis` 增加证据链、覆盖、缺口、过期优惠、阻断原因与 `legacy_unverified` 字段。
- 【修复】落地页分析 / F09 空证据与过期优惠阻断：`evidence_gate()` 在调用模型之前检查空页、抓取失败、薄内容与明确已过期的优惠；不通过时 `analyze_landing_concise` 返回 `gate_status=needs_input` 且不发起模型调用，`/api/landing-analysis` 返回结构化 422 并列出具体原因，前端展示证据链、采样覆盖、事实 / 假设 / 缺口与承诺到证据编号的映射。
- 【新增】素材历史 / F12 服务端持久任务：新增 `GenerationJob` 表与 `backend/job_service.py`。`POST /api/generation-jobs` 立即返回 `job_id`（202）并在后台执行规则校验 → 生成 → 归档，浏览器断开或刷新都不影响；`GET /api/generation-jobs/{job_id}` 可恢复状态与结果，列表、取消、分项重试接口齐备。同一 `idempotency_key` 重复提交只返回原任务，不重复调用模型、不重复归档。
- 【新增】素材历史 / F12 不可变资产与分页：新增 `CreativeAsset` 表，一次生成一张即插入一行，只插入不覆盖；`GET /api/creative-assets?history_id=&offset=` 分页读取，历史超过 80 张仍能查到早期素材。`update_creation_history` 的 `uniq[-80:]` 明确降级为「最近 80 张展示缓存」，不再静默丢弃元数据；删除历史时按显式策略同步删除资产行并安全回收不再被引用的文件。进程重启时 `recover_interrupted()` 把停在 running / queued 的任务标为 failed 并写明原因，不假装任务仍在跑。
- 【新增】素材历史 / F12 分项重试：`POST /api/generation-jobs/{job_id}/retry` 只按 `task_index` 取回 `status=failed` 的子任务重建请求，成功项不重复生成、不重复收费；`needs_revision` 明确要求人工修改文案后重试，不会被当成可自动重试的失败项。取消状态真实可见，运行中任务在检查点停止并保留已生成素材。
- 【优化】前端与菜单 / 服务端任务与恢复：`creationSession.ts` 增加 `jobId` / `jobStatus` / `jobSeq` 并持久化，刷新后不再误报「任务已中断」而是按 `job_id` 自动恢复；`MediaAdStudio.tsx` 的出图改为创建持久任务 + 轮询，生成与归档不再由浏览器另发请求，Step 3 显示任务状态、取消与「仅重试失败项」入口；`MaterialHistory.tsx` 增加全量资产分页面板；`api.ts` 增加任务、资产、尺寸能力接口与全部对应类型。
- 【优化】素材历史 / 导出追溯：`copy_as_text` 增加构图与尺寸能力、服务端任务、历史保留策略；`analysis_as_text` 增加事实证据链与承诺到证据编号的映射；`生成信息.json` 增加 `composition_modes` / `request_sizes` / `returned_sizes` / `job_ids` / `evidence` / `retention_policy`；打包 `清单.json` 增加构图说明与保留策略。空历史与旧记录保持兼容。
- 【优化】系统设置 / 新版通知收官：`**改造期次**：第 4 期（F06 / F09 / F12）` 让「新版通知」当前版本自动切换为 V4.42 并展示本期主要更新内容，改造进度由 9/12 更新为 12/12，四期全部标为 done；`main.py` 版本升至 4.42.0，README 与追踪表同步。
- 【发布】发版流程 / V4.42：本条按结构化规范整理本次优化和更改的功能与模块，发版前由 `prepare_release.py --check` 校验模块覆盖、字段完整性与「每期 3 个问题 / 版本一致」后再同步 git。

**影响范围**
- 前端：`api.ts` 增加任务 / 资产 / 尺寸能力类型与接口、`MediaImagePayload` 共用入参；`creationSession.ts` 增加三个会话字段；`MediaAdStudio.tsx` 出图改为持久任务 + 轮询并新增恢复 effect；`MaterialCreation.tsx` 展示证据链；`MaterialHistory.tsx` 新增资产分页面板；`styles.css` 增加任务条、证据链、资产分页与逐图构图样式。原有版位任务矩阵、规则版本校验、跨页面会话与素材历史交互保持不变。
- 后端：新增 `backend/image_capabilities.py` / `evidence.py` / `job_service.py`；`providers.py` 声明能力键并按比例请求；`imaging.py` 主体保护构图；`media_ad.py` 逐图记录请求 / 返回尺寸与裁切参数并给 `task_results` 加 `task_index`；`services.py` 证据采样与阻断门；`schemas.py` 增加分析证据字段；`models.py` 新增两张表；`routers.py` 新增 7 个接口并把落地页分析 422 阻断；`creation_history.py` 导出追溯；`main.py` 版本与重启回收。
- 数据：新增 `generation_jobs` 与 `creative_assets` 两张表，由 `ensure_schema()` 的 `create_all` 自动建表，无需手写迁移，旧库直接重启即可；`creation_history` 不新增列。旧分析没有证据 ID 时按 `legacy_unverified` 展示，不自动补成已验证；旧图片保留文件与历史身份，不重新生成替换。
- 兼容性：`POST /api/media-campaign/images` 同步出图接口完整保留，仍返回逐图构图记录；`render_ad_png` 旧位置参数与 `text_budget` 默认口径不变；`build_landing_prompt` 旧三参数调用自动按新规则采样；`style_opts.strict_text=false` 应急开关保留。行为变化：正文过短、抓取失败或含过期优惠的落地页分析现在返回 422 而不再给出无证据结论；出图默认走服务端任务，前端不再主动写回历史；历史列表只展示最近 80 张缓存，完整素材改由分页读取。
- 权限：新增任务与资产接口均要求 admin / manager / editor；落地页分析 422 阻断对所有可编辑角色一致；新版通知、媒体规则、行业画像、尺寸能力对所有登录角色可读。
- 部署：无新增依赖与必填环境变量。`git pull` 后重启后端（自动建两张新表）、前端重新构建即可。可选配置：`params.size_candidates` / `params.size_verified_on` 用于登记已核验的供应商尺寸能力。

**验证**
- 后端全量 `compileall` 通过，`import main` 正常，版本号 4.42.0，有效 `/api` 路径 42 条。
- T08（F06）回归：1200×628 与方形候选比例差超阈值时标记 `needs_outpaint`、`size_verified_on` 为空；宽版与 320×50 极端横幅走扩图且 `crop=None`，方版走主体保护裁切且锚点不再固定居中；带中心与四角颜色标记的测试图经扩图输出后四种边缘标记全部保留；逐图 `request_size` / `returned_size` / `composition` / `size_capability` 齐备且 `requested_size` 与目标尺寸一致；构图目标确实写进模拟供应商收到的提示词。
- T11 / T12（F09）回归：关键订阅条款位于第 4080 字符仍进入提示词且 `coverage` 记录其字符区间；长页面如实标注未覆盖字符；空页、抓取失败、过期优惠三类输入均在调用模型前判定 `needs_input` 并给出可解释原因，HTTP 层返回结构化 422；未来优惠不误判过期；分析结果回传证据门、采样覆盖与原文字符数。
- T16（F12）回归：创建任务立即返回 `job_id` 与 queued，同一幂等键重复提交返回原任务；浏览器不参与时任务自行跑完并按 `job_id` 取回结果；生成后由服务端自动写不可变资产与历史；插入 95 条资产后按 `offset=85` 仍能分页读取早期素材元数据；分项重试只取回失败子任务、成功项不重复生成；排队任务可取消且状态真实可见；刷新后 `job_id` 保留并由会话中枢自动恢复（Node 回归 18 项断言全通过）。
- 前 3 期不回退：F01 超预算文案仍被阻断、F08 未知平台仍在调用模型前拒绝、F04 编辑过的预设仍进入配置、F11 批次 A 清理不影响批次 B、旧同步出图与文案接口均 200、媒体规则 / 行业画像 / 新版通知 / 素材历史 / 大模型配置接口未受影响。
- 后端回归共 85 项断言全通过（临时数据库 + TestClient + 模拟供应商，强制清空真实密钥，全程只走本地 Mock）；会话中枢 18 项断言全通过；导出文本与 `生成信息.json` 新增字段及空历史兼容单独验证通过。
- 前端 `tsc --noEmit` 通过；`vite build` 44 模块，271.34 kB JS / 56.82 kB CSS；`prepare_release.py --check` 通过（含改造期次 3 问题 / 版本一致性 / 模块覆盖校验）。
- 所有回归在临时数据库、临时 uploads 目录与模拟供应商上执行，测试 PNG、临时库与批次目录已清理；未修改生产数据、未读取或输出任何密钥、未产生真实付费模型调用。

**说明 / 默认约定**
- 本期修复的是「尺寸能力声明、原文证据链、服务端任务与归档」三条工程链路，不等于已验证投放效果。未运行真实付费文本 / 文生图模型调用、未做真实样本逐图人工抽检、未测量 CTR / CPA / ROAS，不承诺效果提升。
- F06 不宣称任何供应商已支持横版 / 竖版 API 尺寸：默认候选仍是代码内已有实测说明的方形尺寸，`needs_outpaint` 表明比例差过大，由渲染端扩图或主体保护处理；`size_verified_on` 为空表示尚未按官方文档与受控测试核验。媒体尺寸与政策规则 `SPEC_VERIFIED_ON` 同样为空，正式投放前须复核。
- F09 的证据「已验证」只表示页面原文可引用，不构成价格、优惠、效果或合规性的真实性背书；竞品识别仍须独立研究附来源。动态渲染页面尚未升级浏览器抓取，本次只做分区与预算采样。
- F12 的任务状态与资产记录在数据库，但进程被强制杀死时运行中的内存任务不会跨进程自动续跑，重启后由 `recover_interrupted()` 标为 failed 并提示分项重试；本实现是单进程服务端持久任务，不宣称分布式队列或跨进程事务。效果反馈闭环（关联广告 ID、订单、退款、订阅与概念表现）属批次 E，未在四期改造内实现。
- 四期共 12 个问题已按「每期 3 个、独立提交、独立版本通知」全部完成；Product / Offer / SpecProfile / GenerationJob / CreativeAsset 中，GenerationJob 与 CreativeAsset 已按本期范围落地，Product / Offer / SpecProfile 的完整独立建模与效果反馈仍属后续规划，不把现有结构等同于说明书中的完整目标数据模型。新版通知的当前版本与改造进度完全由 CHANGELOG 发版记录驱动。

## V4.43 版本通知改造：按系统版本自动同步 + 总结式展示

**发布日期**：2026-11-10
**变更类型**：修复 / 新增 / 优化 / 发布
**涉及模块**：新版通知、系统版本、前端与菜单、后端接口、发版流程、系统设置、改造追踪、文档
**变更摘要**：修复「版本通知」没有随每次系统更新同步的问题：把系统运行版本抽为单一来源，版本通知以该版本为锚点自动同步，CHANGELOG 漏写时也会生成明确标注的兜底通知，发版校验强制版本号一致；页面改为只展示版本号与总结式更新要点，从最新版本开始，删除改造进度、筛选、影响范围、验证结果与完整发版记录等无关内容。

**更新要点**
- 版本号以系统运行版本为准，每次更新后版本通知自动出现对应版本，不再停留在旧版本。
- 发版前强制校验系统版本与 CHANGELOG 版本一致；漏写版本通知会被拦截，也可用 `--sync` 自动生成总结式通知。
- 版本通知只展示版本号、日期、一句话总结与更新要点，不再铺开功能细节、前因后果与验证过程。
- 列表从最新版本开始，默认展示最近若干版本，更早版本折叠查阅。
- 重新进入页面或窗口重新聚焦时自动拉取最新通知，禁用缓存，无需整页刷新。
- 补写最近六个版本的「更新要点」，历史版本自动按模块聚合为短句。

**本次优化与更改的功能 / 模块**
- 【修复】新版通知 / 同步根因：此前通知只读人工撰写的 CHANGELOG，发版校验只检查「CHANGELOG 是否改动」与字段完整，不校验系统实际版本；漏写新版本段落时通知会停留在旧版本。本次新增 `backend/version.py` 作为唯一版本来源，`main.py` 与版本通知共用。
- 【新增】新版通知 / 自动同步：`release_notes.get_release_notes()` 以 `APP_VERSION` 为锚点，CHANGELOG 尚无该版本时生成标注 `auto_generated` 的兜底通知（要点来自本次 git 改动文件与提交信息，不编造功能细节）；CHANGELOG 缺失时同样能显示当前版本号。
- 【修复】后端接口 / 缓存：版本通知缓存改按 `(mtime_ns, size, inode)` 签名失效并提供 `invalidate_cache()`；`/api/system/release-notes` 返回 `Cache-Control: no-store`。
- 【优化】新版通知 / 精简数据契约：接口只下发 `version / title / date / summary / points / change_types / modules / auto_generated`，移除 `body / impact / verification / changes / highlights / roadmap` 等与版本更新内容无关的字段。
- 【新增】发版流程 / 版本一致性闸门：`prepare_release.py --check` 用纯解析结果校验「系统版本 == CHANGELOG 最新版本」，并把「更新要点」列为必备字段；新增 `--sync` 按当前运行版本自动生成可直接发布的总结式通知，`--points` 可传入自定义要点。
- 【优化】前端与菜单 / 总结式展示：重写 `ReleaseNotes.tsx`，删除当前版本大卡片、改造进度面板、统计与筛选工具栏、影响范围 / 验证结果 / 完整发版记录；改为版本列表，最新在前并高亮，默认展示最近 8 条，更早版本折叠。
- 【优化】前端与菜单 / 实时同步：`api.releaseNotes()` 禁用缓存并带时间戳；页面进入、窗口聚焦与定时轮询自动重新拉取，App 的红点检测同步刷新。
- 【优化】改造追踪 / 显示口径：改造进度不再占用版本通知页面，四期 12 个问题的完成情况保留在 `docs/REMEDIATION_TRACKER.md` 与版本归档中。

**影响范围**
- 前端：`api.ts` 精简版本通知类型；`ReleaseNotes.tsx` 重写；`App.tsx` 红点刷新与菜单描述；`styles.css` 清理旧通知样式并新增简洁列表样式。原有素材创作、素材历史、大模型配置页面不受影响；现有数据模型与大模型配置接口行为不变。
- 后端：新增 `backend/version.py`；`release_notes.py` 重写解析与自动同步；`main.py` 版本改为引用 `APP_VERSION`；`routers.py` 版本通知接口禁用缓存。其它接口行为不变。
- 数据：无新增表、无迁移；CHANGELOG 为唯一完整归档，V4.43 起新增「更新要点」章节。
- 兼容性：`GET /api/system/release-notes` 路径与权限不变，响应字段精简；旧前端若读取 `body` / `roadmap` 会得到 undefined，本次前端已同步更新。历史版本条目保持原样，不会重新生成或删除。
- 权限：所有登录角色仍可查阅版本通知；发版脚本只在本地 / CI 执行，不暴露为接口。
- 部署：无新增依赖与环境变量；`git pull` 后重启后端、重新构建前端即可。

**验证**
- 后端 `compileall -q backend scripts` 与 `import main` 通过，版本 4.43.0，有效 `/api` 路径 42 条；`get_release_notes()` 返回 `app_version=V4.43`、`latest=V4.43`、`auto_generated=false`、共 53 个版本，首条 6 条要点。
- 版本通知专项回归 **54 项断言全通过**：版本号映射、精简字段集合（恰好 8 个）、不下发 `body / impact / verification / roadmap`、版本降序、要点 ≤6 条且 ≤120 字、V4.37–V4.43 的要点来自「更新要点」章节、系统升版后立即出现新版本且 `auto_generated=true`、CHANGELOG 缺失仍显示当前版本、缓存按内容签名自动失效、版本不一致 / 缺要点时 `--check` 返回 1、`--sync` 生成条目可直接发布。
- 接口集成（临时数据库 + TestClient）：`/api/system/release-notes` 返回 `Cache-Control: no-store`、`latest=V4.99`（模拟升版后）、`current` 字段精简、未登录 401；`--sync` 幂等（V4.43 已存在时跳过），`--check` 通过。
- 前一期不回退：V4.42 后端回归 **85 项断言全通过**（F06 / F09 / F12 与既有接口未受影响）。
- 前端 `tsc --noEmit` 通过；`vite build` 44 模块，264.49 kB JS / 50.82 kB CSS；版本卡片 SSR 渲染 **12 项断言全通过**（含版本号、当前版本标记、日期与要点；不含改造进度、影响范围、验证结果、完整发版记录与筛选）；页面源码无关内容残留 0 处。
- 所有回归在临时数据库、临时 CHANGELOG 副本与模拟供应商上执行，强制清空 `DEFAULT_LLM_API_KEY`，未修改生产数据、未读取或输出任何密钥、未产生真实付费模型调用。

**说明 / 默认约定**
- 「更新要点」是版本通知的展示内容；「本次优化与更改 / 影响范围 / 验证」仍保留在 CHANGELOG 作为完整归档，便于发版追溯，但不在页面铺开。
- 自动生成的兜底通知只陈述可核对的改动文件与提交信息，不编造功能说明；正式发布仍应补写「更新要点」，发版闸门会强制版本一致。
- 历史版本没有「更新要点」时按模块聚合改动标题，最多 6 条、每条最多 120 字；不展示改动细节、影响范围与前因后果。
- 改造进度（四期 12 个问题）已完成并从版本通知页移除，避免与「版本更新内容」混淆；如需查阅请见 `docs/REMEDIATION_TRACKER.md`。

## V4.44 新版验收整改第 1 期（D0）：证据、规则、任务与安全

**发布日期**：2026-11-10
**变更类型**：修复 / 新增 / 优化 / 发布
**涉及模块**：素材创作平台、落地页分析、广告文案、推广图片、行业适配、素材历史、服务端任务、媒体规则、系统设置、系统版本、新版通知、后端接口、数据模型、前端与菜单、发版流程、改造追踪、安全初始化
**变更摘要**：按《素材创作平台新版验收与自动化创作改造实施方案》v2.0 完成 D0，修复验收报告指出的 N01 / N02 / N04 / N05 / N06 五个工程缺口：证据编号与广告承诺建立强引用、删除随机场景池、版位级规则强校验、任务重启与幂等边界闭环、移除源码固定凭据并新增可运行回归目录。

**更新要点**
- 证据统一为 `[E###]` 单一命名空间；不存在的编号直接拒绝，广告承诺必须能定位到原文。
- 量化承诺生成后统一校验限定条件，短句丢掉「最多 / 护理模式 / 计费周期」也会标为需修订。
- 删除按关键词和哈希挑选动作 / 场景的兜底，画面改由产品类型与真实素材决定。
- 版位与尺寸按完整规则主键校验，未知版位和尺寸错配在调用模型前拒绝；目录补 Moloco。
- 任务执行前预登记子任务，重启后可重试项续跑、结果未知项先对账；幂等键按账号隔离且内容冲突返回 409。
- 移除源码固定管理员口令与启动自愈，新增可运行 `tests/` 回归目录与显式口令轮换脚本。

**本次优化与更改的功能 / 模块**
- 【新增】落地页分析 / 证据统一命名空间：`backend/evidence.py` 新增 `build_canonical_index()` 与 `snapshot_id_of()`，`[E###]` 成为唯一可对外引用编号，每条带原文 quote、字符区间、所属分区、条款类型与来源；分区记录退为内部索引并挂 `sample_ids`。不可变快照 ID 由内容决定，内容不变则稳定。
- 【新增】广告文案 / 证据→承诺强引用：`backend/claims.py` 提供 `EvidenceSnapshot` / `validate_evidence_refs()` / `validate_evidence_chain()` / `claim_contract()`；`services._normalize_landing()` 剔除无效编号并把对应 claim 标 `rejected`，`media_ad._analysis_context()` 首次把 facts、assumptions、gaps、事实→证据映射与限定契约送进文案模型。
- 【新增】广告文案 / 生成后限定校验：`claims.check_claim_qualifiers()` 把广告短句的数字回连原文窗口，要求保留上限、条件、计费周期、测试条件与适用范围；`audit_copy_fields()` 在**每次**生成后执行，与是否超长、是否压缩无关，违规写入 `claim_audit` 与 `needs_revision`。「可定位原文」与「商业真实性已审核」显式分离。
- 【修复】推广图片 / 概念证据语义：`creative_config.build_concept()` 不再把副标直接命名为已验证证据，新增 `claim_refs` / `evidence_ids` / `claim_verified` / `evidence_kind=copy_subhead_not_verified`。
- 【修复】推广图片 / 删除随机场景（N02）：`industry_profiles.py` 新增声明式 `SCENE_POLICIES`（实体类型、主体资产、允许场景、禁止推断、默认动作与场景），`creative_config.build_visual_brief()` 移除 `_ACTION_POOL` / `_SETTING_POOL` / `_pick()` 哈希兜底；软件保留真实 UI 图层不被 no-UI 背景规则删除（A09）。
- 【修复】媒体规则 / 版位级主键（N04）：`media_platforms.py` 新增 `resolve_placement()`，`validate_task_matrix()` 对已标注版位强制校验「版位存在 + 尺寸属于该版位 + 已登记交付语义」，未知版位不再静默返回 `unspecified`；未标注版位的旧调用兼容放行但写入 `placement_warnings`。目录补 Moloco 图片 / 原生角色，Google「RSA 配图」改为「上传式展示图」，`SPEC_VERSION` 升至 `2026-11-10.3`，`SPEC_VERIFIED_ON` 仍为空并显式标注需官方复核。
- 【修复】服务端任务 / 恢复与幂等（N05）：`models.GenerationJob` 新增 `payload_hash`；`job_service.create_job()` 执行前预登记全部子任务、按账号作用域隔离幂等键、同键不同内容抛 `IdempotencyConflict`（路由返回 409）；`recover_interrupted()` 把未派发项标 `failed`（可重试）、已派发结果未知项标 `unknown_outcome`（先对账，不自动重发）；`run_job()` 回写逐图子任务状态；`retry_failed()` 优先用预登记子任务且只重试可安全重试项。
- 【修复】安全初始化（N06）：`main.py` 删除源码内全部固定默认口令与「命中历史口令就重置」的自愈逻辑；首次初始化口令来自 `INITIAL_PASSWORD_<USERNAME>` 环境变量或 CSPRNG 随机值，只写入 0600 的 `backend/.bootstrap_credentials`（已 gitignore）；新增 `scripts/rotate_admin.py`，轮换口令的同时轮换 `AUTH_SECRET` 使既有会话在重启后失效。
- 【新增】回归测试 / 可复现目录（N06）：新增 `tests/`（`run_all.py` + 6 个模块 + README），覆盖 N01 / N02 / N04 / N05 / N06 与版本通知动态回归；测试强制清空模型密钥、使用临时 SQLite，不触碰生产数据、不发起付费调用。
- 【优化】前端 / 证据与承诺可见：`api.ts` 增加证据快照、无效编号、审核状态与 `ClaimAudit` 类型；`MaterialCreation.tsx` 展示快照 ID、审核状态与已拒绝承诺；`MediaAdStudio.tsx` 增加证据 / 承诺校验警示。

**影响范围**
- 前端：`api.ts`、`MaterialCreation.tsx`、`MediaAdStudio.tsx` 增加只读展示字段；原有生成、勾选、任务与历史流程不变。
- 后端：新增 `claims.py`；`evidence.py` / `services.py` / `schemas.py` / `media_ad.py` / `creative_config.py` / `industry_profiles.py` / `media_platforms.py` / `job_service.py` / `models.py` / `routers.py` / `main.py` / `version.py` 均有改动；有效 `/api` 路径仍为 42 条。
- 数据：`generation_jobs` 自动补 `payload_hash` 列（迁移幂等）；历史任务的幂等键在首次命中时补写哈希，不判冲突；历史图片、资产与提示词不改写、不重新收费生成。
- 兼容性：未标注版位的旧调用仍放行但标记 `mixed_legacy`；证据 `evidence_index` 由 `EV_S###` 改为 `[E###]`，前端已同步；Google 广告产品名变更会影响导出元数据显示，不影响生成链路。
- 权限与部署：所有登录角色可查阅新增证据展示；**必须由管理员执行 `scripts/rotate_admin.py` 轮换线上口令与 `AUTH_SECRET` 并重启服务**，删除源码固定口令不能替代轮换；`backend/.bootstrap_credentials` 首次启动后应删除。
- 验收口径：本版为**工程修复**，不宣称素材视觉合格或投放效果提升；真实模型、真实供应商、官方规格与投放实验仍为未验证。

**验证**
- `python3 tests/run_all.py`：**72 项断言全部通过**（证据命名空间与无效引用 18 项、场景策略 14 项、版位规则 14 项、任务恢复与幂等 8 项、凭据整改 7 项、版本通知动态回归 11 项）。
- 前一期不回退：V4.42 后端回归 **85 项断言全部通过**。该脚本原使用 Facebook 不存在的 `square` 版位（旧版被静默放行），按 N04 修正为合法版位后复跑通过；测试口令改由 `INITIAL_PASSWORD_LESON` 环境变量注入临时库，不再来自源码。
- 后端 `compileall -q backend scripts tests`、`import main` 通过，版本 `4.44.0`，有效 `/api` 路径 42 条；前端 `tsc --noEmit` 通过，`vite build` 44 模块 / 265.79 kB JS / 50.82 kB CSS。
- 版本通知锚点：`version.APP_VERSION=4.44.0` 时 `get_release_notes()` 返回 `app_version=V4.44`、首条 `V4.44`，证明 V4.43 的「升版即同步」机制在本版仍生效。
- 所有回归在临时 SQLite、临时文件副本与纯函数上执行，强制清空 `DEFAULT_LLM_API_KEY`，未修改生产数据、未产生真实付费模型调用。

**说明 / 默认约定**
- 文档 N03（商品素材缺口）与默认自动创作属 D1–D6，安排在第 2 / 3 期，本版不宣称已实现。
- `SPEC_VERIFIED_ON` 与供应商 `size_verified_on` 继续留空；Moloco 目录为内部整理，正式投放前须按账户广告产品与官方文档核验。
- 「已验证事实」仍只表示页面原文可引用，不构成价格真实性、效果或合规背书；限制条件保护为规则级拦截，不替代人工审核。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。


## V4.45 默认自动化素材创作（D1–D3）：策划层、结构化概念与交付门

**发布日期**：2026-11-10
**变更类型**：新增 / 优化 / 修复 / 发布
**涉及模块**：素材创作平台、前端与菜单、后端接口、行业适配、系统版本、系统设置、数据模型、发版流程、改造追踪、工程文档
**变更摘要**：按《素材创作平台新版验收与自动化创作改造实施方案》v2.0 完成 D1–D3：新增「自动创作」并设为新建会话默认，保留「定制创作」；新增不调用新模型的确定性策划层，输出产品对象、结构化概念、VisualBrief、推荐视觉描述、覆盖摘要与交付门，并把 A01–A08 验收路径落成可运行回归。

**更新要点**
- 素材创作默认「自动创作」：分析完成后先给推荐画面与覆盖摘要，确认媒体即可一次点击生成；定制创作保留为次级入口。
- 旧会话固定迁移为定制模式，输入、分析、文案、图片与历史 ID 全部保留；不重置进行中任务、不隐式发起收费调用。
- 新增确定性策划服务：产品对象、证据快照、结构化概念、VisualBrief 与推荐描述同源生成，规则负责事实边界，模型只做既有落地页理解。
- 行业策略版本化，电商 / 软件 / 旅游 / B2B 主体与场景各自匹配；未知平台在策划阶段拒绝，不静默套用其它平台规则。
- 草案与可投放分开：缺官方商品图 / 真实 UI、规则未官方核验、逐图质检未上线时一律记为草案，等级与计划版本随任务快照归档。
- 量化承诺、源文限定与地区报价受控：未在原文定位的量化表达自动移除，价格条款不进推荐描述，投放国家只取工作区默认值。

**本次优化与更改的功能 / 模块**
- 【新增】素材创作 / 自动创作面板：`frontend/src/pages/AutoCreationPanel.tsx` 展示推荐视觉描述、不超过三条的推荐理由、产品概要、覆盖摘要、结构化概念、交付门、工作区默认值与确认媒体入口；完整策划数据折叠保留，不铺开实现细节。
- 【新增】素材创作 / 模式切换与旧会话迁移：`frontend/src/creationSession.ts` 新增 `mode` / `showAdvanced` / `autoContinue` / `autoStage` / `workspaceDefaults` / `recommendation`，会话版本升为 v3 但 localStorage key 不变；v2 旧会话固定迁移为 `custom` 且迁移结果立即落盘，避免重复追加中断日志。新增 `planVersion()` 与 `updateWorkspaceDefaults()`，关键默认值变化使推荐和确认失效。
- 【新增】后端 / 确定性策划层：`backend/creation_planner.py` 提供 `build_recommendation()` / `build_visual_brief_seed()` / `render_visual_summary()` / `build_structured_concepts()` / `_quality_gate()`；输出 `product_profile`、`visual_brief`、`recommended_visual_summary`、`structured_concepts`、`coverage_summary`、`pricing_gate`、`quality_gate`、`plan_id` / `plan_version`。推荐描述限 60–120 字、按槽位独立限长，保证产品 / 场景 / 价值 / 构图 / 文字区 / 版位六项不因截断丢失。
- 【新增】后端接口：`POST /api/creation-recommendation` 接收既有落地页分析结果、媒体与工作区默认值，返回策划结果；未知平台由 `validate_platform()` 在调用模型前返回 422，不静默降级。
- 【优化】行业适配 / 版本化策略：`backend/industry_profiles.py` 新增 `PROFILE_SCHEMA_VERSION`，每个画像带 `profile_id` / `version` 并纳入计划版本计算；`list_profiles()` 同步下发版本，新增或改动画像会使旧推荐失效。
- 【修复】推荐描述 / 量化与价格承诺（A05 / A07）：源文含 `up to` / 护理模式 / 实验室条件 / 计费周期时，推荐描述改用非量化表达，限定词随结构化概念下发给文案链路；价格与试用条款整段不进描述，地区报价一律不生成。
- 【修复】交付门 / 草案与合格素材分离（N03 / A08 / A15）：`quality_gate` 分别检查产品素材、证据快照、官方规格核验与逐图质检；V4.45 全部自动产出标记 `delivery_grade=draft` 且 `deliverable=false`，草案等级、`plan_id`、`plan_version` 随生成任务 `archive` 快照落库。
- 【优化】自动链路 / 不另造生成系统：`MediaAdStudio.tsx` 在自动模式隐藏复杂配置、改为阶段进度条，用户显式确认后按「文案 → 出图」串联，复用既有 `mediaCopy` / `generation-jobs` / 素材历史链路；失败时清掉待出图标记，避免后续被隐式带出收费任务。
- 【新增】回归测试：`tests/test_auto_creation.py`（24 项断言）覆盖 A01–A08、A10 / A13 / A15 与 N03；`tests/frontend/auto_creation_session.mjs` 通过本地 esbuild 打包并真实执行 `creationSession.ts`，验证默认 auto、旧会话迁移、模式切换与计划版本失效。
- 【优化】前端类型与样式：`api.ts` 新增 `WorkspaceDefaults` / `StructuredConcept` / `CreationRecommendation` 及归档草案字段；`styles.css` 增加模式切换、推荐面板、结构化概念、交付门与进度条样式。

**影响范围**
- 前端：素材创作页新增模式切换与自动面板；定制创作三步工作台保持可用。自动模式只影响新建会话，发布时不重置进行中的定制任务；旧会话一律迁移为 custom。
- 后端：新增 `creation_planner.py` 与 1 条 `/api` 路径（有效 `/api` 路径由 42 条增至 43 条）；`industry_profiles.py` / `routers.py` / `version.py` 有改动。策划层不调用新模型、不改数据库表、不写历史数据。
- 数据：草案等级与计划版本写入生成任务的 `archive` 快照（JSON），不新增列、不改写历史图片、不重新生成或收费。
- 验收口径：本版完成 D1–D3 的**工程路径**，不宣称素材视觉合格或投放效果提升；D4–D6（媒体全覆盖计划、PromptBundle、多阶段持久任务、逐图质检、A09–A20 验收记录）仍为后续期次；官方媒体规格 `SPEC_VERIFIED_ON` 与供应商 `size_verified_on` 仍为空，真实模型与真实投放验证均未执行。
- 权限与部署：沿用既有登录角色与编辑权限；无需数据库迁移、无需管理员轮换口令；回滚只需关闭自动创作入口，资产、计划与任务记录保留。

**验证**
- `python3 tests/run_all.py`：**96 项断言全部通过**（V4.44 既有 72 项 + 本版 24 项），其中前端会话用例由本地 esbuild 打包后以 node 真实执行。
- 后端 `compileall -q backend scripts tests` 通过；`import main` 通过，运行版本 `4.45.0`、有效 `/api` 路径 43 条。
- 前端 `tsc --noEmit` 通过；`vite build` 45 模块 / 279.39 kB JS / 57.21 kB CSS。
- 版本通知锚点：`APP_VERSION=4.45.0` → `release_tag()` = `V4.45`，`get_release_notes()` 首条为本版要点；`prepare_release.py --check` 通过。
- 所有回归在临时 SQLite、临时文件副本与纯函数上执行，强制清空 `DEFAULT_LLM_API_KEY`；未修改生产数据、未产生真实付费模型调用。

**说明 / 默认约定**
- 「可定位原文」仍不等于「商业真实性已审核」；`delivery_grade=draft` 不等于素材质量不合格，但明确不得作为可投放商品广告交付。
- 自动创作的分析、文案、出图复用现有链路与同一证据 / 规格检查；本版不宣称已完成 PromptBundle、多阶段编排、官方规格核验或逐图质检。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。

## V4.46 媒体覆盖计划 + 多阶段编排 + 灰度验收（D4–D6）

**发布日期**：2026-11-10
**变更类型**：新增 / 优化 / 修复 / 发布
**涉及模块**：素材创作平台、前端面板与会话、后端接口、数据模型、策划与编排服务、发版流程、改造追踪、工程文档
**变更摘要**：按《素材创作平台新版验收与自动化创作改造实施方案》v2.0 完成 D4–D6：新增媒体全覆盖计划（`build_coverage_plan` / `_split_batches`）、`PromptBundle` 编译（`compile_prompt_bundle` + 资产角色渲染表）、多阶段持久 `CreationPlan` 编排（状态机 + 版本冻结 + 幂等 + 质检 + 可恢复），并把 A09–A20 验收路径落成可运行回归；灰度开关 `ENABLE_AUTO_CREATION_PLAN` 默认开启，回滚不删列、不破坏既有数据。

**更新要点**
- D4 媒体全覆盖计划：按「平台 × 资产角色 × 尺寸 × 概念」生成所需任务，每个概念完整适配全部版位（不做轮换伪装）；贪心拆子批（≤24 任务 / ≤40MP，父计划保留全部任务不截断）；成本上界 = 图片数×0.05 + 概念数×0.05，预算不足显式标出 `over_budget` 不静默生成。
- D4 `PromptBundle` 编译：按资产角色决定 bake_text / bake_logo / bake_cta；软件真实 UI（app_portrait / fullscreen_portrait / splash_vertical / native_image / banner）不烘焙文字或 CTA，避免「no UI」把产品真实界面误删；bundle 携带 fact_input / concept_input / references / render_spec / post_render / traceability / hashes 可溯源至 64 位哈希。
- D5 `CreationPlan` 持久编排：状态机 `created → analyzing → needs_input / recommendation_ready → platform_confirmed → planning → generating → validating → succeeded / partial / failed / canceled`；版本冻结 `approval_token`，确认时强校验费用授权 ≥ 成本上界；工作区级幂等键 + payload_hash（同键不同内容返回 409），相同输入查到既有计划即返回避免唯一约束冲突（前端刷新重提交）。
- D5 质检与可恢复：供应商失败且为纯背景 → 标记 `draft / needs_revision`；`SPEC_VERIFIED_ON` 为空（官方规则未核验）即便生成成功也记 `draft`；中断恢复按 `plan_id` 重取计划与 job 清单，未知结果绝不自动重发；取消后不可再 confirm / 不可复活。
- D6 灰度与回归：A09–A20 全部落成 `tests/test_d4_d5_d6.py`（32 项断言）——未知平台 A10 拒绝、覆盖只按已选 A11、无轮换伪装 A12、计划版本失效 409（A13）、费用不足 / 0 费拒绝（A14）、草案不计可投放（A15）、幂等冲突 409（A16）、全链路 + 新会话恢复（A17）、中断不自动重发（A18）、取消不可再确认（A19）、manifest 打包不谎报（A20）；灰度开关关闭返回 503、未知平台 422。
- 回归修复：V4.45 `MediaAdStudio` 无条件发送 `s.recommendation.plan_id`，而 V4.46 后端要求该 plan 必须已存在于 `creation_plans` 且已确认，否则 422 中断自动链路；改为仅当 `s.planApproved && s.planId` 才附加 `plan_id / plan_version`，未确认计划走不带计划元数据的降级路径。

**本次优化与更改的功能 / 模块**
- 【新增】后端 / 媒体全覆盖计划：`backend/media_coverage.py` 提供 `build_coverage_plan(recommendation, platforms, concepts, workspace_defaults)`（task / 子批 / 成本上界 / 覆盖报告，`unknown_spec` 显式标注未核验规则任务）、`merge_manifest(plan, job_results)`（D6 / A20 打包 media / concept / role / 缺失报告）、`_split_batches(tasks)`（贪心拆批，父计划保留全部）。
- 【新增】后端 / PromptBundle 编译：`backend/prompt_compiler.py` 提供 `compile_prompt_bundle(concept, brief, references, asset_role, supplier_caps)`（返回 system / task / fact_input / concept_input / references / render_spec / post_render / traceability / hashes）与 `ASSET_ROLE_RENDER` 资产角色渲染表（按角色决定 bake_text / bake_logo / bake_cta）。
- 【新增】后端 / 多阶段编排：`backend/creation_plan_service.py` 提供纯逻辑（`build_plan_doc` / `qa_generation_result`（A15 质检）/ `build_manifest` / `next_stage` / `STAGES` / `TERMINAL`）与 DB CRUD（`create_plan` 幂等 / `set_coverage`（A11）/ `confirm_plan`（A13 A14 冻结 + 费用授权）/ `attach_job` / `finalize` / `get_plan` / `plan_to_dict` / `validate_plan_reference`），未知平台抛 `MediaRuleError`（A10）。
- 【新增】数据模型：`backend/models.py` 新增 `CreationPlan`（creation_plans：plan_id / plan_version / mode / stage / status / analysis_json / recommendation_json / coverage_json / approval_token / fee_authorized / owner_id / history_id / job_ids / manifest_json）；`GenerationJob` 新增 `plan_id` / `plan_version` 两列（幂等 `ensure_schema()` 在建表后 ALTER 补齐，不破坏旧数据）。
- 【优化】后端接口：`backend/routers.py` 新增 5 条 `/api/creation-plans*` 路径（202 创建 / 查询 / coverage / confirm / finalize），含 `_plan_feature_off()` 灰度开关（关时返回 503）；修改 `POST /api/generation-jobs`：携 `plan_id` 时强校验计划引用（版本冲突 409 / 事实改写 422 / 未确认 422），创建后 `attach_job`。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.46.0"`，`ENABLE_AUTO_CREATION_PLAN = True`（灰度开关，回滚时不删列）。
- 【新增】前端类型与接口：`frontend/src/api.ts` 新增 `CreationPlan` 接口（stage / status / coverage{cost_estimate, coverage, report} / approval_token / fee_authorized / job_ids / manifest）与 5 个 plan API（`createCreationPlan` / `getCreationPlan` / `setPlanCoverage` / `confirmPlan` / `finalizePlan`）。
- 【优化】前端会话：`frontend/src/creationSession.ts` 新增 `planId` / `planVersion` / `planApproved` / `planCoverage`，`defaults()` 初始化、`sanitize()` 清洗迁移避免拿旧冻结版本生成。
- 【优化】前端面板：`frontend/src/pages/AutoCreationPanel.tsx` 推荐就绪后自动 `createCreationPlan`（幂等）写入会话并展示 D4 覆盖计划（总任务 / 子批 / 资产角色 / 成本上界 / 规则核验 / over_budget 告警）；`confirmAndGenerate` 改为 async：先建计划 → `confirmPlan(planId, max(costUpper, 0.01))` 冻结 + 费用授权 → 成功才把计划写入会话再触发生成，失败回退不带计划元数据；`MediaAdStudio.tsx` 出图 payload 仅在 `s.planApproved && s.planId` 时附加 `plan_id / plan_version`。
- 【新增】回归测试：`tests/test_d4_d5_d6.py`（32 项断言）覆盖 A09–A20 与 D6 路由；`tests/test_auto_creation.py::test_22` 更新为校验计划有条件附加（V4.46 回归修复）。

**影响范围**
- 前端：自动创作面板新增「已按所选平台建立自动创作计划」提示与 D4 覆盖计划展示；确认生成前先冻结计划并授权费用，未授权不生成。复用既有生成链路，不另造生成系统。
- 后端：新增 `media_coverage.py` / `prompt_compiler.py` / `creation_plan_service.py` 与 5 条 `/api` 路径（有效 `/api` 路径由 43 条增至 56 条）；`models.py` / `job_service.py` / `routers.py` / `version.py` 有改动；`ensure_schema()` 幂等建表 + ALTER 补齐列，旧库不重建、不丢数据。
- 数据：`CreationPlan` 持久化计划与 manifest；`GenerationJob` 增加 `plan_id` / `plan_version` 关联列；回滚时仅关闭灰度开关，列与记录保留。
- 验收口径：D4–D6 完成**工程路径 + 模拟回归**；官方媒体规格 `SPEC_VERIFIED_ON` 与供应商 `size_verified_on` 仍为空，真实模型与真实投放验证均未执行；A09–A20 登记为「模拟回归通过，真实模型 / 真实投放 / 人工视觉核验未验证」。
- 权限与部署：沿用既有登录角色与编辑权限；无需管理员轮换口令；灰度回滚只需置 `ENABLE_AUTO_CREATION_PLAN = False`，资产、计划与任务记录保留。

**验证**
- `python3 tests/run_all.py`：**128 项断言全部通过**（V4.45 既有 96 项 + 本版 32 项），其中前端会话用例由本地 esbuild 打包后以 node 真实执行（test_23）。
- 后端 `compileall -q backend scripts tests` 通过；`import main` 通过，运行版本 `4.46.0`、有效 `/api` 路径 56 条。
- 前端 `tsc --noEmit` 通过；`vite build` 45 模块 / 282.87 kB JS / 57.21 kB CSS。
- 版本通知锚点：`APP_VERSION=4.46.0` → `release_tag()` = `V4.46`；`prepare_release.py --check` 通过。
- 所有回归在临时 SQLite、临时文件副本与纯函数上执行，强制清空 `DEFAULT_LLM_API_KEY`；未修改生产数据、未产生真实付费模型调用。

**说明 / 默认约定**
- `SPEC_VERIFIED_ON` 与 `size_verified_on` 仍为空，按文档边界**不得宣称符合平台官方规范**；本版 `ASSET_ROLE_RENDER` 的「不烘焙文字 / CTA」仅保护软件真实 UI 不被 no UI 误删，不构成官方规格核验。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。

## V4.47 系统日志 · 账号登录日志（登录账号 / IP / 时间全量记录）

**发布日期**：2026-11-11
**变更类型**：新增 / 修复 / 优化
**涉及模块**：系统设置（日志）、后端鉴权与接口、数据模型、前端页面、发版流程、工程文档
**变更摘要**：排查并修复「系统设置 → 日志」模块的既有问题——此前登录动作**完全没有被记录**，审计日志只覆盖配置变更 / 账号操作 / 提示词修改，且不含任何账号登录或 IP 信息。本版补全全部账号的登录日志：成功与失败尝试均落库，每条记录**登陆账号名称、登陆 IP 地址、登陆时间**三项，并在前端「日志」页拆分为「审计日志 / 登录日志」两个标签页。

**更新要点**
- 修复既有缺陷：原 `POST /api/auth/login` 只返回 token，不写任何日志，导致「全部账号的登录」无从追溯；现成功与失败分支均写入登录日志。
- 登录日志字段与需求一一对应：`username`=登陆账号名称（成功为系统内 username，失败为尝试输入的邮箱 / 用户名）、`ip`=登陆 IP 地址、`created_at`=登陆时间；另存 `user_agent` 与 `success` / `detail`（失败原因）。
- 真实客户端 IP 取值顺序：`X-Forwarded-For` 第一段 → `X-Real-IP` → 直连 socket（适配 Cloudflare Tunnel + Caddy 反向代理场景，避免只记录网关内网地址）。
- 「日志」页拆分为「审计日志」与「登录日志」标签页：登录日志表头为「登陆时间 / 登陆账号名称 / 登陆 IP 地址 / 状态 / 详情」，并提供「仅成功 / 仅失败」筛选；审计日志保留原样。
- 登录日志仅管理员可读（`GET /api/login-logs` 复用 `require_roles("admin")`），与审计日志权限一致；失败登录同样记入，便于安全排查与暴力破解识别。

**本次优化与更改的功能 / 模块**
- 【新增】数据模型：`backend/models.py` 新增 `LoginLog`（`login_logs` 表：id / username / ip / user_agent / success / detail / created_at，username 与 ip 建索引）；`ensure_schema()` 通过 `Base.metadata.create_all` 幂等建表，旧库不重建、不丢数据。
- 【新增】后端登录日志：`backend/routers.py` 新增 `_client_ip(request)`（取真实客户端 IP）与 `_log_login(db, username, request, success, detail)`（异常不阻断登录主流程）；`login()` 改为接收 `Request`，在成功与失败分支各调用一次 `_log_login`。
- 【新增】后端接口：`backend/routers.py` 新增 `GET /api/login-logs`（admin 可读，支持 `limit` 与 `success` 过滤，上限 2000 防滥用）；同时对既有 `GET /api/audit-logs` 增加 `limit` 上限（1–2000）加固。
- 【优化】前端类型与接口：`frontend/src/api.ts` 新增 `LoginLog` 接口与 `loginLogs(limit, success?)` 方法。
- 【优化】前端页面：`frontend/src/pages/Logs.tsx` 重写为标签页式（审计 / 登录），登录日志表含账号 / IP / 状态（成功绿标、失败红标）/ 详情，支持关键词（账号 / IP）与「仅成功 / 仅失败」筛选；`frontend/src/App.tsx` 日志菜单描述同步更新。
- 【新增】回归测试：`tests/test_login_logs.py`（5 项断言）覆盖成功登录含账号 / IP / 时间、失败登录记录、匿名访问 401、X-Forwarded-For 取真实 IP、停用账号尝试亦记录。

**影响范围**
- 前端：「系统设置 → 日志」新增「登录日志」标签页；旧审计日志功能不受影响。
- 后端：新增 `LoginLog` 模型与 1 条 `/api` 路径（有效 `/api` 路径由 56 条增至 57 条）；`routers.py` 改动登录逻辑；`ensure_schema()` 自动建 `login_logs` 表，旧库不重建、不丢数据。
- 数据：登录日志独立落库，不写入审计日志、不改写用户表；回滚时该表保留。
- 权限与部署：沿用既有登录角色与鉴权；无需数据库迁移脚本（自描述建表），无需管理员轮换口令。

**验证**
- `python3 tests/run_all.py`：**133 项断言全部通过**（V4.46 既有 128 项 + 本版 5 项），0 失败 0 错误 0 跳过。
- 后端 `compileall -q backend scripts tests` 通过；`import main` 通过，运行版本 `4.47.0`、有效 `/api` 路径 57 条。
- 前端 `tsc --noEmit` 通过；`vite build` 45 模块 / 284.79 kB JS / 57.21 kB CSS。
- `python3 scripts/prepare_release.py --check` 通过（系统版本 == CHANGELOG 最新版本且含「更新要点」）。
- 所有回归在临时 SQLite 与 TestClient 上执行，强制清空 `DEFAULT_LLM_API_KEY`；未修改生产数据、未产生真实付费模型调用。

**说明 / 默认约定**
- 登录日志覆盖「账号 + IP + 时间」三项，满足本需求的追溯与合规要求；更细的会话级行为（登出、超时、操作轨迹）属后续增强。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。

## V4.48 新版通知可靠性修复：版本内容强制随代码同步

**发布日期**：2026-11-11
**变更类型**：修复 / 优化 / 新增
**涉及模块**：新版通知、发版流程、后端接口、系统版本
**变更摘要**：修复「新版通知」模块在部署环境中可能因缺少 CHANGELOG.md / git 而展示陈旧或空内容的问题；将版本通知改造为「随代码发布的权威数据文件（release_notes_data.py）」驱动，并由发版校验（`prepare_release.py --check`）强制要求每个系统版本都生成同步的发布数据，从而实现「每次代码更新都总结更新内容并同步到新版通知」。

**更新要点**
- 根因：原「新版通知」运行期直接解析仓库根目录 CHANGELOG.md，并依赖 git 生成兜底摘要；部署环境若未随包发布 CHANGELOG.md 或不含 .git，最新版本内容会缺失或被弱兜底内容替代，表现为「近期更新未整理发布」。
- 权威来源改为 `backend/release_notes_data.py`：随代码发布的版本通知数据，接口优先读取，部署环境无论是否有 CHANGELOG.md / git 都能展示最新版本；开发期若 CHANGELOG 已含更新版本则优先实时解析，避免陈旧 CHANGELOG 覆盖已发布的新版本。
- 发版闭环：`prepare_release.py --sync` 在整理 CHANGELOG 段落的同时，自动重建 `release_notes_data.py`；`--check` 新增校验「发布数据最新版本 == 系统版本」并校验当前版本已包含，缺失即拦截发布。
- 兜底仍保留：若某版本在两个来源都缺失，仍由 `auto_note()` 生成一条明确标注「自动同步」的通知，但发版校验会强制要求补写，杜绝静默兜底的弱内容。
- 同步机制文档化：README 补充「每次系统更新 → 运行 `--sync` → 通知随代码入库 → 部署即包含」的标准动作，并新增 `tests/test_release_notes.py` 回归保护接口返回当前版本且有非空要点。

**本次优化与更改的功能 / 模块**
- 【修复】后端 / 新版通知：`backend/release_notes.py` 的 `get_release_notes()` 改为以内置 `release_notes_data.NOTES` 为权威来源，CHANGELOG 仅在版本更新时作为实时覆盖；`auto_note()` 保留为最终兜底。
- 【新增】部署发布数据：`scripts/prepare_release.py` 新增 `write_data_file()`，将 CHANGELOG 全部版本整理为 `backend/release_notes_data.py`（仅含前端消费的版本号 / 标题 / 日期 / 摘要 / 要点 / 类型 / 模块 / 自动标记字段）。
- 【优化】发版校验：`scripts/prepare_release.py --check` 增加发布数据版本一致性校验（缺失 / 落后 / 未含当前版本均报错拦截），并打印「发布数据最新版本」。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.48.0"`。
- 【新增】回归测试：`tests/test_release_notes.py` 覆盖接口返回当前版本（非自动生成）且要点非空、`prepare_release.py --check` 通过、内置发布数据首条为当前版本。

**影响范围**
- 前端：「系统设置 → 新版通知」读取的数据来源不变（仍经 `/api/system/release-notes`），但后端现在优先使用随代码发布的权威数据，部署更可靠。
- 后端：新增 `backend/release_notes_data.py`（生成文件，随代码提交）；有效 `/api` 路径数不变（仍为 57 条）。
- 发版流程：每次版本更新须运行 `python3 scripts/prepare_release.py --sync`，该命令会同时更新 CHANGELOG 与发布数据；CI / pre-push 的 `--check` 会拦截未同步的发布。
- 兼容：未部署 `release_notes_data.py` 的旧构建回退到 CHANGELOG 实时解析，行为不退化。

**验证**
- `python3 tests/run_all.py`：原有 133 项断言全部通过，新增 `tests/test_release_notes.py` 覆盖接口与发版校验。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.48 == 系统版本 V4.48，校验通过。
- 后端 `compileall -q backend scripts tests` 通过；`import main` 通过，运行版本 `4.48.0`、有效 `/api` 路径 57 条。
- 前端 `tsc --noEmit` 通过；`vite build` 45 模块 / 284.79 kB JS / 57.21 kB CSS。

**说明 / 默认约定**
- 「新版通知」现在以随代码发布的 `release_notes_data.py` 为权威来源，彻底摆脱对部署环境 CHANGELOG.md / git 的依赖；CHANGELOG.md 仍是人类可读的完整归档。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。

## V4.50 创意工作台：独立自动化创意创作中枢

**发布日期**：2026-11-11
**变更类型**：新增
**涉及模块**：创意工作台、全球创意分析、前端导航、后端接口、提示词体系
**变更摘要**：新增独立的一级模块「创意工作台」，面向落地页 / 官网 / 应用的自动化创意素材创作。包含「创意工作台」（对话式自动创作：输入链接或产品信息 → 选择媒体平台 → 大模型分析产品并总结框架 → 自动生成推广图片 → 放大查阅与下载）与「全球创意分析」（参考素材 → 大模型归类创意风格/类型 → 产出可复用图片/视频提示词模板）。与现有「素材创作平台」并存，不替换。

**更新要点**
- 新增一级菜单「创意工作台」（与「素材创作平台」并列），含「创意工作台」「全球创意分析」两个子模块；权限沿用编辑/管理角色，且保持「素材创作」常驻挂载的既有会话持久化不变。
- 创意工作台采用对话式自动创作流：用户输入模块 + 对话/调整区 + 成果区；产品分析调用既有 `POST /api/landing-analysis`（LLM 8 字段推理），媒体规格沿用既有 `media-rules` / `media-platforms`，图片生成复用 `POST /api/generation-jobs`（服务端持久任务，含历史落库与打包下载）。
- 全球创意分析为本期新增的 LLM 驱动子模块：新增 `POST /api/creative-analysis`（参考链接/文本 → 大模型归类创意类型并产出可复用提示词模板，结果落库）、`GET /api/creative-analysis`（列表）、`GET /api/creative-analysis/{id}`（详情）；提示词可复制沉淀到「素材提示词」库复用。
- 视频生成按既定决策本期预留为「下期待生成」节点，不阻断图片主流程（用户已确认：图片优先、视频预留）。

**本次优化与更改的功能 / 模块**
- 【新增】后端模型：`backend/models.py` 新增 `CreativeAnalysis` 表（creative_analyses：owner/title/inputs_json/result_json/model_info）。
- 【新增】后端端点：`backend/routers.py` 新增 `/api/creative-analysis`（POST 分析+落库、GET 列表、GET 详情），复用 `providers.get_llm_with_info` 调用已配置大模型并回传实际模型快照。
- 【新增】前端页面：`frontend/src/pages/CreativeWorkbench.tsx`（对话式自动创作）、`frontend/src/pages/CreativeAnalysis.tsx`（全球创意分析）。
- 【优化】前端导航：`frontend/src/App.tsx` 新增「创意工作台」分组（compass/atom 图标）与两个 Tab，与「素材创作平台」「系统设置」并存。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.50.0"`；`frontend/src/api.ts` 新增 `creativeAnalyze / creativeAnalyses / creativeAnalysis`。
- 【新增】回归测试：`tests/test_creative_analysis.py`（5 项：分析落库、列表、详情、缺参拦截、鉴权）。

**影响范围**
- 前端：新增 2 个页面与 1 个一级菜单，既有「素材创作平台」「系统设置」不受影响。
- 后端：新增 1 张表（随 `ensure_schema` 幂等建表）、3 个端点；有效 `/api` 路径数 +3；图片生成仍走既有 generation-jobs，不新增外部依赖。
- 部署：新增表随 `ensure_schema()` 自动创建，旧库无需手动迁移；发布数据随 `--sync` 重建。

**验证**
- `python3 tests/run_all.py`：运行 141 项，失败 0、错误 0、跳过 0（含新增 5 项创意分析用例）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.50 == 系统版本 V4.50，校验通过。
- 后端 `import main` 通过，运行版本 `4.50.0`；前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 297.28 kB JS / 58.39 kB CSS。

**说明 / 默认约定**
- 创意工作台复用既有「落地页分析 / 媒体规则 / 生成任务 / 素材历史 / 提示词」能力，是统一创作中枢而非重复实现；全自动对话式创作沿用既有大模型配置，所有分析/生成均调用已配置模型。
- 视频生成节点本期预留，下期接入文生视频模型后打通；媒体规格数值以各平台上架政策为准。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。

## V4.51 创意工作台：修复素材未展示 + 新增右侧滑出过程面板

**发布日期**：2026-11-11
**变更类型**：修复 / 优化
**涉及模块**：创意工作台（前端）
**变更摘要**：修复 V4.50 创意工作台「显示已完成但素材图片为空」的问题；并将分析过程与创作过程从主区卡片迁移至可显示/隐藏的右侧滑出面板，仅保留必要信息，去除冗余陈述。

**更新要点**
- 【修复】创意工作台生成流程轮询到终态后，优先读取 `job.result.images`（服务端落库前已写入 `result_json`，无时序竞态），`GET /api/creative-assets` 作为兜底；原实现仅依赖 `creative-assets` 查询，存在「任务状态已 succeeded 但 CreativeAsset 尚未提交」的竞态窗口，导致素材列表为空、界面显示「尚未生成素材」。修复后素材按平台正确落盘到右侧面板与成果区。
- 【新增】右侧滑出过程面板「分析 & 创作过程」：默认展开，可点击右上角按钮或面板内「×」收起、点击遮罩关闭；面板分两块——「分析过程」（行业/类型/对象/优势 + 推荐媒体与理由）、「创作过程」（每个媒体平台的任务状态、进度条、生成缩略图与单张下载）。仅展示必要结构化信息，不堆砌对话陈述。
- 【新增】生成完成轻量 toast 反馈「图片已生成 N 张（平台）」；成果区保留「打包下载全部」与「新的创作」。

**本次优化与更改的功能 / 模块**
- 【修复】`frontend/src/pages/CreativeWorkbench.tsx`：`generate()` 改为读取 `st.result.images` + `creativeAssets` 兜底，按平台维护 `jobs` 状态，统一合并到 `assets`；轮询上限 40 → 80 次。
- 【优化】`frontend/src/pages/CreativeWorkbench.tsx`：主区改为对话/输入单卡片；新增右侧 `cw-drawer` 滑出面板、`cw-toggle` 切换按钮、`cw-backdrop` 遮罩、`cw-toast` 提示。
- 【优化】`frontend/src/styles.css`：新增 `.cw-drawer / .cw-toggle / .cw-backdrop / .cw-job / .cw-thumbs / .cw-toast` 等样式（含滑入动画与进度条）。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.51.0"`。

**影响范围**
- 前端：仅改动创意工作台页面与样式；既有「素材创作平台」「全球创意分析」「系统设置」不受影响。
- 后端：无接口变更，版本号随发布数据同步。

**验证**
- `python3 tests/run_all.py`：运行 141 项，失败 0、错误 0、跳过 0（前端改动不影响后端回归）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.51 == 系统版本 V4.51，校验通过。
- 前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 299.71 kB JS / 60.94 kB CSS。

**说明 / 默认约定**
- 右侧面板默认展开，便于核对分析与创作进度；可随时收起以扩大对话区。视频节点仍为「下期待生成」预留。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。

## V4.52 创意工作台重构：四步引导流程 + 创意策略路线规划 + 历史库

**发布日期**：2026-11-11
**变更类型**：重构 / 新增
**涉及模块**：创意工作台（前端 + 后端）
**变更摘要**：按设计方案将「创意工作台」重做为「输入 → 产品分析 → 创意策略 → 生成成果」四步引导流程；新增由大模型驱动的「创意策略 / 路线规划」（为每个所选媒体平台规划创意概念 / 切入角度 / 视觉风格 / 文案方向 / 文生图方向），并新增「历史库」子标签沉淀每次创作会话，补齐原需求中缺失的「创意路线规划」与「历史库」两项。

**更新要点**
- 【新增·后端】`CreativePlan` 数据模型（`creative_plans` 表：分析结论 / 所选平台 / 生成开关 / 路线 JSON / 状态 / 素材数 / 关联历史）。
- 【新增·后端】`POST /api/creative-plan`：接收产品分析 + 所选平台，调用已配置「分析」大模型，为每平台产出一条创意路线（routes 数量与平台一一对应，缺失平台自动补齐），落库返回 `id`。
- 【新增·后端】`GET /api/creative-plan`（列表）、`GET /api/creative-plan/{id}`（详情）、`PATCH /api/creative-plan/{id}`（生成中 / 完成后回填状态与素材数）。
- 【重构·前端】`CreativeWorkbench.tsx` 改为四步步骤条引导：① 输入（链接/信息 + 媒体多选 + 图片/视频）② 产品分析（8 字段框架卡片）③ 创意策略（每平台路线卡片，概念/角度/视觉/文案/提示词可微调）④ 生成成果（自动出图 + 素材画廊）。
- 【新增·前端】「历史库」子标签：列表展示过往创意策略（标题 / 平台 / 素材数 / 日期 / 状态），支持「查看 / 复用」一键回填到创作流程。
- 【保留】右侧滑出过程面板（分析 & 创作过程）继续展示分析框架、创意策略摘要与各平台生成进度 / 缩略图；可显示/隐藏。
- 【接线】生成阶段将每平台路线的创意概念 / 角度 / 视觉风格 / 文案方向注入 `style_opts.creative_direction / content_style`，使「策略」真正驱动出图，而非仅作展示。

**本次优化与更改的功能 / 模块**
- 【后端】`backend/models.py`：新增 `CreativePlan`；`backend/schemas.py`：新增 `CreativeRoute` / `CreativePlanRequest` / `CreativePlanResult`；`backend/routers.py`：新增 4 个创意策略端点 + `_CREATIVE_PLAN_SYS` 提示词 + `_cp_to_dict`。
- 【前端】`frontend/src/api.ts`：新增 `creativePlan / updateCreativePlan / creativePlans / creativePlanDetail`；`frontend/src/pages/CreativeWorkbench.tsx`：四步流程 + 历史库重写；`frontend/src/styles.css`：新增步骤条 / 子标签 / 路线卡片 / 画廊 / 历史列表样式。
- 【测试】`tests/test_creative_plan.py`：6 项（创建/列表/详情/PATCH/缺参拦截/鉴权）。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.52.0"`。

**影响范围**
- 前端：仅改动创意工作台页面与样式；「素材创作平台」「全球创意分析」「系统设置」不受影响。
- 后端：新增模型与端点，幂等迁移（仅新建表），不删除任何既有列或接口。

**验证**
- `python3 tests/run_all.py`：运行 147 项，失败 0、错误 0、跳过 0（141 + 新增 6）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.52 == 系统版本 V4.52，校验通过。
- 前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 304.86 kB JS / 64.19 kB CSS。

**说明 / 默认约定**
- 创意策略与产品分析均调用「分析 / 文案」已配置大模型；无模型时走 Mock 兜底，routes 可能为空但记录正常创建。
- 视频节点仍为「下期待生成」预留；历史库记录每次工作台会话，生成完成后回填素材数。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。

## V4.53 创意工作台：按 Figma 设计稿重建（双栏布局 + 三步流程 + 项目简报）

**发布日期**：2026-11-11
**变更类型**：重构 / 新增
**涉及模块**：创意工作台（前端 + 后端）
**变更摘要**：依据 Figma「创意工作台」设计稿重写整体界面与交互。采用「左主区 + 右固定项目简报」双栏布局；顶部「创意工作台 + 自动保存 / 搜索 / + 新建项目」；主区以「01 解析产品 → 02 规划创意 → 03 批量生成」三步指示串起流程；产品分析以「行业 / 核心人群 / 购买动机 / 价格带」四盒 + 一句话定位呈现；创意规划以 3 张可选路线卡（A/B/C，含概念 / 说明 / 标签）呈现；生成成果以「素材卡（比例徽标 / 标题 / 标签 / 品牌 / 规格 / 下载 / 批量打包）」呈现。后端新增设计对齐的分析与路线端点，复用既有生成链路出图。

**更新要点**
- 【新增·后端】`POST /api/cw/analyze`：产品链接 / 文本 + 平台 → 调用已配置「分析」大模型，产出「一句话定位 + 4 分析盒（行业 / 核心人群 / 购买动机 / 价格带）+ 项目简报（推广目标 / 目标受众 / 核心卖点）」，落库为 `CreativePlan` 草稿并返回 `id`；无模型时给出可演示默认结构。
- 【新增·后端】`POST /api/cw/routes`：分析结论 + 简报 + 平台 → 大模型规划 3 条差异化创意概念路线（key A/B/C，含 name / description / tags / angle），写回 `CreativePlan.routes_json`。
- 【重构·前端】`CreativeWorkbench.tsx` 完全重做为设计稿布局：双栏、顶部操作栏、三步指示、各状态（空 / 分析中进度卡 / 分析完成 + 3 路线卡 / 生成中 / 成果卡）、右侧「项目简报」面板（当前项目 / 推广目标 / 目标受众 / 核心卖点 / 生成计划 / AI 提示）。
- 【新增·前端】「历史」弹窗复用 `creative-plan` 列表 / 详情 / PATCH，沉淀并支持「查看 / 复用」过往方案。
- 【接线】生成阶段沿用既有 `generation-jobs` + `media-rules` 链路，将所选创意路线的「概念 / 角度 / 标签」注入 `style_opts` 驱动出图，并优先读取 `job.result.images`（无竞态）展示成果卡；视频节点仍为「下期待生成」预留。

**本次优化与更改的功能 / 模块**
- 【后端】`backend/schemas.py`：新增 `CWAnalyzeRequest / CWAnalysisResult / CWRoutesRequest / CWRoute / CWRoutesResult`；`backend/routers.py`：新增 `POST /api/cw/analyze`、`POST /api/cw/routes` 与提示词 `_CW_ANALYZE_SYS` / `_CW_ROUTES_SYS`，复用 `CreativePlan` 存储。
- 【前端】`frontend/src/api.ts`：新增 `cwAnalyze / cwRoutes`；`frontend/src/pages/CreativeWorkbench.tsx`：设计稿重建；`frontend/src/styles.css`：新增双栏 / 步骤条 / 进度卡 / 路线卡 / 成果卡 / 简报侧栏 / 历史弹窗等样式（含 980px / 720px 响应式）。
- 【测试】`tests/test_cw.py`：5 项（分析落库 / 路线 / 缺参拦截 / 历史列表 / 鉴权）。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.53.0"`。

**影响范围**
- 前端：仅改动创意工作台页面与样式；「素材创作平台」「全球创意分析」「系统设置」不受影响。
- 后端：新增 2 个端点，复用 `CreativePlan` 模型与既有生成 / 历史链路，不删除任何既有列或接口（V4.52 的 `creative-plan` 端点与 `test_creative_plan.py` 一并保留）。

**验证**
- `python3 tests/run_all.py`：运行 152 项，失败 0、错误 0、跳过 0（147 + V4.52 6 + 新增 5）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.53 == 系统版本 V4.53，校验通过。
- 前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 307.51 kB JS / 76.72 kB CSS。

**说明 / 默认约定**
- 产品分析与创意路线均调用「分析」已配置大模型；无模型时走 Mock 兜底，端点仍 200 落库并给出可演示默认结构。
- 设计稿为局部截图（仅 4 屏），未覆盖全部交付细节；本版以「界面布局 / 三步流程 / 项目简报面板」对齐设计稿，核心分析 / 路线 / 生成能力保持不变。
- 四种状态分开记录：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌。

## V4.54 创意工作台：界面优化（标题化头部 + 常驻输入 + 滑出分析面板 + 灯箱）

**发布日期**：2026-11-11
**变更类型**：优化 / 重构（UI）
**涉及模块**：创意工作台（前端）
**变更摘要**：按 5 项优化点重构创意工作台交互布局。① 顶部仅保留「创意工作台」菜单标题，删除「自动保存 / AI CREATIVE COPILOT」等冗余文案；② 输入模块常驻展示用户链接 / 产品信息，贯穿整个生成流程；③ 产品分析 → 创意策略收进右侧滑出面板，按需点击查阅；④ 生成成果展示在输入框下方，呈现图片 / 视频素材、尺寸规格与文案内容；⑤ 素材支持批量下载，且可单独点击放大查阅（灯箱）。

**更新要点**
- 【优化·前端】顶部仅保留菜单标题，移除绿点「自动保存」、AI COPILOT 横幅等说明性文案；保留「分析 & 创意策略 / 历史 / 新建项目」功能入口（置于输入卡内）。
- 【优化·前端】输入卡片常驻主区顶部，生成过程中持续展示链接与所选投放平台，便于随时核对。
- 【重构·前端】原正文「产品分析 + 3 条创意路线」整体迁入右侧滑出抽屉（`cwb-drawer`），点击「分析 & 创意策略」或分析中自动展开；正文仅保留输入与成果。
- 【优化·前端】生成成果区位于输入框下方：资产卡新增「文案内容」（headline / sub / CTA）、视频类型识别与播放、比例徽标、尺寸规格；支持全选 / 批量打包下载。
- 【新增·前端】单素材放大灯箱（`cwb-lightbox`）：点击图片 / 视频或「放大」按钮查看大图、规格与文案，并可单独下载；ESC / 点遮罩关闭。
- 【修复·前端】修复「投放平台」选择器不显示、点击「开始分析」报「请至少选择一个媒体平台」的问题：`GET /api/media-platforms` 返回的是平台数组（非 `{ platforms: [...] }`），原代码读取 `d?.platforms` 始终为空导致芯片不渲染；现兼容数组 / 对象两种结构，并在接口异常时回落到 Meta/Google/Unity/Adsterra 默认清单，默认预选首个平台。

**本次优化与更改的功能 / 模块**
- 【前端】`frontend/src/pages/CreativeWorkbench.tsx`：按 5 项要求重写（头部 / 常驻输入 / 滑出面板 / 成果区 / 灯箱）；`frontend/src/styles.css`：新增标题化头部、常驻输入操作行、`.cwb-results`、`.cwb-drawer*` 滑出面板、`.cwb-lightbox*` 灯箱、`.cwb-copy` 文案块等样式（含 980px 响应式）。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.54.0"`。

**影响范围**
- 前端：仅改动创意工作台页面与样式；后端接口与数据模型未改动（沿用 V4.53 的 `cw/analyze`、`cw/routes`、`generation-jobs`、`creative-assets`、`creative-plan`）。
- 后端：无新增 / 删除接口。

**验证**
- 前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 308.64 kB JS / 81.36 kB CSS。
- `python3 tests/run_all.py`：运行 152 项，失败 0、错误 0、跳过 0（沿用 V4.53，无新增后端用例）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.54 == 系统版本 V4.54，校验通过。

**说明 / 默认约定**
- 滑出面板中的「确认并生成」沿用 V4.53 路线选择逻辑；生成后在输入框下方即时沉淀素材，可随时重开面板核对分析 / 策略。
- 视频素材：当前生成链路仅产出图片，资产卡已做视频类型识别与播放支持，待后端视频节点接入即可生效。

## V4.55 创意工作台：分析结果 / 创意路线 / 素材成品 三段式正文流

**发布日期**：2026-11-11
**变更类型**：优化（UI 布局）
**涉及模块**：创意工作台（前端）
**变更摘要**：将「产品分析完成」与「为你规划了 N 条创意路线」从右侧滑出面板移回正文，收入输入框下方的连续区块；生成素材结果展示在创意路线下方。分析后「分析 + 路线」一直常驻显示，直到用户开启新创作，便于在同一视图直观比对分析结论、创意路线与成品素材。同时移除右侧滑出面板。

**更新要点**
- 【优化·前端】原 V4.54 的右侧滑出面板（`.cwb-drawer` / `.cwb-backdrop`）整体移除；分析进度卡、产品分析四盒 + 简报、3 条创意路线卡片与「确认并生成」按钮移至正文「`.cwb-strategy`」区块。
- 【优化·前端】正文垂直流定为：① 常驻输入卡（链接 + 投放平台）→ ② `.cwb-strategy`（分析中显示进度卡；分析后显示「产品分析完成」+「为你规划了 N 条创意路线」并常驻）→ ③ `.cwb-results`（素材图片 / 视频 + 尺寸规格 + 文案，位于创意路线下方）。
- 【优化·前端】输入卡操作行移除「分析 & 创意策略」入口按钮（内容已在正文常驻）；保留「历史 / 新建项目」。
- 【修复·前端】`.cwb-strategy-empty` 复用既有 `.cwb-drawer-empty` 的空状态样式；`analyze()` / `loadPlan()` 不再自动展开抽屉；ESC 仅关闭灯箱。

**本次优化与更改的功能 / 模块**
- 【前端】`frontend/src/pages/CreativeWorkbench.tsx`：删除 `drawerOpen` 状态与抽屉 JSX；在 `cwb-main` 内输入框与成果区之间插入 `.cwb-strategy`（复用原抽屉内的分析 / 路线 JSX）；`generate()` 在路线区块内触发，素材沉淀于其下。`frontend/src/styles.css`：新增 `.cwb-strategy` 容器样式（flex 纵向、间距、首段去 margin-top）。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.55.0"`。

**影响范围**
- 前端：仅创意工作台页面与样式；后端接口与数据模型未改动（沿用 `cw/analyze`、`cw/routes`、`generation-jobs`、`creative-assets`、`creative-plan`）。
- 后端：无新增 / 删除接口。

**验证**
- 前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 308.26 kB JS / 81.49 kB CSS。
- `python3 tests/run_all.py`：运行 152 项，失败 0、错误 0、跳过 0（纯前端改动，无新增后端用例）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.55 == 系统版本 V4.55，校验通过。

**说明 / 默认约定**
- 「分析 + 创意路线」区块在 `cw` 存在且非分析中时持续显示；点「新的创作」reset 后回到空状态提示。
- 视频素材：当前生成链路仅产出图片，资产卡已做视频类型识别与播放支持，待后端视频节点接入即可生效。

## V4.56 创意工作台：分析进度条归位 + 右侧「项目简报」结果面板

**发布日期**：2026-11-11
**变更类型**：优化（UI 布局）
**涉及模块**：创意工作台（前端）
**变更摘要**：按需求将「分析进度条」从任何面板中移出，直接显示在创意工作台输入框下方（紧接输入卡）；同时重新引入右侧「项目简报」面板，但其定位严格限定为「分析结果展示」——仅展示推广目标、目标受众、核心卖点、产品定位等结果内容，可收缩 / 展开，且**不展示流程进度、选项或操作按钮**。正文保留「分析 → 路线 → 成品」三段流，路线选择与生成操作仍在正文内完成。

**更新要点**
- 【优化·前端】分析进度条（`.cwb-progress-card`）从 `.cwb-strategy` 区块内移出，改为紧跟输入卡下方、以独立块渲染（仅 `view === 'analyzing'` 时显示），明确「输入框下方、不在面板内」。
- 【优化·前端】重新引入右侧 `.cwb-brief`「项目简报」面板：仅含「当前项目 / 推广目标 / 目标受众 / 核心卖点 / 产品定位」只读结果；新增 `briefOpen` 状态与头部「›」收起按钮、收起态「‹ 项目简报」竖排展开标签（`.cwb-brief-tab`），可随时收缩。
- 【优化·前端】正文 `.cwb-strategy` 的「产品分析完成」区块移除与右侧面板重复的「推广目标 / 受众 / 卖点」子块（`.cwb-brief-extra`），只保留摘要 + 四盒（行业 / 核心人群 / 购买动机 / 价格带），避免信息冗余；路线选择卡片与「确认并生成」按钮仍在正文，符合「面板不展示选项 / 操作」的界定。
- 【优化·前端】面板内容来源与正文章节一致（`cw?.brief` / `cw?.boxes`），切换路线 / 重新分析时自动同步；面板仅在 `cw` 存在时渲染，无分析结论前不出现。

**本次优化与更改的功能 / 模块**
- 【前端】`frontend/src/pages/CreativeWorkbench.tsx`：新增 `briefOpen` 状态；进度卡上移至输入卡下方；删除正文 `.cwb-brief-extra`；在 `cwb-main` 之后新增可收缩的 `.cwb-brief` 简报面板（含头部收起按钮与收起态竖排标签）。`frontend/src/styles.css`：新增 `.cwb-brief-body`、`.cwb-brief-pos`、`.cwb-brief-toggle`、`.cwb-brief-tab` 样式（面板沿用既有 `.cwb-brief*` / `.cwb-sell` / `.cwb-bchip`）。
- 【优化】系统版本：`backend/version.py` 升 `APP_VERSION = "4.56.0"`。

**影响范围**
- 前端：仅创意工作台页面与样式；后端接口与数据模型未改动（沿用 `cw/analyze`、`cw/routes`、`generation-jobs`、`creative-assets`、`creative-plan`）。
- 后端：无新增 / 删除接口。

**验证**
- 前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 309.21 kB JS / 82.30 kB CSS。
- `python3 tests/run_all.py`：运行 152 项，失败 0、错误 0、跳过 0（纯前端改动，无新增后端用例）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.56 == 系统版本 V4.56，校验通过。

## V4.58 创意工作台：统一分析来源（B2·消除二次模型理解）

**发布日期**：2026-11-12
**变更类型**：缺陷修复（后端契约 + 前端数据源统一）
**涉及模块**：创意工作台（前端 CreativeWorkbench / 后端 cw/analyze / schemas）
**变更摘要**：依据《创意工作台专项评估与改造实施方案 V4.56》「问题排查」P0#3，确认 `cwAnalyze` 不返回 `analysis` 字段、前端在 `analyze()` 内二次调用 `landingAnalysis` 形成「两次模型理解」且失败时静默吞掉。本版为 B 类（涉及处理流程调整）第一项，按依赖顺序 `B2 → B1 → B3 → B4 → B5` 推进；仅做统一分析来源的契约与前端去重，不动界面布局。
**更新要点**
- 后端 `CWAnalysisResult` 新增 `analysis`，`api_cw_analyze` 一次性产出生成所需统一分析来源。
- 前端移除第二次模型调用，路线规划与素材生成均复用 `cw.analysis` 单一来源。

**来源 / 问题**
- 依《创意工作台专项评估与改造实施方案V4.56》「问题排查」P0#3：`cwAnalyze` 不返回 `analysis` 字段，前端在 `analyze()` 内再调一次 `landingAnalysis` 取得落地分析，形成「两次模型理解」且 `landing` 失败被 `.catch(() => null)` 静默吞掉，路线规划与生成以空分析兜底。
- 本版为 B 类（涉及处理流程调整）第一项，按依赖顺序 `B2 → B1 → B3 → B4 → B5` 推进；仅做统一分析来源的契约与前端去重，不动界面布局。

**本次优化与更改的功能 / 模块**
- 【修复·后端】`schemas.py` 的 `CWAnalysisResult` 新增 `analysis: dict`（统一分析来源）。
- 【修复·后端】`routers.py` 的 `api_cw_analyze`：基于产品分析结论（boxes/brief/summary/recommendedPlatforms）构造兼容媒体生成链路 `media_ad` 的 `analysis`（含 industry/type/audience/advantages/channels/language/industry_profile 等键，并保留 boxes/brief 嵌套），随结果返回并写入 `CreativePlan.analysis_json`，供历史复用。
- 【修复·前端】`CreativeWorkbench.tsx` 的 `analyze()` 移除第二次模型调用 `landingAnalysis`，路线规划与素材生成统一改用 `cw.analysis` 单一来源；落库 `createCreationHistory` 与生成 payload 的 `analysis` 均取自 `cw.analysis`；`loadPlan` 恢复时回填 `analysis`。
- 【测试】`tests/test_cw.py` 的 `test_01` 增加 `analysis` 字段结构断言。

**影响范围**
- 前端：仅 `CreativeWorkbench.tsx` 的 `analyze()` / `generate()` / `loadPlan` 数据源切换；界面布局、步骤、文案、右侧面板均不变。
- 后端：`api_cw/analyze` 响应多一个 `analysis` 字段（向后兼容，旧调用方忽略即可）；`CreativePlan.analysis_json` 多存 `analysis`，无表结构变更。

**验证**
- 前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 309.72 kB JS / 82.30 kB CSS。
- `python3 tests/run_all.py`：运行 152 项，失败 0、错误 0、跳过 0（含新增的 `analysis` 结构断言）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.58 == 系统版本 V4.58，校验通过。

**说明 / 默认约定**
- 右侧面板定位为「结果查阅」：不展示进度、不展示路线勾选、不提供生成 / 下载按钮；需要选择路线或生成素材时仍在正文操作。
- 面板默认展开，可点击头部「›」收起；收起后右侧显示竖排「项目简报 ›」标签，点击即展开。
- 视频素材：当前生成链路仅产出图片，资产卡已做视频类型识别与播放支持，待后端视频节点接入即可生效。

## V4.57 创意工作台：文档问题排查之 A 类修复（纯逻辑 / 契约，不动布局与流程）

**发布日期**：2026-11-11
**变更类型**：缺陷修复（后端契约 + 前端逻辑）
**涉及模块**：创意工作台（前端 / 后端 presets）
**变更摘要**：依据《创意工作台专项评估与改造实施方案 V4.56》的「问题排查」清单，逐条核对 V4.56 源码（基线 8196ea6），确认 6 项 P0 + 2 项 P1 全部真实存在。本版只实施其中 **A 类（纯逻辑 / 契约修复，无需改动界面布局、不增删步骤、不改处理流程）** 的 5 项止血与正确性修复；涉及界面展示 / 处理流程调整 / 新增内容的 B 类项（抓取、统一快照、覆盖编排、逐图质检、视频、会话模型）按约定留到最后版本，先列方案待确认后再开发。

**更新要点（A1–A5）**
- 【修复·后端 A1】`backend/presets.py`：`get_preset` 对未知编号由「硬索引抛 KeyError」改为「返回 None」；`build_directives._text` 在预设缺失但原始值为自然语言文本（如创意路线名 / 角度 / 描述）时，直接作为自定义指令文本进入提示词。修复文档 P0#1：路线文本误传预设 ID 引发的 `KeyError`，且确保路线内容不丢失。
- 【修复·前端 A2】`CreativeWorkbench.tsx`：去掉 `sizes.slice(0, 2)` 静默截断，按媒体平台返回的全部规格生成；生成维度由「平台 × 1 条路线」改为「平台 × 每条选中路线」，保证单平台多选路线时三条路线均被覆盖（修复文档 P0#5 的覆盖裁剪与路线轮换缺陷）。进度分母同步改为 `平台数 × 选中路线数`。
- 【修复·前端 A3】`generate()` 完成态不再无条件 `setView('result')` + 写 `status='done'`；改为依据各任务真实终态裁决：有图才标记完成并写 `done`，零图 / 全失败则进入结果区展示错误并允许重试，不谎报成功（修复文档 P0#6 的错误完成）。
- 【修复·前端 A4】`loadPlan()` 加载历史前先清理上一项目的 `landing / assets / jobs / historyId` 残留，并还原 `history_id` 与输入链接，避免跨项目旧数据参与生成（修复文档 P1#1 的历史恢复不全）。
- 【修复·前端 A5】新增独立 `downloadAll()`，「打包下载全部」与「下载已选」解耦；未勾选也能打包全部素材（修复文档 P1#2 的「全部」复用已选函数）。

**本次优化与更改的功能 / 模块**
- 【前端】`frontend/src/pages/CreativeWorkbench.tsx`：重写 `generate()` 生成循环（平台 × 每条选中路线、去掉 `sizes.slice(0,2)` 规格截断、完成态按真实终态裁决）；`loadPlan()` 加载前清理跨项目 `landing / assets / jobs / historyId` 残留并还原 `history_id` 与输入；新增 `downloadAll()` 并与「下载已选」解耦。
- 【后端】`backend/presets.py`：`get_preset` 未知编号由硬索引改为安全返回 `None`；`build_directives._text` 在预设缺失但原始值为自然语言文本时，将其作为自定义指令兜底进入提示词（修复路线文本误传预设 ID 的 KeyError 且不丢内容）。
- 【优化】`backend/version.py` 升 `APP_VERSION = "4.57.0"`；`CHANGELOG.md` / `README.md` 同步版本与说明。

**B 类（已确认存在，留到最后版本，待确认方案后再开发）**
- B1 P0#2 链接实际抓取（ProductSnapshot）；B2 P0#3 统一分析来源（去掉重复模型调用）；B3 P0#4 文案与资产（reference_image）；B4 P0#5 完整覆盖编排（concept×媒体×角色 + 拆批）；B5 P0#6 后端逐图质检与真实合规字段；B6 W01–W07 架构级（creation-plans 接通、视频、模型契约、会话 / 修订模型、回归灰度）。

**影响范围**
- 前端：仅 `CreativeWorkbench.tsx` 的生成 / 历史 / 下载逻辑；界面布局、步骤流程、文案均不变。
- 后端：`presets.py` 的预设解析防御与自定义文本兜底；无新增 / 删除接口，无 DB 迁移。

**验证**
- 前端 `tsc --noEmit` 通过；`vite build` 47 模块 / 309.78 kB JS / 82.30 kB CSS。
- 后端：`python3 tests/run_all.py` 152 项通过（A 类修复为逻辑层，沿用既有用例）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.57 == 系统版本 V4.57，校验通过。

**说明 / 默认约定**
- 本版仅做 A 类止血；B 类系统性重构（抓取 / 统一快照 / 覆盖编排 / 质检 / 视频）不在本次范围，待逐条确认方案后实施。
- KeyError 修复采用「安全返回 + 自定义文本兜底」，未改变前端 `style_opts` 传参结构，因此不需要调整界面或处理流程。

## V4.59 创意工作台：真实抓取 + 来源快照 + 演示模式隔离（B1·P0#2）

**发布日期**：2026-11-12
**变更类型**：新增 + 缺陷修复（新增 fetchers 模块、后端处理流程 + 前端展示）
**涉及模块**：创意工作台（后端 routers / 新增 fetchers / schemas；前端 CreativeWorkbench / api / styles）
**变更摘要**：依据《创意工作台专项评估与改造实施方案 V4.56》「问题排查」P0#2，确认 `api_cw_analyze` 仅把 URL 当字符串塞进提示词（不抓取），模型无页面事实可依、只能凭 URL 猜测或静默套用写死的「降噪耳机」演示数据并以真实结论呈现。本版为 B 类（修改处理流程 + 新增内容）第二项，按依赖顺序 `B2 → B1 → B3 → B4 → B5` 推进：① 输入 URL 时服务端真实抓取落地页并构造带 [E###] 证据包的事实提示词；② 新增 `ProductSnapshot` 固化来源 / 抓取时间 / 证据，可追溯；③ 把「降噪耳机演示数据」隔离到显式「演示模式」开关（默认关闭），非演示且抓取失败时明确 422 阻断，不再静默编造；④ 前端展示数据来源与真实调用的模型。

**更新要点**
- 新增 `backend/fetchers.py`：复用素材创作链路的真实抓取与证据机制（`fetch_page` / `build_evidence_pack` / `evidence_contract` / `claim_contract`），提供 `fetch_product(url)`（真实抓取 + 快照字段，抓取失败返回 `ok=False` 供调用方阻断）与隔离的 `demo_product()` / `demo_snapshot(url)`（仅演示模式使用，标注 `source=demo`）。
- 后端 `schemas.py`：新增 `ProductSnapshot`（source / url / final_url / fetched_at / fetch_quality / snapshot_id / title / evidence_ids）；`CWAnalyzeRequest` 增加 `demo_mode: bool = False`；`CWAnalysisResult` 增加 `snapshot: ProductSnapshot`。
- 后端 `routers.py` 的 `api_cw_analyze`：按三态分支 —— `demo_mode=True` 仅返回样例（`source=demo`，不调用模型、不伪装真实）；`url` 有值则服务端真实抓取并以证据包驱动模型（`source=real_fetch`），抓取失败且无文本时返回 `422 needs_input`；仅 `text` 有值则基于粘贴文本分析（`source=pasted`）。抽出 `_build_cw_result` 统一构造 B2 的「生成统一来源 analysis」并落库，快照一并写入 `CreativePlan.analysis_json`。

**本次优化与更改的功能 / 模块**
- 【新增·后端】`backend/fetchers.py`：CW 专属抓取模块（真实抓取 + 证据包 + 演示数据隔离）。
- 【修复·后端】`schemas.py` 新增 `ProductSnapshot`；`CWAnalyzeRequest.demo_mode`；`CWAnalysisResult.snapshot`。
- 【修复·后端】`routers.py` 的 `api_cw_analyze`：真实抓取 + 证据驱动 + 演示模式隔离 + 422 阻断；新增 `_build_cw_result` 统一构造 analysis 与快照落库。
- 【前端】`api.ts` 的 `cwAnalyze` 请求体支持 `demo_mode`。
- 【前端】`CreativeWorkbench.tsx`：输入框新增「演示模式」勾选并随请求发送；分析结果区与右侧「项目简报」面板展示「数据来源 / 落地页 / 抓取时间 / 抓取质量 / 分析模型」徽标（按来源着色）；`loadPlan` 恢复历史 `snapshot`。
- 【测试】`tests/test_cw.py` 增强断言：演示模式返回 `source=demo`，真实抓取路径返回 `snapshot.fetched_at` 非空且 `source=real_fetch`，抓取失败 + 无文本返回 422。

**影响范围**
- 前端：新增演示模式开关与来源徽标展示；现有界面布局、步骤流程、文案不变。
- 后端：新增 `fetchers.py`；`cw/analyze` 响应新增 `snapshot` 字段（向后兼容，旧调用方忽略即可）；`CreativePlan.analysis_json` 多存 `snapshot`，无表结构变更。`demo_mode` 未传时默认 `False`，向后兼容。

**验证**
- 前端 `tsc --noEmit` 通过；`vite build` 通过（约 47 模块）。
- `python3 tests/run_all.py`：全量通过（含 B1 新增的 demo / real_fetch / 422 断言）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.59 == 系统版本 V4.59，校验通过。

## V4.60 创意工作台：广告文案上线 + 商品/品牌参考图接入（B3·P0#4）

**发布日期**：2026-11-12
**变更类型**：新增 + 缺陷修复（后端新增端点、前端处理流程 + 文案生成 + 参考图接入）
**涉及模块**：创意工作台（后端 routers / 前端 CreativeWorkbench / api / styles）；复用素材创作链路 `generate_media_copy` / `generate_media_images`
**变更摘要**：依据《创意工作台专项评估与改造实施方案 V4.56》「问题排查」P0#4，确认创意工作台 `generate()` 只提交 `images_request` 且写死 `copy_fields: {}, copy_variants: []`，从不调用 `generate_media_copy`，导致**出图不出文案（文案为空）**；同时出图链路虽已支持 `style_opts.reference_image`（真实商品/品牌图本地合成或参考编辑），但 CW 前端既无上传/传参入口、也未把产品参考图接上。本版为 B 类（修改处理流程 + 新增内容）第三项，按依赖顺序 `B2 → B1 → B3 → B4 → B5` 推进：① 生成流程每平台基于统一分析来源产出可编辑广告文案，文案随图叠加（`copy_variants`），并在结果区展示 / 可下载 / 落库；② 输入区新增「商品/品牌参考图」，支持上传与 URL 两种方式，URL 经后端下载本地化后以 `/files/<name>` 注入 `style_opts.reference_image`，让生成资产真正参考真实商品外观。

**更新要点**
- 前端 `CreativeWorkbench.tsx`：在 `generate()` 中为每个平台先调用 `api.mediaCopy({analysis, platform, lang})` 取得 `fields` 与 `variants`，组装成 `copy_variants` 注入该平台每个路线任务的 `images_request`（图片叠加文案）；按平台收集文案用于展示。
- 前端 `CreativeWorkbench.tsx`：输入卡新增「参考图」控件——上传（调 `POST /api/assets/upload`）或粘贴 URL（调新增 `POST /api/assets/fetch-url` 下载本地化），统一以 `/files/<name>` 经 `style_opts.reference_image` 进入出图链路；结果区新增「广告文案」区块，按平台展示字段并提供单平台 TXT / 全部 JSON 下载；生成后把文案写回创作历史（`updateCreationHistory` 的 `copy`，含 `platform_copies` 多平台全量），`loadPlan` 从历史恢复展示。
- 后端 `routers.py` 新增 `POST /api/assets/fetch-url`：校验 http(s)、超时、content-type 为图片、限大小（12MB），下载到 `UPLOAD_DIR` 并返回 `/files/<name>`；非图片 / 下载失败一律 400，不静默假装成功。

**本次优化与更改的功能 / 模块**
- 【修复·前端】`CreativeWorkbench.tsx` 的 `generate()`：接入每平台文案生成并注入 `copy_variants`（修复「文案为空」），参考图经 `style_opts.reference_image` 进入出图。
- 【新增·前端】输入卡「参考图」上传 + URL 输入；结果区「广告文案」展示与下载（TXT / JSON）；`loadPlan` 恢复历史文案。
- 【新增·前端】`api.ts` 补充 `fetchAssetUrl` 与 `creationHistoryDetail` 封装。
- 【新增·后端】`routers.py` 的 `POST /api/assets/fetch-url`：参考图 URL 下载本地化。
- 【复用·后端】素材创作链路 `generate_media_copy` / `generate_media_images` 已具备文案叠加与 `reference_image` 能力，本版直接复用，无重复实现。

**影响范围**
- 前端：输入卡新增参考图控件、结果区新增文案区；现有布局 / 步骤 / 其它文案不变。文案生成比原流程每平台多 1 次模型调用，已计入进度与文案。
- 后端：新增 1 个端点（不修改既有接口契约）；旧历史 `copy` 缺省为 null，前端空值兜底；`reference_image` 不传时维持原 `reference_mode=none` 行为，向后兼容。

**验证**
- 前端 `tsc --noEmit` 通过；`vite build` 通过。
- `python3 tests/run_all.py`：全量通过（含 B3 新增的文案生成 / copy_variants 透传 / reference_image 透传 / URL 端点校验断言）。
- `python3 scripts/prepare_release.py --check`：发布数据最新版本 V4.60 == 系统版本 V4.60，校验通过。

**说明 / 默认约定**
- 演示模式默认关闭；开启后返回降噪耳机样例并明确标注「演示样例」，不会伪装成真实抓取结论。
- 真实抓取失败（链接不可达 / 空页）且未提供文本时，系统直接 422 阻断并提示「开启演示模式或补充正文」，不再静默套用样例数据。

## V4.61 创意工作台·素材沉淀库（B4）

**发布日期**：2026-11-12
**变更类型**：优化
**涉及模块**：数据模型、后端接口、系统版本、前端与菜单
**变更摘要**：创意工作台新增素材沉淀库：B1 真实抓取/粘贴的产品、用过的参考图、产出的品牌自动沉淀，新会话可一键复用，避免重复上传与重复分析。

**更新要点**
- 数据模型：新增 cw_library 表（reference/product/brand 三类），按方案/文件/品牌去重，ensure_schema 自动建表
- 后端：B1 真实抓取/粘贴分析后自动沉淀产品；新增 GET/POST/DELETE /api/cw/library（仅本人可增删、孤立文件清理）
- 前端：参考图「素材库」一键引用、产品「复用产品」预填链接、品牌「素材库」复用；生成时自动沉淀用过的参考图与品牌

**本次优化与更改的功能 / 模块**
- 【优化】数据模型 / 版本更新：相关代码与配置已同步更新。
- 【优化】后端接口 / 版本更新：相关代码与配置已同步更新。
- 【优化】系统版本 / 版本更新：相关代码与配置已同步更新。
- 【优化】前端与菜单 / 版本更新：相关代码与配置已同步更新。

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：本次改动涉及 数据模型、后端接口、系统版本、前端与菜单；旧数据与旧接口保持兼容。

**验证**
- 系统版本与 CHANGELOG 版本一致性由发版校验强制检查；该条目由本次改动文件自动归纳。

## V4.62 创意工作台·导出与交付增强（B5）

**发布日期**：2026-11-12
**变更类型**：优化
**涉及模块**：素材创作平台、系统版本、前端与菜单、数据模型、后端接口、新版通知
**变更摘要**：创意工作台历史导出包增强为结构化交付物：在原有图片/文案/分析基础上，新增 ad_copy.csv（多平台文案表格）与 delivery_notes.md（来源、分析模型、各平台文案、素材清单、素材库引用追溯），一键「导出交付包」即可交付广告主/渠道。

**更新要点**
- 增强 build_history_zip：新增 ad_copy.csv（列=平台/版位/标题/副标题/行动号召/品牌，含 BOM 兼容 Excel），从 copy_json 的 platform_copies / copy_variants / 顶层 fields 提取多平台文案
- 新增 delivery_notes.md：来源落地页、产品/品牌、数据来源与抓取时间、分析模型、各平台文案、素材清单、引用 B4 素材库的复用说明
- 前端「打包下载全部」升级为「导出交付包」，改用既有的 /api/creation-history/{hid}/export.zip 端点（含全部增强交付物）；无 historyId 时回退纯素材 ZIP

**本次优化与更改的功能 / 模块**
- 【优化】素材创作平台 / 版本更新：相关代码与配置已同步更新。
- 【优化】系统版本 / 版本更新：相关代码与配置已同步更新。
- 【优化】前端与菜单 / 版本更新：相关代码与配置已同步更新。
- 【优化】数据模型 / 版本更新：相关代码与配置已同步更新。
- 【优化】后端接口 / 版本更新：相关代码与配置已同步更新。

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：本次改动涉及 素材创作平台、系统版本、前端与菜单、数据模型、后端接口；旧数据与旧接口保持兼容。

**验证**
- 系统版本与 CHANGELOG 版本一致性由发版校验强制检查；该条目由本次改动文件自动归纳。

### 热修复（2026-11-12）：落地页分析后无文案 / 无素材图片

**根因**：创意工作台前端 `DEFAULT_PLATFORMS` 与后端 `analyze` 兜底均使用已弃用别名 `Meta`，但媒体规则引擎只认 `Facebook`。用户选择 Meta 后，`/api/media-campaign/copy` 与出图任务矩阵校验返回 422，被前端 `.catch(()=>null)` 静默吞掉，表现为「无分析结果 / 无文案 / 无素材图片」。

**修复**
- `backend/media_platforms.py`：`_PLATFORM_ALIASES` 增加 `Meta/fb/instagram/ig → Facebook` 历史别名兼容（治本，文案 + 出图同时修复）
- `backend/routers.py`：`rec_plat` 兜底由 `['Meta','Google']` 改为 `['Facebook','Google']`；`_build_cw_result` 对 `recommendedPlatforms / channels` 做平台名归一（去重 + 别名收敛），杜绝弃用名外泄
- `frontend/src/pages/CreativeWorkbench.tsx`：`DEFAULT_PLATFORMS` 由 `['Meta',...]` 改为规范名 `['Facebook',...]`
- `tests/test_cw.py`：新增 `test_15`（Meta 别名端到端通过 mediaCopy / 出图）与 `test_16`（recommendedPlatforms 必为规范名）

**验证**：`run_all.py` 163 项全过；`tsc` + `vite build` 通过；`prepare_release --check` 通过。

### 热修复（2026-11-12）：平台规范名统一为 Meta（Facebook 降级为兼容别名）

**根因回顾**：上一轮热修复用 `Meta→Facebook` 别名把「Meta」收敛到规则引擎规范名 `Facebook`，但前端/用户习惯称其为 Meta，命名仍不一致、易再次踩坑。

**本次统一**：将规则引擎**规范平台名改为 `Meta`**，`Facebook / fb / instagram / ig` 全部作为**兼容别名**（出图任务矩阵 / 文案 schema 仍解析为 Meta）。涉及 `media_platforms.py`（`MEDIA_PLATFORMS` / `PLACEMENT_RULES` / `MEDIA_COPY_SCHEMA` 主键 + 别名表）、`media_ad.py`（COPY_SCHEMA 主键与默认值）、`providers.py`（平台分析字典键）、`routers.py`（提示词文案 + `rec_plat` 兜底 `['Meta','Google']`）、`prompt_catalog.py` 平台列表、`frontend`（`DEFAULT_PLATFORMS` 与菜单描述）；并把 `SPEC_VERSION` 由 `2026-11-10.3` 升到 `2026-11-12.1` 标记该规则变更。旧数据/旧调用中的 `Facebook` 仍经别名解析为 `Meta`，不破坏历史记录。

**验证**：`run_all.py` 163 项全过；`tsc` + `vite build` 通过；`prepare_release --check` 通过。

### 热修复（2026-11-12）：出图任务因 placement 传平台名被整体拒绝（Meta: undefined）

**根因**：创意工作台出图链路构造任务矩阵时 `slots = sizes.map(size => ({size, placement: p}))`，把**平台名 `"Meta"` 当作版位（placement）**传给后端。后端 `validate_task_matrix` 自 V4.44/N04 起严格执行「未知版位不静默降级」，`"Meta"` 不是合法版位（合法为 feed/stories/reels），于是整批校验失败 → 出图任务 `failed`；同时前端轮询只更新 `status/progress`，从不把后端返回的真实 `error` 写回 `jobs` 数组，失败任务 `error` 始终为 `undefined`，界面渲染成 `Meta: undefined`，掩盖了真实错误。

**修复**
- `backend/media_platforms.py`：新增 `default_placement(platform, size)`，取平台默认版位（优先 `default` 标记、且尺寸匹配者）；`validate_task_matrix` 在 `resolve_placement` 抛错且传入 `placement` 恰好等于平台名（即「用平台名当版位（placement）传入」）时，回退到默认版位并保留 warning，而非整体拒绝；真正写错版位（如 `"foobar"`）仍按 N04 严格报错。
- `frontend/src/pages/CreativeWorkbench.tsx`：轮询任务状态时把后端返回的真实 `error` 写回 `jobs`；失败文案对 `undefined` 兜底为可读提示，不再显示 `Meta: undefined`。
- `tests/test_cw.py`：新增 `test_17`（placement=平台名回退默认版位 feed + warning，真错版位仍报错）与 `test_18`（端到端：placement=Meta 任务矩阵落库并跑出图片）。

**验证**：`run_all.py` 165 项全过（原 163 + 新增 2）；`tsc` + `vite build` 通过；`prepare_release --check` 通过。

### 热修复（2026-11-12）：候选文案被拼接成超长文案 → 版位预算溢出 → 零图（Meta: undefined 的真实主因）

**根因**（依据《创意工作台Meta生成失败原因与最小修复方案》，审查 `f266cac`）：上一轮把「Meta/Facebook 名称不一致」误判为本轮根因；真实且可复现的故障路径为——工作台在 `mediaCopy` 取得 Meta 的 headline 候选数组后，映射函数 `one(v)` 对数组执行 `filter(Boolean).join(" / ")`，把 3 个各 40 字符候选拼成 **126 字符单条图内文案**。该长度超过 Meta 各版位图内排版预算（如 1080×1080/1350/1920 仅 45 字符），`build_overlay_text` 将每个尺寸都记为 `needs_revision` 并跳过；所有尺寸均跳过时整批 `failed`、图片为空。此时 `job.status=failed` 但顶层 `error` 为空（后端未在 failed 时汇总原因），前端轮询只回写 `status/progress`、不写 `error`，失败任务 `error=undefined` → 界面显示 `Meta: undefined`，掩盖了真实原因。

**修复（对应方案 Fix 1~4）**
- `frontend/src/pages/CreativeWorkbench.tsx`：
  - Fix 1：候选文案映射由「拼接」改为「取单个有效值」——新增 `firstNonEmpty`（数组取首个非空字符串、字符串保持原值、null 返回空）与 `pickFirstField`（在 description/body/primary_text 多个备选字段中取首个有效值，避免空数组阻断 body 回退）；`headline/sub/cta/brand` 均按单个值处理；全量候选仍保留在 `copiesByPlat[p].fields` 中，不删除已有文案；维持每路线一组 variants、**不增加任务数量**。
  - Fix 1/F4：文案生成失败或 `validation.status==='invalid'` 时记录 `copyFailures[平台]`，**不提交该平台空文案出图任务**，并在结果区登记具体失败原因（不浪费生成额度）。
  - Fix 2：轮询与最终回写均填充 `error`；失败列表渲染带 `route.name` 与 `jobId`；最外层零图汇总优先展示已捕获的具体错误，**不再用通用「调整媒体或重试」覆盖真实异常**。
  - Fix 4：文案归档 `copiesByPlat[primary]` 判空（`primaryCopy ? ... : {}`），避免「全部文案失败 → 对象不存在 → TypeError」被末尾通用提示吞掉。
- `backend/job_service.py`：Fix 3——新增 `_summarize_failed_error(result)`，在 `run_job` 的 `failed` 终态从 `task_results`（failed/needs_revision/invalid 的 reason/error）、`issues[].message`、`result.note` 汇总真实原因，去重并限长后写入 `job.error`；succeeded/canceled 不受影响，不新增接口或数据库字段。
- `tests/test_cw.py`：新增 `test_19`（单值 40 字符标题正常出图、变体 headline 不含拼接）、`test_20`（复现 126 字符拼接超预算被阻断且 `job.error` 含预算原因）、`test_21`（`_summarize_failed_error` 单元：汇总/去重/限长/空结果）、`test_22`（空 copy_variants 任务不抛 500）。

**验证**：`run_all.py` 169 项全过（原 165 + 新增 4）；`tsc` + `vite build` 通过；`prepare_release --check` 通过。
**说明**：仅消除 `undefined` 不算修复完成；本次同时证明「正常单值文案能生成图片、异常文案能显示明确原因」。线上真实模型生成成功与生产部署需受控验证 F8（复用用户原产品/媒体/路线）后再行报告，未获真实输出不宣告生产验收。

### 热修复（2026-11-12）：新版通知时间格式补全为 YYYY-MM-DD HH:MM

**目标**：「新版通知」每个版本更新通知原只展示发布日期 `YYYY-MM-DD`，缺少具体时间；按需求补全为完整时间格式 `YYYY-MM-DD HH:MM`（年-月-日 时:分）。

**修复**
- `backend/release_notes.py`：新增 `_git_commit_time(version)`（取首次引入该版本 CHANGELOG 段落的提交时间，按版本缓存避免重复调用 git）与 `_note_datetime(note)`；`public_note()` 的 `date` 字段由纯日期升级为 `YYYY-MM-DD HH:MM`——CHANGELOG 通知以官方「发布日期」为权威日期、叠加该版本发布提交的「时分」；自动同步通知用当前时间；无 git / 找不到提交时退回纯日期，不编造时间。
- 该改动同时覆盖部署环境权威数据 `backend/release_notes_data.py`：`scripts/prepare_release.py --sync` 经由 `public_note` 重建，71 个版本全部带完整时间。
- 前端 `frontend/src/pages/ReleaseNotes.tsx` 直接渲染后端下发的 `date`，无需额外格式化。

**验证**：`run_all.py` 169 项全过；`prepare_release --check` 通过；`release_notes_data.py` 首条 V4.62 的 `date` 为 `2026-11-12 11:28`（含时分）。
