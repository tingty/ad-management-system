# 广告管理系统（在线营销素材管理平台 V4.39）

对应方案文档：《在线营销素材管理平台方案.docx》；开发节奏见《在线营销素材管理平台-版本开发规划.docx》。
**当前版本：V4.39（2026-11-10）**。每次优化与更改的完整版本内容见 [CHANGELOG.md](CHANGELOG.md)，
系统内「系统设置 → 新版通知」顶部显示当前更新版本号与主要更新内容，并统一展示各期改造进度
（支持按涉及模块 / 变更类型筛选、查看影响范围与验证结果）。

**AI 改造分期**：依据《广告素材平台问题诊断与AI改造实施说明书》，12 个问题按「每期 3 个、
独立提交、独立版本通知」分 4 期推进，问题核对与验收用例见 [docs/REMEDIATION_TRACKER.md](docs/REMEDIATION_TRACKER.md)。
改造主干对全部行业一致，电商购买与订阅转化只是 `backend/industry_profiles.py` 中的两个画像；
其它行业通过局部调整价值维度、语义保护、证据类型与视觉主体输出素材，不改通用链路。

**定位**：面向投放人员的「素材创作 + 推广图片交付」工具。核心链路是
**落地页 URL / 正文 → 大模型 8 字段分析 → 营销推广平台设置 → 广告推广文案 → 推广图片 →
放大查阅 / 单张或打包下载 → 素材历史归档与复用**。

## 当前模块结构（V4.37 起）

| 一级菜单 | 二级功能 | 说明 | 权限 |
|---|---|---|---|
| 素材创作平台 | 素材创作 | 落地页分析 + 营销推广设置（平台 / 文案 / 推广图片） | admin / manager / editor |
| 素材创作平台 | 素材提示词 | 全量提示词目录（按功能 / 使用类型分类）+ 优秀提示词总结库 + 系统默认 | 读取所有登录角色；写入 admin |
| 素材创作平台 | 素材历史 | 已分析网站 / 文案 / 图片归档、放大查阅、再下载、批量删除、复用分析 | admin / manager / editor |
| 系统设置 | 大模型配置 | 按协议直配、连通性测试、每日自动测试、测试成功优先选配 | admin |
| 系统设置 | 账号 / 日志 | 账号与角色、审计日志 | admin |
| 系统设置 | 新版通知 | 当前版本号 + 主要更新内容、分期改造进度、结构化版本发布内容、模块 / 类型筛选、未读红点 | 所有登录角色（含 viewer） |

> **V4.37 下线说明**：整体删除「素材管理」的**创作工作台 / 批量生成 / 素材库 / 规格库**四个子模块，
> 以及系统设置中的**提示词管理**；对应的前端页面、后端接口、业务代码、ORM 表定义与失效提示词均已清理。
> 下方「版本状态」表为历史交付记录，其中 V0.1–V4.36 描述的旧模块不再存在于当前系统中。
> 旧 hash（`#/workspace`、`#/batch`、`#/library`、`#/specs`、`#/prompts`）会自动跳到当前角色可用页面。

## 每次发版：版本通知流程（V4.37 起）

单一数据源是根目录 `CHANGELOG.md`；每条版本段落按统一结构发布，
系统「新版通知」由 `backend/release_notes.py` 解析后经 `/api/system/release-notes` 展示。

```bash
# 1. 开发完成后，从本次 git 改动自动归纳「涉及模块」并生成版本通知骨架
python3 scripts/prepare_release.py --draft

# 2. 把骨架追加到 CHANGELOG.md，补全摘要 / 改动明细 / 影响范围 / 验证
python3 scripts/prepare_release.py --write --version V4.38 --title "版本主题"

# 3. 同步 git 前校验：结构化字段完整、无占位文字、CHANGELOG 已随代码更新、模块已总结
python3 scripts/prepare_release.py --check

# 4. 安装一次本机 pre-push 钩子，之后每次 push 自动执行第 3 步
bash scripts/install_hooks.sh
git add -A && git commit -m "V4.38 ..." && git push
```

版本段落模板（缺一不可）：

```markdown
## V4.38 版本主题
**发布日期**：YYYY-MM-DD
**变更类型**：新增 / 优化 / 修复 / 删除
**涉及模块**：模块A、模块B
**变更摘要**：一句话说明本版做了什么

**本次优化与更改的功能 / 模块**
- 【优化】模块A / 功能名：具体改动说明

**影响范围**
- 前端 / 后端 / 数据 / 兼容性 / 权限

**验证**
- 本次实际执行的验证项与结果
```

