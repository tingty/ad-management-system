# 广告管理系统（在线营销素材管理平台 V4.0）

对应方案文档：《在线营销素材管理平台方案.docx》；开发节奏见《在线营销素材管理平台-版本开发规划.docx》。

**定位**：给投放人员用的素材生产工具，不是素材台账。核心链路是
**产品 → 事实抽取 → 6 个创意方向 → 多版位素材（图/文案/视频分镜/关键词）→ 投放包**。
素材墙是主界面，协作与权限退到二级。

V4.0 的关键差别：导航从顶部横排标签换成**统一的左侧菜单栏**，一级菜单只有两项——
「素材管理」（含创作工作台 / 批量生成 / 素材库 / 规格库）与「设置」。菜单栏可收起为
66px 图标条（状态记忆、窄屏自动收起、点左上角 logo 展开），主区顶部有「一级 / 当前页」
层级标识，页面地址带 hash 可直接分享或刷新不丢位置。

V3.2 的关键差别：整条链路收进**一个纵向页面**，从上到下就是投放人员的实际动作——
**落地页链接 → 结构化分析报告 → 选平台/语言/版位 → 选方向 → 生成 → 说一句怎么改 → 下载**。
「素材优化」是一等公民：任何已生成的批次都能用自然语言调整，产出新版本、逐条列出改了什么，
而且文案与图片始终同源（图上文字就是文案字段渲染出来的）。

V3.0 的关键差别：素材的最小单位从「平台×语言×类型」换成**创意方向（Angle）**。
同一方向在不同版位是**重新排版**（横幅改左右分栏、竖版改上下分区），不是把 1:1 拉伸成 9:16。
默认不接大模型也能产出可投放内容：本地抽取真实卖点与指标、6 套视觉模板合成带视觉主体的图、
平台字段级文案（FB 三段式 / Google RSA 多标题）、视频四镜关键帧。

## 版本状态（均已开发并验收）

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
│   ├── report.py        # 结构化分析报告：七段结论 + 可信度 + 信息缺口 + 合规提示 + Markdown 导出
│   ├── optimize.py      # 素材优化：自然语言 → 确定性规则（更短/去数字/突出/换版式/换色）
│   ├── creative.py      # 创意方向引擎、平台文案字段、字数安全裁剪、同质化检测、关键词
│   ├── render.py        # 视觉渲染：6 套模板 + 多版位重排 + 产品图合成 + 视频关键帧
│   ├── imaging.py       # V1.3 旧版渲染（保留给 AI 底图叠加路径）
│   ├── validation.py    # 规格校验
│   ├── services.py      # 分析（整页抓取 + 本地抽取 + 模型润色）/ 方向规划 / 按方向生产 / 重生成 / 批量优化
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
3. **创意方向**：6 个方向按分析结果预选（推荐打标），可增减。
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

1. **落地页分析**：粘贴 URL/文本 → 产品、品类、人群、地区、语言、卖点、各平台策略。
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

## AI 模型接入

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