紧急发布可用 `SKIP_RELEASE_CHECK=1 git push` 跳过钩子，但事后须补齐版本通知。
历史版本（V1.1–V4.36）保持原样，前端自动降级为「要点摘要 + 完整发版记录」，不丢内容。

## 版本状态（历史交付记录，均已开发并验收）

| 版本 | 主题 | 核心能力 |
|---|---|---|
| V0.1 | 原型基线 | 前后端骨架、Mock 全链路、四页面、ZIP 导出 |
| V1.0 | 核心可用 | 规格校验（字数/尺寸/关键词）、模型连通性测试、规格库页、模型热切换 |
| V1.1 | 批量提效 | CSV 导入、异步任务队列（进度/取消/失败隔离）、多 Campaign 合并导出 |
| V1.2 | 迭代与 A/B | 版本链、并排对比（逐字段+字数差）、定稿标记、A/B 分组导出、定稿导出 |
| V1.3 | 真实视觉素材 | Pillow 合成真实 PNG（全尺寸）、AI 底图 + 文案叠加、视频分镜脚本/可配置视频模型 |
| V2.0 | 平台化协作 | 用户与角色、登录鉴权、审阅流（提交/通过/驳回+记录）、规格后台编辑、审计日志 |
| V3.0 | 创意工厂 | 本地事实抽取、6 个创意方向、6 套视觉模板 + 多版位重排、平台字段级文案与字数条、视频关键帧、同质化检测、按平台/方向打包导出 |
| V3.1 | 真实页回归 | 落地页正文自动抓取、抽取依据可回溯、产出量参数化（版位数/视频策略）与预估、评分与倒计时改为真实数据 |
| V3.2 | 单页工作台 | 落地页整页抓取（标题/H1/H2/CTA/图片/语言）、结构化分析报告（七段+可信度+缺口+合规）、单页纵向流程、素材优化指令（短/去数字/突出卖点/换版式/换色）与逐条变更记录、只导合格素材、版本化导出 |
| V4.0 | 左侧菜单 | 两级左侧导航（素材管理 / 设置）、可收起为图标条并记忆状态、窄屏自动收起、hash 路由刷新不丢位置、主区层级标识与页面说明、角色化菜单过滤 |
| V4.1 | 网站核心内容分析 | `SYS_SITE_ANALYSIS` 提示词驱动 LLM 一次性产出 9 模块结构化分析（定位 / 价值 / 背书 / 人群 / 页面 / 渠道 / 风险 / 缺口 / 下一步）并落库 `Framework.site_analysis`，替代旧版「部分模块 LLM、其余规则硬写」；无 Key 时 Mock 按 MARKER 分支返回同结构 JSON |
| V4.2 | 创意方向框架 | 方向扩至 8 个（新增 场景代入 / 对比测评），每个带 `hook_type` 钩子类型与 3 段 `storyboard` 分镜；`build_copy_kit` 自动从 `site_analysis` 注入指标 / 卖点 / 痛点；推荐排序结合受众痛点、价值主张、背书与合规风险加权打分，命中信号写入 `reasons` 可回溯 |
| V4.3 | 默认大模型 | 启动播种「千问大模型 / qwen-plus」（`/compatible-mode/v1`），`max_tokens` 4096 防截断，回退 Mock 时如实标注 `_source` |
| V4.4 | 设置拆分 | 「系统设置」拆为大模型配置 / 账号 / 日志 / 提示词管理四页；提示词可在线编辑、保存即生效、支持恢复默认 |
| V4.5 | 完整视频 | 投放设置按媒介广告位类型显示「生成完整视频」；AI 分镜 → 关键帧 → ffmpeg 合成 MP4，可在线预览与下载 |
| V4.6 | 差异化视觉 | 素材墙图片 / 视频 / 文案上下分区；9 种背景风格 + 4 种文字版式，按创意方向（LLM 提示词 `image` + 内置预设）差异化，图片与视频关键帧逐镜轮换 |
| V4.7 | 成片级关键帧 | 关键帧只保留广告画面（满画幅，去掉镜号/时间码/进度条/说明文字），分镜说明与旁白改为素材墙图片右侧逐帧标注；文案随镜头推进（钩子→卖点→证据→CTA）；提示词明确 `visual`=拍摄说明、`text`=上屏字幕、`shot`=镜头名；每镜按秒单独编码后拼接，成片时长精确 |

## 目录结构

```
ad-material-platform/
├── backend/
│   ├── main.py          # 入口：鉴权中间件、建表/迁移、CORS、静态素材、路由
│   ├── database.py      # 连接池 + SQLite WAL/busy_timeout
│   ├── models.py        # ORM：落地页/框架/Campaign/素材/规格/模型/任务/用户/审阅/审计
│   ├── schemas.py       # Pydantic 出入参
│   ├── specs_data.py    # 7 平台规格基线（可后台维护）
│   ├── providers.py     # 模型接入层（LLM / Image / Video，Mock 与真实均可切换）
│   ├── insight.py       # 本地事实抽取：产品/品类/指标/卖点/受众/地区/语言
│   ├── report.py        # 结构化分析报告：消费 site_analysis 的 9 模块 + 可信度 + 缺口 + 合规 + 创意方向推荐排序（_rank_angles）+ Markdown 导出
│   ├── optimize.py      # 素材优化：自然语言 → 确定性规则（更短/去数字/突出/换版式/换色）
│   ├── creative.py      # 8 个创意方向（hook_type + storyboard）、平台文案字段、从 site_analysis 注入指标/痛点、字数安全裁剪、同质化检测、关键词
│   ├── render.py        # 视觉渲染：6 套模板 + 多版位重排 + 产品图合成 + 视频关键帧
│   ├── imaging.py       # V1.3 旧版渲染（保留给 AI 底图叠加路径）
│   ├── validation.py    # 规格校验
│   ├── services.py      # SYS_SITE_ANALYSIS 提示词 + 分析（整页抓取 + 本地抽取 + LLM 9 模块）/ 方向规划 / 按方向生产 / 重生成 / 批量优化
│   ├── batch.py         # CSV 解析 + 异步批量任务
│   ├── auth.py          # PBKDF2 口令 + HMAC Token + 角色门禁
│   ├── migrations.py    # 轻量 schema 自愈（自动补列 + 数据回填）
│   └── uploads/         # 生成的 PNG / 素材文件
└── frontend/src/
    ├── App.tsx          # 登录态 + 左侧两级菜单（可收起）+ 角色过滤 + hash 路由
    ├── api.ts           # API 封装（自动带 Token、401 兜底）
    ├── pages/           # Workspace（单页：分析→设置→方向→素材→优化→交付）/ Batch / Library / Specs / Settings / Login
    └── components/      # ValidationBadge / VersionPanel / Storyboard / AdminUsers
```

## 启动

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8033
# 接口文档 http://127.0.0.1:8033/docs

# 前端（另开终端）
cd frontend
npm install
npm run dev          # http://localhost:5173
```

首次启动自动建表、播种平台规格与默认账号。

## 菜单结构（V4.0 左侧菜单）

```
素材管理                              ← 一级
  ├─ 创作工作台   单页流程：分析 → 投放设置 → 创意方向 → 素材与优化 → 交付
  ├─ 批量生成     CSV 导入 + 异步任务
  ├─ 素材库       历史批次检索、版本对比、审阅
  └─ 规格库       7 平台尺寸 / 字数红线 / 关键词逻辑
设置                                  ← 一级（仅管理员）
```

- 侧栏展开 236px，可收起为 66px 纯图标条；状态记在 `localStorage.admb_sidebar`，刷新后保持。
- 视口 < 1180px 自动收起；只有用户没手动设过状态时，变宽才会自动展开，不覆盖手动选择。
- 收起后点左上角 logo 展开；「素材管理」分组标题可折叠，收起态显示为分隔短横线。
- 地址栏同步 `#/workspace`、`#/library` 等 hash，刷新、书签、分享都能回到同一页。
- 菜单按角色过滤：只读账号没有「创作工作台 / 批量生成」，非管理员没有「设置」。

## 核心链路（V3.2 单页工作台）

1. **推广产品分析**：贴落地页链接（或正文）→ 服务端抓整页 → 本地事实抽取 →
   `report.py` 输出结构化报告：产品与定位 / 核心价值主张（带原文依据与强弱）/ 信任与量化背书 /
   目标人群 / 落地页结构与转化路径 / 各平台投放读法 / 风险与合规 / 信息缺口 / 下一步。
   报告顶部给「结论可信度」及理由，抓不到正文会明确说明原因，不编造卖点。
2. **投放设置**：平台（决定版位与文案字段规则）、语言、产出类型、每方向版位数、视频策略、品牌色与产品图。
   生成前实时预估产出量，超单次上限（240）直接拦截。
3. **创意方向**：8 个方向按网站分析信号（受众痛点 / 价值主张 / 量化背书 / 合规风险）加权打分排序，
   Top2 打「推荐」标并显示命中依据，可增减。
4. **素材与优化**：素材墙按方向分组、多尺寸并排、文案带字数条与校验状态。
   优化输入框支持「标题更短 / 去掉数字 / 更口语 / 换成纯文字版式 / 主色改蓝」等要求，
   产出新版本并逐条列出 `before → after`；无法保证语义完整时会保留原句并说明原因，不产出残句。
5. **交付下载**：单张直接下载；打包按「平台/方向」分目录，**默认只打每组最新版本**，
   可只导出校验通过的素材，另附 `copy.csv`、`delivery_notes.md`、`manifest.json` 与分析报告 Markdown。

### 关键接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/report` | 抓整页 + 结构化报告 + 顺带规划方向（一次调用走完第 1 步） |
| GET | `/api/reports/{fid}` | 基于已落库事实重建报告（不重复抓取） |
| GET | `/api/reports/{fid}/export.md` | 下载分析报告 Markdown |
| POST | `/api/campaigns/{cid}/optimize` | 按自然语言要求优化，返回新版本与逐条变更 |
| GET | `/api/export/campaign/{cid}?only_valid=true` | 只打包校验通过的素材（默认仅最新版本） |

### 默认账号

| 账号 | 密码 | 角色 | 能力 |
|---|---|---|---|
| admin | Admin@123 | 管理员 | 全部 + 用户管理 + 模型配置 + 审计 |
| manager | Manager@123 | 投放经理 | 审阅、规格维护、生成、导出 |
| editor | Editor@123 | 投放执行 | 分析、生成、重生成、A/B、导出 |
| viewer | Viewer@123 | 只读 | 查看素材库与规格库 |

> 生产环境请通过 `AUTH_SECRET` 覆盖默认签名密钥，并修改默认口令。

## 功能地图

1. **落地页分析**：粘贴 URL/文本 → LLM 产出 9 模块「网站核心内容」（定位 / 价值主张 / 量化背书 /
   人群与痛点 / 页面结构与转化路径 / 各平台打法 / 风险合规 / 信息缺口 / 下一步），结论可回溯、不编造。
2. **素材生成**：平台 × 语言 × 类型；图片按平台尺寸各出一张成品 PNG（文案已合成），视频输出可执行分镜脚本。
3. **规格校验**：生成即校验，卡片标「合规 / N 项不合规」并列出问题与字数。
4. **批量任务**：CSV 粘贴或上传 → 预览解析 → 异步执行（进度轮询、可取消、单条失败不影响整批）→ 一键下载全部成品。
5. **素材库 / 审阅**：历史检索、素材展开、单条下载、批量导出、版本链、A/B 对比、定稿、提交审阅、通过/驳回与审阅记录。
6. **规格库**：7 平台尺寸/视频/字数红线/关键词逻辑；管理员与经理可在线编辑，改动即时影响生成与校验。
7. **设置（管理员）**：按用途配置模型（analysis/copy/image/video）+ 连通性测试 + 用户与角色 + 审计日志。

## 关键 API

| 分组 | 接口 |
|---|---|
| 认证 | `POST /api/auth/login`、`GET /api/auth/me`、`GET /api/auth/roles` |
| 用户 | `GET/POST /api/users`、`PUT/DELETE /api/users/{id}`、`GET /api/audit-logs` |
| 分析/生成 | `POST /api/analyze`、`POST /api/generate`、`POST /api/materials/{id}/regenerate` |
| 版本/A-B | `GET /api/materials/{id}/versions`、`GET /api/materials/{id}/compare?against=`、`POST /api/materials/{id}/select`、`GET /api/campaigns/{id}/slots` |
| 批量 | `POST /api/batch/parse`、`POST /api/batch/upload`、`POST /api/batch/jobs`、`GET /api/jobs/{id}`、`POST /api/jobs/{id}/cancel`、`GET /api/batch/template` |
| 审阅 | `POST /api/campaigns/{id}/submit`、`/approve`、`/reject`、`/comment`、`GET /api/campaigns/{id}/reviews` |
| 导出 | `GET /api/export/campaign/{id}`、`/api/export/batch?ids=`、`/api/export/ab/{id}?selected_only=`、`/api/materials/{id}/download` |
| 规格/设置 | `GET/PUT /api/platform-specs`、`/api/settings/models`（含 `/test`） |

除 `/api/auth/login`、`/api/meta`、`/api/health`、`/api/auth/roles` 外，所有 `/api/*` 需要 `Authorization: Bearer <token>`；浏览器直链下载支持 `?token=`。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./ad_material.db` | 切 Postgres 直接改这里 |
| `AUTH_SECRET` | dev 默认值 | Token 签名密钥，**生产必须覆盖** |
| `AUTH_TTL_HOURS` | `12` | 登录有效期 |
| `IMAGE_SIZES_PER_PLATFORM` | `4` | 每平台出几种尺寸的图（主尺寸优先） |
| `MOCK_DELAY_MS` | `0` | Mock 每次调用延迟，用于演示进度条/取消 |
| `DEFAULT_LLM_PROVIDER` | `千问大模型` | 默认模型显示名称（设置页「模型名称」列） |
| `DEFAULT_LLM_BASE_URL` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | 默认模型 OpenAI 兼容地址（`/api/v1` 是 DashScope 原生协议路径，不兼容本系统） |
| `DEFAULT_LLM_MODEL` | `qwen-plus` | 默认模型名 |
| `DEFAULT_LLM_API_KEY` | 空 | 默认模型密钥；为空则不播种、回退本地 Mock。建议写入 `backend/.env`（已 gitignore）或部署环境变量，勿提交进仓库 |

## AI 模型接入

- **默认模型（开箱即用）**：`analysis` / `copy` 两个文本用途在启动时自动播种 DashScope 国际版
  `qwen-plus`（`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`，OpenAI 兼容协议），`is_active=True`。
  注：DashScope 的 `/api/v1` 是原生协议路径，本系统调用 `/chat/completions`，故使用 `/compatible-mode/v1`。
  设置页「AI 模型配置」可见、可编辑、可停用。密钥放在 `backend/.env`（已被 `.gitignore` 忽略，不进仓库）
  或部署环境变量 `DEFAULT_LLM_API_KEY`；未配置密钥则跳过播种、自动回退本地 Mock。
  图片 / 视频用途不预置，可在设置页继续接入其它模型调试。
- **网站分析**：`SYS_SITE_ANALYSIS` 提示词驱动，一次调用产出 9 模块 JSON 并落库；未配置 Key 时
  Mock 按 `MARKER:SITE_ANALYSIS_JSON` 返回同结构结果，从正文首句派生产品名，不出现 `Unknown Product`。
- **未配置 Key**：Mock 出稿（按语言、遵守字数红线、每次重生成措辞不同），图片用 Pillow 合成，开箱即用。
- **配置真实接口**：设置页填 `Base URL / Model / API Key`（OpenAI 兼容），保存即热切换；`/test` 可测连通性与延迟。
- **健壮性**：真实调用失败自动回退 Mock/模板，主流程不中断。
- **视频**：未配置时输出分镜脚本（镜头/画面/字幕/口播/交付物）；配置后按 `POST {base_url}/video/generations` 契约调用，失败回退分镜。

## 导出结构

```
campaign_<id>.zip                 # 单 Campaign：manifest.json + 全部素材
batch_export.zip                  # 多 Campaign：每个一个目录 + batch_manifest.json
campaign_<id>_ab.zip              # A/B：每个素材位一个目录（A_v1 / B_v2 …）+ ab_plan.csv
campaign_<id>_selected.zip        # 定稿：仅导出已选变体（未定稿时取最新版）
```

命名规范：`{campaign}_{platform}_{lang}_{type}[_{size}]_v{version}.{ext}`；视频分镜导出为 `.json`，关键词为 `.csv`。

## 已知边界

- 视频模型各厂商协议差异大，当前约定最小通用契约（`video/generations` 返回 `url` 或 `b64_json`），接入具体厂商时替换 `providers.ModelVideo` 即可。
- 图片为模板化合成（品牌色板在 `imaging.PALETTE`），如需品牌 VI 规范可替换字体与色板。
- 默认 SQLite 便于本地验收，团队并发使用建议切 PostgreSQL（WAL 与 busy_timeout 已就绪）。
