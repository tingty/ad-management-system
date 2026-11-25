# 版本交付记录

按《在线营销素材管理平台-版本开发规划.docx》的顺序交付，每个版本都是可独立验收的垂直切片。

## V4.137 全系统时间统一东八区北京时间
**发布日期**：2026-11-25 11:01
**变更类型**：修复 / 新增
**涉及模块**：全局时间展示、前端时间工具与页面（API对接、日志、素材历史、大模型设置、广告主报表、任务抽屉）、素材创作平台（前端页面时间显示）、后端时间工具、新版通知（版本日期与同步时间）、系统设置（模型每日测试调度）、广告主数据（自动调度执行小时）、专项测试、发版数据
**变更摘要**：排查并修复全系统时间显示比北京时间少 8 小时的问题。根因是后端数据库统一存 UTC，SQLite 取回丢失时区信息后多数接口直接输出无时区后缀的时间字符串，浏览器把这类字符串当成本地时间解析，界面实际展示的是 UTC 钟点；后端少数 `datetime.now()` 又输出本机时间，口径不一致。本版新增前后端统一时间工具：无时区后缀按 UTC 解析、带时区原样解析、纯日期按北京时间当天零点，展示强制锁定 Asia/Shanghai，且调度小时与版本通知时间显式按东八区生成，不再依赖运行机器的本地时区。
**更新要点**
- 【排查】实测取证：`2026-11-25T02:51:00` 在东八区浏览器被解析为 02:51（UTC 钟点），而 `2026-11-25T02:51:00Z` 正确解析为 10:51，确认差异 8 小时；后端 `models.utcnow()` 存 UTC、SQLite 取回为 naive，`routers._connection_out()` 等直接 `.isoformat()` 输出无时区串，`schemas` 仅模型配置的 `last_test_at` 单独补过时区，口径不统一。
- 【新增】前端 `frontend/src/datetime.ts`：统一 `parseBackendTime / parseBackendMs / fmtBeijing / beijingToday`，无时区后缀补 Z 按 UTC 解析、带 Z 或 +08:00 原样解析、纯日期按北京当天零点、空值与非法值可回退；输出用 `Intl.DateTimeFormat` 强制 `timeZone=Asia/Shanghai`，即使浏览器运行在 UTC 环境也显示北京时间。
- 【修复】全部时间展示点改为消费统一工具：API对接列表时间列 / 测试时间、日志页登录与审计时间、素材历史时间、大模型设置测试时间、任务抽屉创建时间（计时口径同步收敛）、广告主报表 `date` / `datetime` 格式列；API对接默认查询窗口改用 `beijingToday()`，避免浏览器处于 UTC 时窗口偏移一天。
- 【新增】后端 `backend/timeutil.py`：提供 `beijing_now / beijing_naive_now / beijing_display / beijing_iso`，固定 UTC+8；存储仍统一 UTC，面向用户的时间戳带 `+08:00`，调度钟点用 naive 北京时间避免与 SystemState 水位字符串混用 aware/naive 报错。
- 【修复】版本通知生成时间与 `synced_at` 改用显式东八区，避免部署到 UTC 服务器后通知日期偏移 8 小时；模型每日自动测试的日期与小时判断改按北京时间；广告主自动调度的执行小时与下次运行时间改按北京时间解释，拉取窗口与数据库时间列仍保持 UTC 不变。
- 【新增】`tests/test_timezone_v4137.py`：11 项覆盖后端时区固定 +08:00、UTC 机器仍输出北京时间、前端四种时间形态解析、空值回退、以及 TZ=UTC 与 TZ=Asia/Shanghai 下输出完全一致（用真实编译后的 `datetime.ts` 验证）。
**本次优化与更改的功能 / 模块**
- 【修复】所有界面时间（列表、日志、历史、测试记录、报表日期列、任务创建时间）统一显示为北京时间，跨浏览器与跨部署环境时区一致，不再出现少 8 小时或跨日偏移。
- 【新增】时间口径有单一事实来源：后端 `timeutil.py` 负责生成与调度，前端 `datetime.ts` 负责解析与展示，后续新增时间展示只需调用同一工具，不再各自 `new Date().toLocaleString()`。
**影响范围**
- 兼容：仅改变时间解析与展示口径，不改任何数据结构、数据库时间列、迁移、接口路径与业务字段；数据库存储仍为 UTC，历史数据无需回填。
- 部署：无新增表 / 列 / 迁移，重启后即刻生效；回滚只需还原前后端时间工具与各页面调用点，数据层无需变更。
- 边界：后端仍有部分接口直接输出 naive UTC 字符串（如运行记录窗口），系统内展示已由前端工具统一纠正；若有外部系统直接消费这些 API，需按 UTC 自行解析。
**验证**
- 专项：时区专项 11 passed；广告主十二个专项 + 时区专项合计 155 passed。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，691 passed / 2 skipped / 14 subtests passed。
- 前端：`tsc --noEmit` 与 `vite build` 通过；编译后的 `datetime.ts` 在 TZ=UTC 与 TZ=Asia/Shanghai 下输出逐字一致。
- 后端：`timeutil` 在 TZ=UTC 环境下仍输出 `YYYY-MM-DD HH:MM` 北京时间与 `+08:00` 时间戳。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.137。

## V4.136 广告主报表界面精简与数据排查
**发布日期**：2026-11-25 10:51
**变更类型**：优化 / 新增
**涉及模块**：广告主数据（广告主报表页面与空态引导）、前端报表页面、系统设置（模块功能开关）、专项测试、发版数据
**变更摘要**：按反馈精简「广告主报表」页面：顶部只保留主标题，删除解释文字与说明条，移除「趋势」和「广告主名称排行」两个子模块及其前端请求 / 状态 / 样式，保留 KPI、佣金明细与下钻。同时排查「已保存并对接 API、测试有返回但报表无数据」问题：报表只读已落库的订单佣金明细，不直接调上游 API；「测试连接」仅验证连通性不落库，必须点「立即拉取明细」或「历史回填」写入事实表后报表才有数据，明细空态已补充该引导。
**更新要点**
- 【优化】`AdvertiserReports.tsx` 顶部区块只保留主标题，删除 `ad-sec-desc` 解释文字与底部说明条；移除趋势 SVG 图、维度排行及「维度 / 维度值」筛选（原仅服务这两个模块），页面收敛为「筛选栏 + KPI + 明细 + 下钻」。
- 【优化】删除前端 `reportTrend / reportRankings / reportDimensions` 调用与对应 `ad-report-grid / ad-chart-* / ad-rank-*` 样式；后端报表接口与纯查询层完整保留（未来可复用，零表结构变更，回滚无损）。
- 【优化】明细空态文案改为可操作引导：说明报表只展示已落库明细，并指向「API对接 → 立即拉取明细 / 历史回填」完成落库。
- 【排查】数据不显示的根因：① 报表数据源是 `api_unified_fact` + `v_api_order_final`，只查落库数据，不实时请求上游；② 「测试连接」只回写测试元信息（`last_test_*`），不调用 `ingest_records()`，因此测试看到明细不等于已落库；③ 当前项目库 `api_connection` / `api_unified_fact` / `api_source_record` 均为空，且本机 8033 后端进程版本陈旧（健康检查报 4.122.0）、持有已移入废纸篓的旧库文件句柄，与新代码读取的项目库不是同一个库。修复路径：重启后端到当前版本并指向正确数据库，对已保存连接执行「立即拉取明细」或「历史回填」完成落库。
- 【新增】`tests/test_advertiser_reports_v4135.py` 增补 V4.136 静态契约：页面不含被删模块组件 / 请求 / 文案与顶部解释，保留 KPI / 明细 / 下钻。
**本次优化与更改的功能 / 模块**
- 【优化】报表界面去掉信息噪声与两个低频图表，信息密度聚焦在「收入 KPI → 订单明细 → 溯源下钻」，减少用户误以为报表应实时显示上游测试数据的困惑。
- 【优化】通过空态引导明确「拉取才落库、报表只读落库数据」的链路，把排查结论前移到界面，降低人工支持成本。
**影响范围**
- 兼容：后端报表查询层与七个只读接口全部保留，KPI / 明细 / 下钻口径不变；表头仍读 `api_field_label`；不改数据模型、不改视图、不改迁移、不改 API 对接 / 拉取 / 回填 / 调度逻辑。
- 部署：纯前端精简 + 空态文案 + 版本号更新，无表结构变更；回滚只需还原 `AdvertiserReports.tsx` 与样式。
- 边界：本机 8033 旧进程与旧库问题属运行环境问题，不在代码修复范围；需运维重启到当前版本并指向正确数据库后，落库数据才会在报表可见。
**验证**
- 专项：广告主数据十二个专项共 144 passed（含 V4.136 新增静态契约 1 项）。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，680 passed / 2 skipped / 14 subtests passed。
- 前端：`tsc --noEmit` 与 `vite build` 通过。
- 排查取证：项目库连接 / 事实 / 原始三表均为 0 行；测试接口仅回写 `last_test_*` 不落库，仅拉取接口调用 `ingest_records()`；8033 健康检查版本为 4.122.0 且打开废纸篓旧库文件句柄。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.136。

## V4.135 广告主数据 P3：广告主报表
**发布日期**：2026-11-25 10:39
**变更类型**：新增 / 发布
**涉及模块**：广告主数据（广告主报表、KPI 与趋势、维度排行与明细下钻）、后端接口、前端报表页面与 API 封装、系统设置（模块功能开关）、唯一维护文档、专项测试、发版数据
**变更摘要**：按规划完成 P3「广告主报表」，「广告主数据 → 广告主报表」由空白骨架页升级为可用报表。新增概览 KPI、按日趋势、维度排行、佣金明细与逐级下钻四块只读能力，全部读订单最终视图与统一事实表，表头 / 字段名 / 顺序 / 单位 / 格式 / 枚举翻译统一由 api_field_label 配置驱动，前端零硬编码业务字段中文名。报表是纯查询层，不新增表、不改字段、不改视图、不改已有 API 对接与落库链路。
**更新要点**
- 【新增】`backend/advertiser_reports.py`：纯读查询层，零表结构变更。`kpi()` 读订单最终视图 `v_api_order_final`（净销售 / 净佣金 / 订单数 = 视图行数 / 取消单 / 平均客单价，含除零保护）；`trend()` 按事件日期聚合净额并支持维度 EXISTS 筛选；`rankings()` 按广告主 / 品牌 / 事件 / 订单状态排行，先按订单取维度代表值避免原始单 + 修正单重复计单；`details()` 明细分页 / 关键词 / 维度筛选；`drilldown()` 下钻链路「事实行 → 商品子表 / 扩展层 → 原始 JSON + 字段映射规则」。全部按 owner 的 connection_id 隔离。
- 【新增】`api_field_label` 配置驱动：`field_labels(scope)` 下发可见列（column_key / label / unit / format / enum_map / sort_no）；明细查询列由可见列动态推导并做标识符白名单校验，不在代码里硬编码业务列名；`unavailable_metrics` 显式声明上游无花费 / 曝光 / 点击，报表不提供投资回报与转化率类指标。
- 【新增】只读接口：`GET /advertiser-data/reports/labels|dimensions|kpi|trend|rankings|details`、`GET /advertiser-data/reports/drilldown/{fact_id}`，沿用 `_ad_gate()` 开关与 `require_roles(*ROLES)`，受 `ENABLE_ADVERTISER_DATA` 统一控制。
- 【新增】前端 `AdvertiserReports.tsx` 由空白骨架改为完整报表：连接 / 日期 / 维度 / 关键词筛选栏、五张 KPI 卡、纯 SVG 双线趋势图（无外部图表依赖）、可点击联动的维度排行条、动态表头明细表与分页、右侧下钻抽屉（事实行 / 商品明细 / 扩展字段 / 原始 JSON / 字段来源与转换规则）。`api.ts` 增加报表类型与接口封装，`styles.css` 追加 `ad-*` 报表样式，明暗主题变量兼容。
- 【优化】唯一维护文档 5.4 报表页面设计同步 P3 完成状态与四块能力口径；`test_advertiser_api_v4130.py` 的旧静态断言（当时报表页尚未实现）随版本演进更新为「表头配置驱动」契约。
- 【新增】`tests/test_advertiser_reports_v4135.py`：15 项覆盖字段标签顺序 / 单位 / 格式 / 枚举、KPI 视图口径与取消单净额、趋势按日聚合与维度筛选、排行不重复计单与维度白名单防注入、明细分页与动态表头、下钻链路与 owner 隔离、前端零硬编码契约。
**本次优化与更改的功能 / 模块**
- 【新增】「广告主报表」从规划阶段落地为可独立验收页面：先看 KPI 与趋势掌握佣金收入全貌，再按维度排行定位贡献来源，最后下钻到单条订单的上游原始 JSON 与字段映射规则，形成「概览 → 定位 → 溯源」闭环。
- 【新增】表头与口径全部配置化：改中文字段名 / 顺序 / 单位 / 格式 / 枚举翻译只需改 `api_field_label`，无需改前端代码；报表只读既有视图与事实表，与数据采集、字段映射、自动调度完全解耦。
**影响范围**
- 兼容：不改动请求对象（查询字段 `publisherCommissions` 下 `records[]` 的 `PublisherCommission` 明细）、不改 `api_field_map` seed、不改 `v_api_order_final` 视图 SQL、不改 Token 加密与脱敏、不改 V4.124–V4.134 的一级菜单 / API 对接列表 / 弹窗 / 测试 / 拉取 / 回填 / 调度逻辑。
- 部署：本版无新增表、无新增列、无版本迁移；报表为纯查询，重启后即刻可用，回滚只需将 `AdvertiserReports.tsx` 还原为空白骨架页并移除报表接口，数据层无需变更。`ENABLE_ADVERTISER_DATA=False` 关闭整个模块时报表接口同步 404。
- 边界：报表仅呈现佣金收入视角，上游不返回花费 / 曝光 / 点击，不提供投资回报与转化率类指标；本版不含第二渠道模板（P4）；真实 CJ 数据入库后的报表数值验收仍需外部完成。
**验证**
- 专项：广告主数据十二个专项共 143 passed，其中 V4.135 专项 15 项通过。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，679 passed / 2 skipped / 14 subtests passed。
- 前端：`tsc --noEmit` 与 `vite build` 通过（51 modules transformed）。
- 边界验证：单订单原始单 + 负修正单净额归零判取消单且订单数不重复；空结果除零保护返回 0；跨 owner 查询与下钻均隔离；维度参数走白名单不拼入任意列。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.135。

## V4.134 广告主数据 P1-C 历史回填与 P2 自动调度
**发布日期**：2026-11-25 10:26
**变更类型**：新增 / 优化 / 发布
**涉及模块**：广告主数据（调度器与回填）、后端接口、数据接入与运行记录、数据模型与版本迁移、系统设置（启动钩子与全局开关）、前端设置弹窗与 API 封装、唯一维护文档、专项测试、发版数据
**变更摘要**：按规划完成 P1-C 与 P2。新增按 ≤31 天分片的 PublisherCommission 历史回填与跨批次订单净额 / 取消单全量重算；新增复用现有任务表与运行记录表的后台调度协程，按连接配置自动拉取并按水位去重。前端「设置」弹窗新增历史回填入口与运行记录，列表布局与请求对象保持不变。
**更新要点**
- 【新增】`backend/advertiser_scheduler.py`：P1-C + P2 核心。`execute_run()` 单窗口拉取（游标 `sinceCommissionId` 翻页至 `payloadComplete`、按 `api_field_map` 幂等落库、写运行记录）、`backfill()` 历史回填（90 天按 30 天步长 + 1 天重叠切成 3 片，单片跨度不超过 31 天）、`run_due()` 到期扫描（SystemState 水位 + 跨进程抢占锁），启停与 `model_health` 对称。
- 【新增】`advertiser_ingest.recalc_all_voids()`：按 (模板, 连接, 订单) 全量重算净额与 `is_void`，修复修正单在后续批次到达时历史行判定未同步的跨批次缺口；回填结束自动调用一次。
- 【新增】`api_fetch_run.run_mode` 列（manual / scheduled / backfill）与 `V4.134.1` 幂等迁移，历史记录回填为 manual；运行记录接口同步返回该字段。
- 【新增】接口：`POST /advertiser-data/connections/{cid}/backfill`（历史回填，天数可选，默认取任务的 90 天）、`GET /advertiser-data/scheduler`（调度概况与任务状态）、`POST /advertiser-data/scheduler/run`（手动触发一轮到期扫描）。
- 【新增】`PATCH /advertiser-data/connections/{id}` 保存任务设置时同步维护 `api_fetch_task`，任务状态、上次 / 下次运行时间可见；未测试通过的连接不自动请求上游。
- 【新增】前端设置弹窗新增「历史回填」按钮与可折叠「运行记录」（来源 / 状态 / 窗口 / 条数 / 错误），`api.ts` 增加回填、调度概况与运行记录封装；列表列结构、测试抽屉与编辑弹窗不变。
- 【优化】唯一维护文档同步 P1-C / P2 完成状态与运行来源口径；设置弹窗文案改为准确描述自动调度已启用。
- 【新增】`tests/test_advertiser_scheduler_v4134.py`：13 项覆盖分片上限与重叠、游标翻页、重复回填幂等、失败留痕、跨批次取消单重算、调度水位去重、未验证连接跳过、任务失败状态、接口 owner 隔离、迁移与前端契约。
**本次优化与更改的功能 / 模块**
- 【新增】广告主数据从「手动拉一次」升级为「自动持续同步」：启用定期拉取后按频率 / 执行小时运行，首次成功前自动回填历史，之后按回溯窗口重叠拉取以捕获迟到修正。
- 【新增】运行来源可区分，手动补拉 / 定时执行 / 历史回填各自留痕，失败不静默且可从界面直接查阅；Token 仅内存解密，不写运行记录与日志。
**影响范围**
- 兼容：不改动请求对象（仍是查询字段 `publisherCommissions` 下 `records[]` 的 `PublisherCommission` 明细）、不改 `api_field_map` seed、不改 `v_api_order_final` 视图 SQL、不改 Token 加密与脱敏、不改 V4.124–V4.133 的菜单 / 列表 / 弹窗 / 测试窗口 / 手动拉取逻辑。
- 部署：新增列由 `ensure_schema()` 幂等补齐并由 `V4.134.1` 回填历史值；后台协程在 FastAPI startup 启动、shutdown 取消；可用 `ADVERTISER_FETCH_ENABLED=0` 停调度、`ADVERTISER_FETCH_AUTO_BACKFILL=0` 关闭首次自动回填，无需删表或迁移数据即可回滚。
- 边界：CJ 的 200 次 / 5 分钟限流通过翻页间隔 1.6 秒与单片 31 天上限控制；本版不含报表数据接口与界面（P3）、不含第二渠道模板（P4）；真实 CJ 自动回填与真实数据验收仍需外部完成。
**验证**
- 专项：广告主数据十一个专项共 128 passed，其中 V4.134 专项 13 项通过。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，664 passed / 2 skipped / 14 subtests passed。
- 前端：`tsc --noEmit` 与 `vite build` 通过。
- 边界验证：90 天回填切成 3 片且每片跨度 ≤31 天、相邻片重叠 1 天；第二轮回填 inserted=0；失败分片留下 failed 运行记录；同一水位下重复扫描不产生新请求。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.134。

## V4.133 API对接：列表更新时间/同步时间列与编辑配置弹窗
**发布日期**：2026-11-25 10:07
**变更类型**：新增 / 优化 / 发布
**涉及模块**：广告主数据 API 对接（列表、编辑弹窗、连接模型与迁移、前后端契约）、唯一维护文档、专项测试、发版数据
**变更摘要**：按需求在「API对接」列表新增「更新时间」与「API同步时间」两列，并新增「编辑」按钮以弹窗修改已有配置。两列时间采用语义精确的新字段，与 `updated_at`（会被测试 onupdate 刷新）、`last_test_at`（拉取不写）解耦；编辑弹窗复用新建弹窗组件，调用既有 PATCH 接口，保持界面一致。不改动请求对象、落库链路、表结构与既有布局逻辑。
**更新要点**
- 【新增】连接模型新增 `config_updated_at`（新建 + 最近一次配置变更）与 `last_sync_at`（最近一次真实接口请求）两个时间列；`V4.133.1` 版本迁移幂等补列并为历史连接回填（更新时间取 `updated_at`、同步时间取 `last_test_at`）。
- 【优化】四个写入点语义分离：创建连接初始化更新时间；PATCH 修改配置（名称/CID/Endpoint/Token/状态/任务设置）才刷新更新时间；测试回写与手动拉取各自刷新同步时间。测试/拉取不再污染更新时间，配置编辑不再计入同步时间。
- 【新增】列表新增「更新时间」「API同步时间」两列，空值显示「—」；新增「编辑」列与按钮，位置在「设置」「测试」之前，「测试」仍为最后一列。
- 【新增】编辑弹窗复用 `ad-modal` / `ad-form-grid` 组件与控件样式，预填当前名称/CID/Endpoint，Token 留空表示不修改；保存调用 `PATCH /advertiser-data/connections/{id}`，成功后刷新更新时间；支持 Esc / 遮罩 / 取消关闭。模板与定期任务仍走「设置」弹窗。
- 【优化】唯一维护文档 5.1 / 5.2 同步两列时间口径与编辑弹窗设计。
- 【新增】`tests/test_advertiser_api_v4133.py`：覆盖两字段契约、迁移回填与幂等、四个写入点语义、前后端列表与弹窗契约；并更新 V4.125/V4.126/V4.128 三处旧布局静态断言以兼容新列与新弹窗。
**本次优化与更改的功能 / 模块**
- 【新增】列表可按「配置何时改过」与「接口何时请求过」两个独立维度查看，避免此前只能看到会被测试刷新的 `updated_at` 与只覆盖测试的 `last_test_at` 造成的口径混淆。
- 【新增】已配置的连接支持就地编辑，无需删除重建，且编辑动作与测试/拉取在时间列上可区分。
**影响范围**
- 兼容：不改动请求对象（仍是 `PublisherCommission` / 查询字段 `publisherCommissions` / 读取 `records[]`）、不改落库映射与事实表、不改 `v_api_order_final` 视图、不改 Token 加密与脱敏；V4.124–V4.132 的菜单、测试抽屉、设置弹窗与拉取逻辑保持不变。
- 部署：新增两列由 `ensure_schema()` 幂等补齐，历史值由 `V4.133.1` 回填，`git pull` 后重启前后端即可生效，无需人工迁移数据。
- 边界：本版不含自动调度与报表数据接口（P1-C / P2 / P3 仍待后续）。
**验证**
- 专项：广告主数据十个专项共 115 passed，其中 V4.133 专项 16 项通过。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，650 passed / 3 skipped / 14 subtests passed。
- 前端：`tsc --noEmit` 与 `vite build` 通过。
- 语义验证：新建连接更新时间有值、同步时间为空；测试回写后更新时间不变、同步时间有值；迁移对历史行回填两列且可重复执行。

## V4.132 广告主数据 P1-B：映射写入与 PublisherCommission 幂等落库
**发布日期**：2026-11-24 17:08
**变更类型**：新增 / 优化 / 发布
**涉及模块**：后端数据接入模块与接口、数据模型复用、前端与菜单、系统版本、唯一维护文档、专项测试、发版数据
**变更摘要**：按规划推进 P1-B，把 V4.129 拉取的 PublisherCommission 明细真正按 `api_field_map` 落库。新增覆盖检查、幂等写入、items / ext 子表、订单净额归零重算、`replay_mapping()` 保障工具与手动拉取接口；设置弹窗新增「立即拉取明细」。不新增数据库列、不改映射 seed、不改请求对象，P2 自动调度与 P3 报表接口仍待后续。
**更新要点**
- 【新增】`backend/advertiser_ingest.py`：P1-B 核心。覆盖检查（上游字段 ⊆ 已登记映射，未登记写原始层并告警）、按 `source_path → fact.* / item.* / ext.* / __skip__` 分发、transform 统一转换（decimal / utc_date / utc_datetime / bool / enum_map / derived）。
- 【新增】幂等落库：`api_source_record` 按 (template_id, connection_id, external_id) 去重并比对 SHA256；`api_unified_fact` 按 (template_id, external_id) upsert；修正单覆盖更新并重建 items / ext 子表；同 payload 重跑记为 unchanged。修复「更新哈希后误判未变化而跳过修正单」的缺陷。
- 【新增】派生字段：主表 `unit_price_usd = saleAmountUsd / Σ items[].quantity`，子表写入官方 `perItemSaleAmountUsd` 精确值；批量落库后按订单重算 `is_void`（净销售额与净佣金同时归零），不使用不存在的 REVERSED 枚举。
- 【新增】保障二 `replay_mapping()` 与 `POST /advertiser-data/replay`：从原始层重放，默认 `dry_run=true` 只预览覆盖告警、不写库；`GET /advertiser-data/fetch-runs` 查看运行记录。
- 【新增】`POST /advertiser-data/connections/{cid}/fetch`：手动拉取一次明细并落库，写 `api_fetch_run`（窗口、条数、游标、错误、状态）；失败路径同样留痕，不静默丢弃。
- 【优化】前端设置弹窗新增「立即拉取明细」按钮，按测试抽屉的查询窗口执行，回显新增 / 更新 / 未变条数与告警数；`api.ts` 新增 `ApiFetchResult` 与 `fetchConnection()`。
- 【优化】唯一维护文档把 P1-B、任务 4、任务 8 标为已完成，任务 5 标为「批内净额重算已实现、跨批历史回填待 P1-C」，并同步 replay 接口契约与设置弹窗新按钮。
- 【新增】`tests/test_advertiser_ingest_v4132.py`：覆盖映射登记、覆盖告警、幂等重跑、修正单更新、均价/精确单价、ext 属性、取消单重算、replay dry_run/apply、拉取接口成功与失败、前后端契约。
**本次优化与更改的功能 / 模块**
- 【新增】广告主数据链路从「能测试、能看明细」升级为「能把明细按配置幂等写入统一事实表」，原始 JSON 零丢失、每次变更可追溯、改映射后可重放。
- 【新增】三条可维护性保障中的 replay 工具落地，配合 V4.127 的展示名层与版本化列迁移，形成完整的「可修改纠正」闭环。
**影响范围**
- 兼容：不新增数据库列、不改 `schema_migrations` 版本、不改 `api_field_map` seed、不改 `v_api_order_final` 视图 SQL；请求对象仍是 `PublisherCommission`（查询字段 `publisherCommissions`、读取 `records[]`）；V4.124–V4.131 的菜单、列表、弹窗、测试窗口与脱敏逻辑保持不变。
- 边界：本版只做单连接手动拉取与批内重算，**不启动自动调度、不做跨批次历史全量回填、不提供报表数据接口**（P1-C / P2 / P3）；真实 CJ 明细入库验收仍需外部完成。
- 部署：无新增 pip 依赖；执行 `git pull` 后重启前后端即可生效，历史连接与数据无需迁移。
**验证**
- 专项：广告主数据九个专项共 99 passed，其中 V4.132 专项 14 项通过。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，634 passed / 3 skipped / 14 subtests passed。
- 前端：`tsc --noEmit` 与 `vite build` 通过。
- 幂等验证：同 payload 连跑两次 inserted=1 → unchanged=1，事实表 / items / ext / 原始层均只有一行；修正单覆盖更新后子表重建为最新 SKU；正负相抵订单两条明细均判为取消单。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.132。

## V4.131 广告主数据：修复 PublisherCommission 测试返回空明细与聚合口径混淆
**发布日期**：2026-11-24 16:36
**变更类型**：修复 / 优化 / 新增
**涉及模块**：广告主数据 API 对接测试链路、CJ 测试窗口、连接状态回写、测试详情抽屉、唯一维护文档、专项测试、发版数据、系统版本
**变更摘要**：排查并修复「测试请求后只有数据结构、没有具体订单明细数值」的现象。根因是测试窗口固定为最近 1 天，而 CJ 佣金记录通常延迟 1–3 天，导致 `publisherCommissions.records` 返回空数组；同时前端在明细数为 0 时用 `record_count || count` 回退显示包装层聚合 `count`，造成「查到的是聚合报表而非订单明细」的错觉。本版把测试窗口默认扩至近 7 天并允许在抽屉内调整，修正明细数口径与空态提示，不改动请求对象与数据库表结构。
**更新要点**
- 【修复】`routers._test_window()` 统一测试窗口：默认近 7 天（≤31 天），支持 `ApiTestIn.since_event_date / before_event_date` 自定义，非法日期回退默认值而不透传给上游；「保存即测试」与「测试」两条入口共用。
- 【修复】`_record_test_result()` 将 `last_test_count` 的落库口径由包装层聚合 `count` 改为 `record_count`，列表与状态浮层显示的是 PublisherCommission 明细条数，0 条即显示 0。
- 【新增】测试返回增加 `window_since / window_before / hint`：空明细时明确提示查询窗口、延迟 1–3 天与扩窗建议；所有返回路径（含错误路径）都回显实际窗口。
- 【优化】`sample_records` 上限由 3 条提升到 10 条，表格新增佣金金额 USD 列；抽屉新增「00 查询窗口」区（起止日期输入 + 应用并重新测试），显示服务端实际窗口；空态展示后端提示而不是笼统文案。
- 【修复】前端 `record_count || count` → `record_count ?? 0`，`retest()` 与摘要指标不再以聚合值冒充明细数。
- 【优化】唯一维护文档同步 7 天可调整窗口、10 条样例、空态口径与返回契约；同步调整 V4.129 旧专项中「上限 3 条」与 V4.125 旧专项中「last_test_count 取 count」的静态断言，反映新契约。
- 【新增】`tests/test_advertiser_api_v4131.py`：覆盖窗口默认/自定义/非法回退、空明细提示、明细数独立口径、样例上限、前后端契约与文档口径。
**本次优化与更改的功能 / 模块**
- 【优化】API 对接测试从「固定 1 天窗口、失败只能猜」升级为「可调窗口 + 实际窗口回显 + 空明细原因提示」，用户可自行扩大窗口复测真实订单明细，无需改代码。
- 【修复】状态口径统一：列表、浮层、抽屉、提示消息四处都只认明细条数，不再混入统计聚合值。
**影响范围**
- 兼容：请求对象仍为 `PublisherCommission`（查询字段 `publisherCommissions`、读取 `records[]`），Endpoint 仍为 `https://commissions.api.cj.com/query`；不新增数据库列、不改 `api_field_map`、不改 `v_api_order_final` 视图、不改 20 个业务字段与展示名种子；V4.124–V4.130 的菜单、列表、弹窗与请求体结构保持不变。
- 边界：本版只修复测试链路的取数窗口与结果口径，**不做明细幂等落库、事实表写入、自动调度与报表数据接口**（P1-B / P2 / P3）；真实 CJ Token/CID 下的明细数据验收仍需外部完成。
- 部署：无新增 pip 依赖；执行 `git pull` 后重启后端与前端即可生效，历史连接数据无需迁移。
**验证**
- 专项：广告主数据八个专项共 85 passed，其中 V4.131 专项 15 项通过。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，620 passed / 3 skipped / 14 subtests passed。
- 前端：`tsc --noEmit` 与 `vite build` 通过（51 modules，CSS/JS 产物正常）。
- 契约断言：专项自动检查后端不再有固定 1 天测试窗口、前端不再有 `record_count || count` 回退、窗口输入与返回字段齐备、文档含新口径。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.131。

## V4.130 广告主数据：请求对象变更后的字段映射与报表影响修复

**发布日期**：2026-11-24 16:15
**变更类型**：优化 / 新增
**涉及模块**：广告主数据 CJ 请求模板、字段映射配置与版本化迁移、统一事实表注释、唯一维护文档、专项测试、发版数据、系统版本
**变更摘要**：针对 V4.129 把请求对象改为 PublisherCommission 明细后的连带影响做完整排查，确认数据库表结构与「广告主报表」骨架均无需改动，并修复两处真实缺口：请求漏取官方 Item 对象的 `perItemSaleAmountUsd`（子表精确单价依赖），以及 `api_field_map` 只有表结构、没有任何映射登记（覆盖检查无法运行）。同时清理存储设计文档中的 `REVERSED` 残留，统一为官方枚举与净额归零判定口径。
**更新要点**
- 【优化】`advertiser_api.PUBLISHER_COMMISSION_FIELDS` 的 items 块补齐 `perItemSaleAmountUsd`；官方 Item 对象确有该字段，`api_fact_item.unit_price_usd` 与映射表 #10 的子表精确单价规则因此可落地，`perItemSaleAmountPubCurrency` 继续保留供扩展层。
- 【新增】`migrations.CJ_FIELD_MAP_SEED`：CJ 模板字段映射的唯一权威配置，覆盖 12 核心字段（含 advertiserName 双目标与 is_void 派生）、6 个新增可见字段、合并技术列、items 子表、23 个 ext 字段与 5 个显式 skip 字段；`V4.130.1` 幂等写入 `api_field_map`，`verify_schema()` 新增 `map_count`。
- 【优化】映射口径固化：`advertiserName → fact.advertiser_name + fact.campaign_name`（Q3 同源）、`actionTrackerName → fact.event_name`（Q4）、`eventDate → fact.event_date`（Q2）、`verticalAttributes.campaignName → __skip__`（避免与品牌名同源歧义）、`postingDate` 仅对账保留而增量水位按 `eventDate`。
- 【优化】唯一维护文档清除 `REVERSED` 残留：`action_status` 官方枚举改为 `closed / extended / locked / new`，`validationStatus` 改为 `PENDING / ACCEPTED / DECLINED / AUTOMATED`，取消单判定统一为订单净额归零（与 `v_api_order_final` 实现一致）；第四章补 6 个新增字段、Item USD 精确单价、ext/skip 与映射已落库说明；功能开发文档同步映射 seed 口径。
- 【优化】`models.py` 的 `posting_date` 注释同步为「对账保留（增量水位按 eventDate）」，消除模型注释与查询/文档口径差异。
- 【新增】`tests/test_advertiser_api_v4130.py`：覆盖请求字段 ⊆ 映射登记集合、关键映射语义、V4.130.1 幂等 seed、视图列未变、报表骨架无字段硬编码与文档口径纠正。
**本次优化与更改的功能 / 模块**
- 【优化】广告主数据从「映射只写在文档」升级为「映射登记已落库且可覆盖检查」：V4.129 的请求明细字段现在每个都有明确目标（fact / item / ext / __skip__），P1-B 落库时未登记字段会告警而不是静默丢弃。
**影响范围**
- 兼容：不新增数据库列、不改 `v_api_order_final` 视图 SQL、不改 20 个业务字段与 26 行展示名种子；「广告主报表」仍是 P3 规划中的页面骨架，无数据接口、无字段硬编码，本次不改其界面与契约；V4.124–V4.129 的菜单、列表、弹窗与测试滑窗保持不变。
- 边界：本版只补配置与口径，**仍不做明细幂等落库、统一事实表写入、自动调度与报表数据接口**（P1-B / P2 / P3）；真实 CJ 明细验收仍是外部验收项。
- 部署：无新增 pip 依赖；执行 `git pull` 后重启后端，`ensure_schema()` 自动执行 `V4.130.1` 幂等 seed 并写版本记录，历史连接与数据无需迁移。
**验证**
- 专项：广告主数据七个专项共 73 passed；其中 V4.130 专项 9 项通过。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，608 passed / 3 skipped / 14 subtests passed（默认库历史脏数据会触发既有 V4.119 归并专项失败，本次未动默认库数据）。
- 覆盖率检查：专项从 `PUBLISHER_COMMISSION_FIELDS` 自动提取请求字段（含 `items[]` / `verticalAttributes.` 前缀），断言全部存在于 `CJ_FIELD_MAP_SEED` 的 `source_path` 集合，缺失即 FAIL。
- 迁移检查：空库执行 `ensure_schema()` 后 `api_field_map` 行数等于种子行数，`schema_migrations` 含 `V4.130.1`，再次执行无新增列与重复行；`verify_schema()` 返回 `map_count` 与 20 业务字段、视图就绪。
- 文档：存储设计文档不再出现 `action_status = 'REVERSED'` 与旧枚举，功能开发文档映射行标注 seed 来源。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.130。

## V4.129 API对接：明确请求 PublisherCommission 订单明细

**发布日期**：2026-11-24 16:06
**变更类型**：优化 / 新增
**涉及模块**：广告主数据 / API对接页与测试滑窗、后端 CJ GraphQL 查询模板与测试契约、模板与接口 Schemas、唯一维护文档、专项测试、发版数据、系统版本
**变更摘要**：按用户确认的目标，把「测试连接」从只取 count 等统计字段，改为真正请求 CJ 官方 Object: PublisherCommission 的逐条订单佣金明细（publisherCommissions.records，含 items 与 advertiser-supplied custom attributes）。代码、请求体、接口契约与界面统一写明请求对象是 PublisherCommission，滑窗新增请求对象标识与明细样例区，确保读取的是订单明细而非统计报表；查询字段仍遵循官方定义 publisherCommissions。
**更新要点**
- 【优化】`advertiser_api.py` 新增 `PUBLISHER_COMMISSION_FIELDS` 与 `build_detail_payload()`，operation name 明确为 `PublisherCommission`，请求体显式包含 `publisherCommissions { count limit maxCommissionId payloadComplete records { ... } }`；`records` 内固化 aid / clickDate / commissionId / orderId / original / originalActionId / advertiserName / actionTrackerName / eventDate / 金额字段、items 明细与 verticalAttributes 广告主自定义属性。
- 【优化】模板新增 `record_object=PublisherCommission` 与官方英文定义 `record_object_desc`，通过 `/advertiser-data/templates` 与 `ApiTemplateOut` 对外输出；`sinceCommissionId` 游标参数预留给 P1-B 续页，测试连接不传。
- 【新增】测试返回契约新增 `record_object` / `record_count` / `sample_records`（前 3 条明细），`count` 仍保留官方包装层语义；明细样例递归脱敏，同时修复 `response` 结构化对象未脱敏的问题，Token 不再以任何形式回显。
- 【优化】API对接页测试滑窗顶部固定显示「请求对象 PublisherCommission」及官方定义，说明查询字段 publisherCommissions → records[] 是逐条明细而非 count 统计；摘要指标改为「明细记录」，新增「02 订单佣金明细」样例表（commissionId / orderId / advertiserName / eventDate / original / items），原响应原文顺延为「03」。
- 【优化】唯一维护文档 3.1 表格增加请求对象行并把查询骨架统一为 `sinceEventDate / beforeEventDate + records`，3.2 补充官方对象层级澄清，4.1 与水位管理口径统一为事件日期，5.3 滑窗设计同步新分区。
- 【新增】`tests/test_advertiser_api_v4129.py`：覆盖真实请求体结构、items 与自定义属性、模板对外声明、records 解析与脱敏、样例上限、错误路径契约、前端文案与文档一致性。
**本次优化与更改的功能 / 模块**
- 【优化】API对接页的「测试」动作从凭据连通性检查升级为订单佣金明细抽样：一次请求即可确认拉取的是 PublisherCommission 明细、看到订单级样例，并保留完整请求/响应原文用于排查。
**影响范围**
- 兼容：保留 V4.124–V4.128 的菜单、列表列、状态浮层、新建弹窗、设置弹窗与测试详情滑窗结构；不新增数据库列、不修改既有表结构；`count` 字段语义不变，前端仍可读取。
- 边界：本次只改请求内容与展示，不做明细幂等落库、统一事实表映射、自动调度与报表（P1-B/P2/P3 后续版本）；真实 CJ Token/CID 与明细数据验收仍是外部验收项，模拟测试不能替代。
- 部署：无新增 pip 依赖；`git pull` 后重启后端、更新前端静态资源即可；历史连接无需迁移。
**验证**
- 专项：广告主数据六个专项共 64 passed；其中 V4.129 专项 11 项通过。
- 全量回归：全新隔离 SQLite 库执行 `pytest tests`，599 passed / 3 skipped / 14 subtests passed（默认库存在历史脏数据会触发既有 V4.119 归并专项失败，本次未改动默认库数据）。
- 前端：`tsc --noEmit` 通过，`vite build` 通过（51 modules，构建无报错）。
- 安全：请求体只含 CID 与事件日期窗口，Token 仅进入 Authorization 头；专项断言响应原文、`response` 对象与明细样例中的 Token 片段全部替换为 `***`。
- 文档：唯一维护文档 3.1 / 3.2 / 4.1 / 5.3 已同步请求对象、records 查询骨架与滑窗新分区。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.129。

## V4.128 API对接：列表测试列与右侧测试详情滑窗

**发布日期**：2026-11-24 15:22
**变更类型**：优化 / 新增
**涉及模块**：广告主数据 / API对接页、前端右侧滑窗与样式、后端接口与测试数据契约、连接模型与轻量迁移、发版数据、功能开发文档、专项测试、发版流程、系统版本
**变更摘要**：按用户确认的交互，在「API对接」列表最后一列新增「测试」按钮；点击后用当前连接的加密凭据发起一次真实 CJ 请求，右侧滑出测试详情面板，顶部展示完整请求链接与状态摘要，下方完整展示请求体和上游响应原文。为支持「完整可查」而不是只显示摘要，后端统一所有测试返回路径的详情字段并把请求链接 / GraphQL 请求体 / 响应原文留痕到连接表，Token 全程脱敏不回显。
**更新要点**
- 【新增】列表最后一列为「测试」，点击即发起真实请求；请求期间按钮显示「测试中…」，完成后列表状态与状态浮层同步刷新。
- 【新增】右侧测试详情滑窗：状态摘要（成功/失败、HTTP Code、返回记录数、测试时间）、完整 Endpoint、GraphQL 请求体、上游响应原文；JSON 自动格式化，非 JSON 原样展示，响应区可完整滚动。
- 【新增】滑窗支持「关闭」按钮、点击遮罩、Esc 三种关闭方式；底部可「重新测试」；沿用系统 CSS 变量与作用域样式，移动端自适应，遵循减少动效偏好。
- 【新增】`advertiser_api.test_connection()` 所有返回路径统一输出 `request_url` / `request_method` / `request_body` / `response_text` / `response` / `tested_at`；错误响应保留上游原文，Token 片段统一替换为 `***`。
- 【新增】`api_connection` 新增 `last_test_url` / `last_test_request_body` / `last_test_response_text`，由 `ensure_schema()` 幂等补列并登记 `V4.128.1`；`_record_test_result()` 与 `ApiConnectionOut` 同步回写 / 输出。
- 【新增】`tests/test_advertiser_api_v4128.py`：覆盖完整请求/响应契约、Token 脱敏、旧库补列、版本记录、结果回写与前端滑窗结构；同步放宽 V4.127 版本列表断言以兼容后续版本追加。
**本次优化与更改的功能 / 模块**
- 【优化】API对接页从「只能看状态摘要」升级为「状态 + 请求链接 + 请求体 + 响应原文」一体查阅，便于按 CJ 官方错误说明排查 Token、CID、Endpoint 与查询参数问题。
**影响范围**
- 兼容：保留 V4.125 的列表列、状态浮层、新建弹窗与设置弹窗；保留 V4.126 弹窗组件样式；侧栏菜单「广告主数据 / 广告主API / 广告主报表」不变。
- 边界：本次只展示测试请求与响应，不新增真实拉取落库与自动调度执行；真实 CJ 凭据与数据验收仍为外部验收项，模拟测试不能替代。
- 部署：无新增 pip 依赖；执行 `git pull` 后重启后端，`ensure_schema()` 自动补齐三列并记版本；前端更新静态资源即可。
**验证**
- 专项：`test_advertiser_api_v4128.py` 与广告主数据既有专项共 53 passed。
- 全量回归：在全新隔离 SQLite 库执行 `pytest tests`，588 passed / 3 skipped / 14 subtests passed（默认库残留同名素材会触发既有 V4.119 归并专项的脏数据断言，本次未改动默认库数据）。
- 前端：`tsc --noEmit` 通过；`vite build` 通过（51 modules，构建无报错）。
- 浏览器实测：隔离端口后端 8054 + 前端 5187 + 本地 CJ 模拟响应 8055，登录后列表最后一列显示「测试」；点击后右侧滑出，顶部显示 `POST http://127.0.0.1:8055/query`、HTTP 200、返回 128 条，下方完整展示 GraphQL 请求体与上游 JSON 响应；点击「关闭」后滑窗消失、列表状态同步为「成功」。验收用假 Token 与本地模拟响应，未使用真实 CJ 凭据，临时服务与数据已清理。
- 安全：请求体只含 CID 与事件日期窗口，Token 仅进入 Authorization 头；测试断言响应原文中的 Token 片段被替换为 `***`，前端固定显示 `Bearer ****`。
- 文档：唯一维护文档第五章新增 5.3「测试」右侧滑窗，并把报表设计顺延为 5.4。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.128。

## V4.127 广告主数据 P1-A：统一事实表建表与版本化迁移骨架

**发布日期**：2026-11-24 15:12
**变更类型**：新增 / 发布
**涉及模块**：广告主数据统一数据存储层、数据模型与轻量迁移、版本化迁移工具、展示名配置层、订单最终视图、后端接口与迁移脚本、回滚工具、功能开发文档、专项测试、发版数据、发版流程、系统版本
**变更摘要**：按唯一维护文档第六 / 七 / 八章落地 P1-A：一次性建齐原始层、统一事实表（20 业务字段）、商品/扩展/映射/展示名等表与定期任务预留表，创建订单最终视图 `v_api_order_final`，并兑现三条保障中的保障一（展示名配置种子）与保障三（版本化列迁移 + `rename_column()` 四处同步 + 迁移前自动备份）。本版只建结构与配置，不改任何现有表与业务、不写入真实拉取数据；映射落库与订单回填留待 P1-B/C。
**更新要点**
- 【新增】`models.py` 新增 10 张表：`api_source_record`（原始 JSON + SHA256 + 唯一幂等键）、`api_unified_fact`（20 业务字段 + 技术列，金额 `Numeric(18,6)`）、`api_fact_item`、`api_fact_ext`、`api_field_map`（含 version/effective_from）、`api_field_label`、`schema_migrations`、`schema_view_def`、`api_fetch_task` / `api_fetch_run`（P2 预留）。冲突消解按定稿：commissionId 复用已有列、correctionReason/postingDate 提升可见、6 列新建、不建 `item_quantity`。
- 【新增】订单最终视图 `v_api_order_final`：按 `(template_id, connection_id, order_id)` 聚合净销售 / 净佣金 / 明细条数，正负相抵净额归零判 `is_void`；不使用 CJ 官方不存在的 `REVERSED` 枚举；视图定义存 `schema_view_def`，改名时同步重建。
- 【新增】保障一：`api_field_label` 幂等种子 20 行 fact 配置（含中文名、单位、格式、枚举中文映射、排序、可见性）+ 6 行 order_final 配置；`correction_reason` / `posting_date` 按 V3.1 定稿为可见。报表前端仍不硬编码中文字段名。
- 【新增】保障三：`migrations.py` 版本函数注册 + `schema_migrations` 版本记录（V4.127.1），`ensure_schema()` 可重复执行；`rename_column(old,new)` 一次同步物理列 → `api_field_map.target_field` → `api_field_label` → 视图定义，并审计写入代码/报表查询中的旧名引用，有残留则拒绝迁移（除非显式 force）。
- 【新增】`scripts/migrate_column.py`：`audit` 只检查引用、`rename` 默认预演，加 `--yes` 才写库且自动先做数据库在线快照；`rollback.py` 的 `restore-db` 可回滚。只改「叫法」仍优先改展示名，不动物理列。
- 【新增】`tests/test_advertiser_schema_v4127.py`：15 项专项，覆盖空库建表 / 9 张表 + 视图 / 20 字段与 Numeric 精度 / 历史库补列 / 幂等 / 冲突比对 / 种子可见性 / 视图净额与取消单 / 改名四处同步与非法输入。
**本次优化与更改的功能 / 模块**
- 【新增】广告主数据从「只有模板和连接」升级为「具备统一数据存储骨架」：后续 P1-B 可按映射写历史、P1-C 可合并回填、P3 报表可读展示名配置，无需再改表结构。
**影响范围**
- 兼容：只新增表、视图与迁移工具，不修改既有 `api_channel_template` / `api_connection` / 其他业务表结构与数据；菜单、页面、接口契约完全不变。
- 边界：本版无数据拉取、无报表界面变更、无自动调度执行；真实 CJ 数据验收仍依赖有效 Token/CID，模拟测试不能替代。
- 部署：无新增 pip 依赖；真实环境执行 `git pull && docker compose up -d --build`，启动时 `ensure_schema()` 自动建表并写版本记录。需要改列名时按 `scripts/migrate_column.py` 流程先备份再迁移。
**验证**
- 专项：`test_advertiser_schema_v4127.py` 15/15 通过。
- 全量回归：全绿（含 V4.124/V4.125/V4.126 既有契约测试无回归）；前端 `tsc --noEmit` 与 `vite build` 通过（本版无前端改动）。
- 隔离库实测：空库两次 `ensure_schema()` 幂等、版本只应用一次；模拟旧库缺列自动补齐；正负相抵订单视图 `is_void=1` 且净额为 0；改名 `sale_amount_usd → net_sale_amount_usd` 后物理列 / 映射 / 展示名 / 视图 SQL 四处一致，版本表有记录；`verify_schema()` 返回 tables_ok / view_ok / 20 字段 / 20 标签。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.127。

## V4.126 API对接：弹窗表单组件样式统一

**发布日期**：2026-11-24 14:58
**变更类型**：优化 / 新增
**涉及模块**：广告主数据 / API对接页、前端全局样式、专项测试、发版数据、发版流程、系统版本
**变更摘要**：按用户截图反馈，统一「新建 API 对接」与「设置 · 定期任务」两个弹窗中输入框、下拉框、数字框的组件外观。此前全局 `select` 规则把下拉框设为 13.5px / 8px padding / 白底，而输入框为 14px / 10px padding / 浅灰底，导致同排控件高度、颜色与边框观感不一致。本版本在弹窗表单作用域内覆盖为同一套尺寸与视觉：38px 高、8px 圆角、1px `--border` 边框、`--card` 背景、`--text` 文字、14px 字号，并共用同一焦点态（主色边框 + 3px 柔光）。复选框保持原有行内勾选样式，不受影响。
**更新要点**
- 【优化】`styles.css` 新增 V4.126 作用域规则：`.ad-modal .ad-form-grid` 下的输入框（排除 checkbox/radio）、下拉框、数字框统一 `height: 38px` / `padding: 0 12px` / `border: 1px solid var(--border)` / `border-radius: 8px` / `background: var(--card)` / `font-size: 14px`。
- 【优化】统一焦点态：输入框与下拉框 `:focus` 均为 `outline: none`、`border-color: var(--primary)`、`box-shadow: 0 0 0 3px rgba(31,78,121,.12)`；placeholder 颜色统一为 `#aab4c0`。
- 【优化】用 `min-width: 0` 覆盖全局 `select` 的 `min-width: 150px`，两列栅格中控件宽度一致，不再出现下拉框被撑破或错位。
- 【新增】`tests/test_advertiser_api_v4126.py`：6 项专项，校验统一规则存在、关键属性一致、焦点态共用、复选框排除、后续无拆散样式、双弹窗结构未变。
**本次优化与更改的功能 / 模块**
- 【优化】API对接页两个弹窗的表单组件：同排「广告主 + 模板」「API Token + 发布者 CID」高度与边框完全一致，视觉收敛到系统变量驱动的统一风格。
**影响范围**
- 兼容：仅作用于 `.ad-modal .ad-form-grid` 作用域，其他页面、菜单、全局表单控件与业务逻辑均不改；无后端接口、数据库字段与数据结构变更。
- 边界：本次只统一外观与交互反馈，不调整字段、校验规则、保存即测试流程或定期任务配置语义。
- 部署：无新增依赖；真实环境执行 `git pull && docker compose up -d --build` 或直接更新前端静态资源后生效。
**验证**
- 专项：`test_advertiser_api_v4126.py` 6/6 通过；前端 `tsc --noEmit` 与 `vite build` 通过。
- 全量回归：561 passed / 3 skipped / 14 subtests passed（含 V4.124/V4.125 既有契约测试与新增 6 项样式专项，无回归）。
- 浏览器实测：隔离端口后端 8054 + 前端 5186，登录后打开「新建 API 对接」弹窗截图确认：广告主输入框与模板下拉框同高、同白底、同圆角与边框，API Token 与 CID 同排一致，Endpoint 单行对齐；弹窗「保存」按钮与列表页未受影响，验收环境已清理。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.126（同进程检查的模块缓存假性 FAIL 按既有约定排除）。

## V4.125 API对接：列表化改造 + 保存即测试 + 设置弹窗

**发布日期**：2026-11-24 14:35
**变更类型**：优化
**涉及模块**：广告主数据 / API对接页面、后端连接与测试接口、数据模型与轻量迁移、API 契约、前端样式、功能开发文档、回归测试、发版数据、发版流程、系统版本
**变更摘要**：按用户确认意见重构「广告主API」界面：页面标题改为「API对接」并删除顶部解释文案；移除可用模板样例卡与定期任务/运行记录预留区块，只保留一张已对接 API 列表。列表列严格按 NO.（自增 id，从大到小）/ 广告主（原「连接名称」）/ 模板（显示名「CJ联盟」）/ 状态 / 设置 展示；状态悬浮显示 HTTP code 与返回明细；新建改为单弹窗单「保存」按钮，一次提交完成创建 + 真实接口测试 + 状态回写；「设置」按钮打开定期任务配置弹窗，可保存、重新测试与删除。改动仅限本模块，其他菜单布局与功能不变。
**更新要点**
- 【优化】`AdvertiserApi.tsx` 重写为「一张列表 + 两个弹窗」：标题「API对接」、无顶部说明；列表五列 NO. / 广告主 / 模板 / 状态 / 设置，NO. 取连接自增 id 且按 id 倒序；删除模板样例区与后续阶段预留区块。
- 【新增】状态悬浮浮层：成功显示 `HTTP <code> · 请求成功`、返回条数、测试时间；失败显示 HTTP code 与脱敏错误摘要；未测试给出明确引导。浮层用 fixed 定位，避免被表格滚动容器裁剪。
- 【新增】「保存即测试」：新增 `POST /advertiser-data/connections/create-and-test`，创建连接后用加密凭据立即真实请求并回写状态，消除「已保存但未测试」的中间态；新建弹窗只保留一个「保存」按钮。
- 【新增】连接表新增 `last_test_http_code` / `last_test_count` / `schedule_json` 三列，`ensure_schema()` 自动补齐旧库；`ApiConnectionOut` 同步输出状态明细与规范化后的定期任务设置。
- 【新增】列表「设置」弹窗：启用开关、频率（每日 / 每 6 小时）、执行小时、回溯窗口、首次回填，可保存配置、重新测试、删除连接；配置经白名单规范化后入库，实际调度执行仍按规划在后续阶段接入，不提前宣称已自动运行。
- 【优化】CJ 模板界面显示名由「CJ 联盟 · 发布者佣金明细」改为「CJ联盟」；底层 `cj_publisher_commissions` 不变，历史连接免数据迁移。
- 【新增】`tests/test_advertiser_api_v4125.py`：覆盖模板名、新增列与契约、保存即测试接口、状态浮层、双弹窗交互、定期任务规范化与旧菜单/安全契约兼容。
**本次优化与更改的功能 / 模块**
- 【优化】API对接页：从四区展示收敛为单列表，用户操作路径缩短为「新建 → 保存 → 看状态」与「设置 → 保存/重测」。
- 【新增】后端连接状态明细与任务配置持久化，定期任务由「只有预留区块」变为「可配置并保存」。
**影响范围**
- 兼容：仅改广告主数据模块；一级菜单「广告主数据」及其下「广告主API」「广告主报表」标签不变，现有模块代码、布局、数据不动；旧库由 `ensure_schema()` 自动补列。
- 边界：模板数据源仍从服务端读取，仅不再展示样例卡；保存即测试会发起一次真实上游请求，测试失败也保留连接以便按状态明细排查；自动调度与运行记录不在本版本范围。
- 部署：无新增 pip 依赖；真实环境执行 `git pull && docker compose up -d --build` 后生效。
**验证**
- 专项：`test_advertiser_api_v4125.py` 与 `test_advertiser_api_v4124.py` 共 20/20 通过；后端 `py_compile` 通过。
- 全量回归：555 passed / 3 skipped / 14 subtests passed；前端 `tsc --noEmit` 与 `vite build` 通过（51 modules，构建无报错）。
- 浏览器实测：隔离端口后端 8053 + 前端 5185，登录后在「广告主数据 / API对接」确认页头标题与空文案、五列列表（NO. 3→2→1 倒序、模板 CJ联盟）、成功/失败状态悬浮分别显示 `HTTP 200 · 128 条` 与 `HTTP 401 · 认证失败明细`；新建弹窗填表点一次「保存」后弹窗关闭、列表新增记录并展示真实 HTTP 401 失败状态；设置弹窗勾选启用并保存后重新打开仍为启用。验收用隔离数据库与临时前后端进程，结束后已清理，未改动现有 5173 / 8000 / 8033 服务。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过，系统版本 / CHANGELOG / 发布数据一致为 V4.125（同进程检查因模块缓存出现的一次假性 FAIL 已按既有约定排除）。

## V4.124 广告主数据：新增一级菜单 + CJ 佣金模板与连接（P0）

**发布日期**：2026-11-24 12:20
**变更类型**：新增
**涉及模块**：新增一级菜单「广告主数据」（下设「广告主API」「广告主报表」）、后端广告主 API 模块（模板 / 连接 / 测试连接）、数据模型、API 契约、前端独立页面与样式、回滚工具、发版数据、发版流程、系统版本
**变更摘要**：按《广告主数据模块 · 功能开发文档》启动全新一级功能模块开发。P0 先建立与现有系统完全隔离的「广告主数据」一级菜单和两个二级页面骨架，预置 CJ 联盟发布者佣金标准模板，用户只需填写 API Token / 发布者 CID / Endpoint 即可建立连接并测试连通性；Token 加密存储、列表脱敏、不回显、不写日志。同时建立版本回滚三件套（基线标签、数据库在线快照工具、功能开关），确保设计有误时可低成本回退且不丢数据。
**更新要点**
- 【新增】一级菜单「广告主数据」：`#/advertiser-data/api`（广告主API）与 `#/advertiser-data/reports`（广告主报表）两个二级路由；现有菜单分组、布局、路由与功能一项未改，仅共享登录态与全局样式变量。
- 【新增】后端 `advertiser_api.py`：预置只读模板 `cj_publisher_commissions`（Bearer 认证、`publisherCommissions` 查询、游标分页、日期≤31天/单次≤10000条/200次5分钟限制）；测试连接用 1 天窗口只读 `count`，真实 HTTP 调用，错误按认证失败 / HTTP 错误 / GraphQL 错误分类并脱敏。
- 【新增】`api_channel_template` 与 `api_connection` 两表：模板固化"接口怎么调"，连接只存用户填的三项；Token 用 HMAC 派生密钥 + CTR 流 + encrypt-then-MAC 加密（零新增依赖，密钥沿用 AUTH_SECRET），篡改可检出。
- 【新增】前端「广告主API」四区骨架：① 可用模板 ② 我的连接（新建 / 测试 / 启用 / 停用 / 删除）已可用；③ 定期任务 ④ 运行记录保留为后续阶段入口。「广告主报表」保留为后续阶段入口，明确标注本 API 无花费数据、不计算 ROAS / ROI。
- 【新增】回滚保障：`v4.123-baseline` 基线标签；`scripts/rollback.py`（backup-db 在线快照 / list-tags / plan-code / restore-db 先备后恢复）；`version.ENABLE_ADVERTISER_DATA` 开关（改 False 即隐藏入口并让接口 404，不删表不迁数据）。
- 【新增】`tests/test_advertiser_api_v4124.py`：8 项专项，覆盖模板必填项、Token 加密/篡改、测试连接成功与错误分类、9 项新增字段已入设计文档、菜单隔离与功能开关。
**本次优化与更改的功能 / 模块**
- 【新增】广告主数据模块首次落地：模板 → 连接 → （后续）任务 → 报表 的分层结构起点。
- 【新增】回滚工具链：开发期每次发版前可打数据库快照，设计错误时先代码回滚（git revert / 功能开关），必要时再数据回滚。
**影响范围**
- 兼容：新增一级菜单与两张新表，现有模块的代码、菜单、布局、数据完全不动；`ensure_schema()` 自愈建表，旧库无需手工迁移。
- 边界：P0 不含定时拉取、统一事实表、报表数据；连接必须"测试通过"才能启用；Token 仅加密入库，任何接口都不回显。
- 部署：新增模块无新增 pip 依赖；真实环境执行 `git pull && docker compose up -d --build` 后生效。
**验证**
- 专项：`test_advertiser_api_v4124.py` 8/8 通过；全量回归 542 passed / 3 skipped / 14 subtests passed（发版校验项在补齐本条后复跑通过）。
- 前端：`tsc --noEmit` 与 `vite build` 通过。
- 后端：建表与 Token 加密/解密/篡改拒绝实测通过；测试连接用 mock 覆盖成功 200、401、GraphQL 错误三类。
- `prepare_release --sync` 后独立进程 `prepare_release --check` 通过。
## V4.123 素材创意模板库：已解构图片原图预览（素材库 / 已沉淀模板）

**发布日期**：2026-11-20 16:50
**变更类型**：优化
**涉及模块**：素材创意模板库（素材库卡片 / 分类归并模板卡片）、前端交互与样式、回归测试、发版数据、发版流程、系统版本
**变更摘要**：按用户决议，已解构的图片在两个保存位置都能查阅原图：「素材库 · 导入与解构 → ② 素材库」的素材卡片缩略图可点击，打开原图预览弹层；「分类归并 · 模板沉淀 → ② 已沉淀模板」的 golden 缩略图与「查看原图」按钮共用同一弹层。预览始终优先使用原始 `file`（缺失才回退 `thumb`），支持新窗口打开原图、Esc / 点遮罩 / 关闭按钮退出。顺带修复直接进入归并 Tab 时未加载素材列表导致 golden 无预览的问题。视频素材保持原行为不变。
**更新要点**
- 【新增】`CreativeAnalysis.tsx` 新增共用原图预览弹层：标题 / 来源 / 平台 / 尺寸 / 状态，展示原始图片，提供「在新窗口打开原图」；点击缩略图或「查看原图」进入，Esc、点遮罩、关闭按钮均可退出。
- 【新增】素材库卡片对图片显示「查看原图」悬浮提示，缩略图可直接点击；已沉淀模板卡片的 golden 缩略图与文字按钮均可打开同一预览。
- 【修复】归并 Tab 的 `useEffect` 补上 `loadAssets()`，直接进入「分类归并 · 模板沉淀」也能拿到 golden 素材的文件字段；素材加载上限由 100 提到 500，减少归档较久的 golden 落在首批之外而无预览的情况。
- 【保持】视频卡片不进入图片原图预览；原图优先用 `file`，只有缺原图时才退回 `thumb`，不改写元数据、不触发任何模型调用或付费链路。
**本次优化与更改的功能 / 模块**
- 【优化】素材库 · 素材卡片：缩略图即预览入口，查阅原图无需离开当前 Tab。
- 【优化】分类归并 · 已沉淀模板：golden 原图可直接预览，模板骨架与归并关系保持不变。
- 【新增】`tests/test_original_preview_v4123.py`：覆盖两处入口、归并 Tab 加载素材、原图优先取 `file` 以及 `/files/<name>` 静态路由返回真实图片字节。
**影响范围**
- 兼容：纯前端交互与测试新增；后端接口、数据模型、解构 / 归并 / 出图链路均未改动，历史素材与模板完全兼容。
- 边界：只覆盖图片素材；视频缩略图仍按原样展示，不提供图片原图弹层。原图由既有 `/files/*` 静态路由提供，无需新权限或新依赖。
- 部署：纯代码升级；真实环境执行 `git pull && docker compose up -d --build` 后生效。
**验证**
- 专项：新增 `test_original_preview_v4123.py` 4/4 通过；模板库全系列 67/67 通过。
- 全量回归：535 passed / 3 skipped / 14 subtests passed；前端 `tsc --noEmit` 与 `vite build` 通过。
- 浏览器实测：隔离后端 8043 + 前端 5182，登录后在素材库卡片与已沉淀模板卡片分别点击「查看原图」，均弹出同一原图预览并正确展示 640×360 测试原图；「在新窗口打开原图」链接指向 `/files/v4123_demo.png`。
- `prepare_release --check` 独立进程通过，系统版本 / CHANGELOG / 发布数据一致为 V4.123。

## V4.122 素材创意模板库：移除「投放授权声明」子模块与强制闸门

**发布日期**：2026-11-20 15:22
**变更类型**：优化 / 移除
**涉及模块**：素材创意模板库（导入 / 解构 / 归并 / 模板沉淀）、素材工作坊（按模板创作）、后端数据模型与契约、后端授权闸门（整体移除）、后端归并引擎、前端解构页、前端 API、前端样式、回归测试、发版数据、发版流程、系统版本
**变更摘要**：按用户决议整体移除素材创意模板库中的「投放授权声明」要求与子模块，并在全流程删除相关内容。素材导入不再要求 `rights_status` / 授权说明；解构、归并候选与确认、golden 改选、模板新建 / 编辑、工作坊按模板创作入队前不再执行任何授权闸门；删除授权补录接口与前端授权声明表单、徽标、补录入口。图片 / 视频解构、12 类分类与归并键、按框架完整度选 golden 沉淀模板、按模板创作（只影响图片）等能力全部保留且语义不变——按模板创作仅保留模板自身基础可用性校验（归属 / 状态 / 骨架 / 引用素材完整），不再涉及投放授权。此为流程收敛，不改变任何真实视觉模型调用、诚实降级与付费出片规则。
**更新要点**
- 【移除】`backend/template_gate.py` 删除授权闸门全部实现：`normalize_status()`、`rights_check()`、授权状态常量与 `REQUIRED_ACTION`；`template_gate()` 移除对 golden / 归并素材的授权逐条判定，仅保留模板自身可用性校验；`template_style_opts()`（模板骨架只注入视觉路线）原样保留。
- 【移除】`CreativeAssetSource` 删除 `rights_status` / `rights_note` 两列（旧库残留列不参与任何读写，无需回填）；`AssetSourceOut` / `AssetSourceCreate` / `AssetImportRequest` 同步移除；删除 `RightsPatchIn` schema 与 `PATCH /template-library/assets/{id}/rights` 补录接口。
- 【移除】`backend/routers.py` 删除 `_rights_block()` / `_rights_on_import()` 与全部闸门调用点（导入、统一导入、图片/视频解构、归并确认、模板新建与编辑、golden 改选）；保留模板 edit 的素材归属校验（防越权引用他人素材）。
- 【移除】`backend/asset_merge.py` 的 `eligibility()` 恢复为单参数（仅解构结果），`build_candidates()` 不再传入授权状态；候选排除原因只保留解构状态 / 完整度 / 分类归一三类。
- 【移除】前端 `CreativeAnalysis.tsx` 删除导入区「投放授权声明」必填子模块、素材卡授权徽标与说明、补录按钮与补录编辑区、解构按钮的授权禁用与 `checkRightsGate()` / `saveRights()`；`MaterialWorkshop.tsx` 模板不可用语气改为「模板暂不可用」；`api.ts` 删除 `tlPatchRights`；`styles.css` 删除 `.tl-rights-*` / `.tl-required` 样式。
- 【保持】默认创作模式、按模板创作（只影响图片）、文本快速分析 Tab、视频解构与诚实降级、真实视觉 / OCR 通道均未改动。
**本次优化与更改的功能 / 模块**
- 【优化】素材入库 / 分析 / 归并 / 沉淀链路去掉授权声明步骤，操作更直接，导入表单更简洁。
- 【保持】按模板创作仍只驱动图片骨架，文案链路完全不读模板；模板下拉仍显示基础不可用原因（模板自身问题），不再有授权拦截。
- 【移除】素材授权状态字段、补录接口与前端授权子模块整体下线。
**影响范围**
- 兼容：旧库中的 `rights_status` / `rights_note` 列保留但不再读写，历史素材与新素材一视同仁；图片 / 视频解构记录、模板骨架与归并标记数据结构不变，历史模板与解构结果完全兼容。
- 边界：本版为流程收敛，不改变任何模型调用规则——视觉模型或 OCR 不可用仍落 `unavailable`、不臆造、不 Mock；真实付费出片与效果验收仍为外部验收项。
- 部署：纯代码升级，无新镜像依赖；真实环境需 `git pull && docker compose up -d --build` 更新代码。
**验证**
- 专项：模板库全系列 63/63 通过（v4117/v4118/v4119/v4120/v4121）；其中 v4120 重写为「模板只影响图片 + 授权声明已移除」验证（闸门符号不存在、导入无授权字段仍成功、解构/归并/模板编辑无 rights_gate、补录接口 404、前端无授权 UI）。
- 全量回归：531 passed / 3 skipped / 14 subtests passed；前端 `tsc --noEmit` 与 `vite build` 通过；`prepare_release --check` 通过。
- 浏览器冒烟（本地 5180）：「素材创意模板库」导入页不再出现投放授权声明字段、状态徽标或补录入口；「素材工作坊」按模板创作 Tab 正常切换，提示文案仅为模板骨架说明。本地页面数据加载仍显示 `Failed to fetch`，系开发服务器跨域登录态环境问题，非本版代码回归（接口与专项测试均正常）。
- 发版数据由 `prepare_release --sync` 重建，独立进程执行 `--check`（同进程模块缓存会导致误报旧版本）。

## V4.121 素材创意模板库 V4：视频解构（抽帧 + 分镜/钩子/字幕/节奏，复用分类与归并键）

**发布日期**：2026-11-20 15:05
**变更类型**：新增 / 优化
**涉及模块**：素材创意模板库（视频解构 + 归并视图）、后端视频解构引擎（新模块）、后端归并引擎、后端解构 / 上传接口、前端解构页、前端 API、回归测试、发版数据、发版流程、系统版本
**变更摘要**：补齐素材创意模板库的视频解构能力，图片与视频从此走同一套「导入 → 解构 → 分类 → 归并 → 沉淀」链路。视频上传后不再只是归档 + 封面帧：解构时复用 `video_vision_audit.extract_frames()` 的首/中/尾抽帧（imageio-ffmpeg 自带 ffmpeg，无系统依赖），逐帧调用同源**真实视觉模型**聚合出分镜 / 钩子 / 字幕 / 节奏四个视频专属维度；字幕来自真实画面 OCR，不臆造、不 Mock。视频解构结果复用 12 类主分类、目的、钩子与信息结构相似度归并键，完整度仍按统一 12 项口径计算，保证图片 / 视频 golden 在同一把尺子上可比。所有诚实降级与 V4.120 授权闸门保持原语义：抽帧失败 / 各帧不可用 / 无视觉配置落 `unavailable`，未授权视频在调用任何视觉通道前 422 拦截。
**更新要点**
- 【新增】`backend/asset_video_deconstruct.py`：视频解构引擎（`asset-video-deconstruct/1.0`）。逐帧复用 `asset_deconstruct.deconstruct_image()` 的真实视觉通道，主干取完整度最高帧、其余帧补充卖点与分类；新增 `dims_json.video` 六项——分镜序列 / 钩子时刻 / 字幕与画面文字 / 节奏 / 抽帧数 / 时长，统一 `{value, confidence, caveat}` 结构。
- 【新增】真实字幕维度：`video_vision_audit.recognize_frames()` 的 OCR 结果逐字去重后写入字幕项并标注「含画面文字与字幕，需人工确认」；OCR 不可用时字幕留空、置信度 0、给出明确 caveat，绝不臆造字幕内容。
- 【新增】诚实降级：无可用帧 / 各帧解构均不可用 → `status=unavailable`、`dims_json={}`、完整度 0；部分帧成功时在分镜 caveat 明确「仅 N/M 帧解构成功」；节奏基于抽样推断，caveat 标注「非逐帧精算」。
- 【优化】`backend/asset_merge.py` 框架白名单扩展为图片 / 视频两套（`SUPPORTED_FRAMEWORKS`），视频解构结果直接进入同一归并键与 golden 完整度口径；`taxonomy()` 暴露两套框架版本；模板骨架的 `source_framework` 按 golden 实际解构框架溯源，不再固定写图片版本。
- 【优化】归并候选视图新增 `media_kind` / `framework_version`，前端候选成员显示「图片 / 视频」徽标，人工确认归并时可分辨来源；授权闸门与排除原因口径不变。
- 【优化】解构路由 `POST /template-library/analyze/{id}` 由「视频 400」改为视频分支（抽帧 → OCR → 聚合），图片分支原样保留；视频上传提示由「解构留待 V4.121」改为「归档后可解构」。前端素材卡解构按钮对图片 / 视频统一开放（仍受授权闸门约束），结果区新增「视频解构（分镜/钩子/字幕/节奏）」分区与六个维度中文标签。
**本次优化与更改的功能 / 模块**
- 【新增】视频解构：上传视频后可解构分镜 / 钩子 / 字幕 / 节奏，结果可人工确认分类。
- 【优化】图片与视频共用 12 类分类、归并键和 golden 完整度口径，可跨来源类型归并沉淀同一创意骨架模板。
- 【保持】默认创作模式、按模板创作（只影响图片）、授权强制闸门、原「文本快速分析」Tab 均未改动。
**影响范围**
- 新增能力：视频解构与视频维度展示、视频参与归并候选、候选来源徽标；框架溯源区分图片 / 视频。
- 兼容：图片解构链路零改动；历史图片分析框架 `asset-deconstruct/1.0` 仍为默认；`framework_version` 沿用 String(32) 字段，无新列 / 无迁移；旧模板不受影响。
- 边界：视频抽帧依赖 imageio-ffmpeg（已在 requirements.txt 与镜像中），本机无系统 ffmpeg 不影响；视觉配置缺失 / 抽帧失败一律落 `unavailable`，不冒充已解构；真实视频的视觉识别与字幕 OCR 效果为外部验收项。
- 部署：纯代码升级，无新镜像依赖；真实环境需 `git pull && docker compose up -d --build` 更新代码。

**验证**
- 专项 15/15 通过（框架与维度、诚实降级、真实视觉通道聚合、字幕 OCR、部分帧标注、归并复用、接口集成与闸门、前端静态契约）；模板库全系列专项 67/67 通过。
- 全量回归 538 项 0 失败 / 2 跳过；`npx tsc --noEmit` 0 错误；`npm run build` 成功。
- 真实浏览器冒烟：本地 5180 前端 + 8033 后端（版本 4.121.0）登录成功；素材库出现视频素材卡并标注「视频」，已授权视频解构按钮可用、未授权视频解构按钮灰显禁用；导入区文案已更新为「归档后可解构分镜/钩子/字幕/节奏」与「视频（归档后可解构）」，无残留「仅归档」表述；无可见运行时报错。接口核对视频解构记录含六个视频维度、字幕来自真实 OCR、节奏带「非逐帧精算」caveat，抽帧失败素材落 `unavailable` 且无维度。
- 发版数据由 `prepare_release --sync` 重建，独立进程执行 `--check` 通过（同进程模块缓存会导致误报旧版本）。

## V4.120 素材工作坊按模板创作 + 授权强制闸门

**发布日期**：2026-11-20 14:54
**变更类型**：新增 / 优化 / 安全加固
**涉及模块**：素材工作坊（首页双模式）、素材创意模板库（授权闸门 + 补录入口）、后端授权闸门（新模块）、后端工作坊生成链路、后端模板库接口与契约、数据模型与迁移、前端解构页、前端 API、前端样式、回归测试、发版数据、发版流程、系统版本
**变更摘要**：按确认决议落地 V4.120 三点：①「按模板创作」入口放在素材工作坊首页 Tab，默认创作模式（链接/描述 → 选媒体尺寸 → 文案 + 图片）原样保留；②模板只允许影响图片——模板骨架经 `creative_plan` 视觉路线注入现有图片提示词规则，文案生成链路完全不读模板，产品事实与数字不沿用 golden 素材；③授权标注从「仅供参考」升级为强制闸门——素材必须显式声明 `granted` 并写明授权来源与范围，才能解构、归并、沉淀模板或被工作坊引用，历史存量素材按 `unknown` 处理并可就地补录。未通过闸门的请求一律 422 + `blocked=rights_gate/template_gate` 与可执行动作，不静默降级、不调用付费模型。
**更新要点**
- 【新增】`backend/template_gate.py`：授权闸门与模板视觉适配的唯一来源。`normalize_status()` 把历史空值 / 非法值收敛为 `unknown`；`rights_check()` 只有 `granted` 且授权说明 ≥4 字才放行；`template_gate()` 逐条校验模板状态、golden 与全部归并素材的授权、骨架非空；`template_style_opts()` 只把构图 / 视线动线 / 主体位置 / 留白 / 配色 / 光线 / 质感 / 情绪转成一条视觉路线，明确禁止沿用来源素材的品牌、具体文案、价格与数字。
- 【新增】数据模型：`CreativeAssetSource` 新增 `rights_status`（granted / denied / 历史空值按 unknown），由既有 `ensure_schema()` 自动补列；`AssetSourceOut` / 两个导入请求同步输出与校验。
- 【新增】强制闸门拦截点：素材导入（无状态或说明过短 422）、图片解构、归并候选与确认沉淀、golden 改选、手工新建/编辑模板的 golden 与归并列表、工作坊按模板创作入队前——全部共用同一判定，堵住 PATCH 改 golden 的绕过路径。
- 【新增】接口：`PATCH /template-library/assets/{id}/rights`（历史/新素材补录授权的唯一入口）、`GET /workshop/templates`（模板清单附逐条 `usable` / `reason` / `required_action`，不可用模板也展示原因而不是凭空消失）；`POST /workshop/generate` 新增可选 `template_id`，只在有可用文案时把视觉路线并入出图 `style_opts`，文案调用不变，返回结果附 `template_id` / `template_name` 溯源。
- 【优化】素材工作坊首页新增「默认创作 / 按模板创作」Tab；模板模式下拉只选 `usable` 模板，展示骨架预览、版本与不可用原因；结果区标注「本批图片由模板 X 驱动（仅影响图片）」。默认模式的输入、尺寸 chips、模型状态、按钮文案与轮询链路未改动。
- 【优化】素材库导入区授权声明改为必填（默认「请选择」，不允许静默放行），素材卡显示「授权已声明 / 不可投放 / 授权未声明」徽标，未授权素材解构按钮禁用并提供就地补录表单；归并候选自动排除未授权素材并给出原因。
- 【新增】专项测试 `tests/test_template_gate_v4120.py`（11 项）：状态归一与闸门判定、模板骨架只含视觉项、导入闸门、denied 仅归档、补录后解构链路放行、候选排除、PATCH 绕过拦截、工作坊模板列表、生成接口前置 422、前端静态契约。
**本次优化与更改的功能 / 模块**
- 【新增】素材工作坊首页双模式与按模板创作，默认创作流程保持不变。
- 【新增】授权强制闸门：导入 → 解构 → 归并 → 模板 → 工作坊引用全链路同一判定，历史素材可补录。
- 【优化】模板只驱动图片，文案链路零改动；所有模板引用带溯源，出图任务快照保留模板版本信息。

**影响范围**
- 新增能力：工作坊首页 Tab、模板清单接口、授权补录接口、按模板出图（模板只影响图片）。
- 兼容：默认创作模式、创意工作台、其余模板库 CRUD 与软归并行为不变；原「文本快速分析」Tab 保留；视频解构仍按规划留 V4.121。
- 数据：旧库由 `ensure_schema()` 自动补 `rights_status` 列；历史素材默认 `unknown`，补录前不能参与解构 / 模板，原素材与解构记录不删除。V4.117/V4.119 专项测试中的素材登记同步补上授权声明以符合新闸门。
- 部署：纯代码与 schema 自愈升级；真实环境的授权声明合规性与真实付费按模板出片效果为外部验收项。

**验证**
- 专项 11/11 通过（授权闸门规则 + 接口 + 前端契约）；旧专项 41/41 通过；`npx tsc --noEmit` 0 错误；`npm run build` 成功。
- 全量回归 523 项 0 失败 / 2 跳过（首轮 V4.111 静态断言因 `style_opts` 由字面量改为变量而失败，已同步更新断言为等价正则，复跑通过）。
- 真实浏览器冒烟：本地 5180 前端 + 8033 后端登录成功；工作坊首页两个 Tab 正确渲染，切到「按模板创作」显示模板下拉、分类目的、骨架预览与版本；素材库授权必填区、素材卡「不可投放 / 授权已声明」徽标与「补录授权」按钮正常，未授权素材解构按钮禁用；无可见报错。
- 发版数据由 `prepare_release --sync` 重建，独立进程执行 `--check` 通过（同进程模块缓存会导致误报旧版本）。

## V4.119 素材创意模板库 V3：分类归并 + 按框架完整度选 golden 沉淀模板

**发布日期**：2026-11-20 14:29
**变更类型**：新增 / 优化
**涉及模块**：素材创意模板库（分类归并 + 模板沉淀工作台）、后端归并引擎（新模块）、后端接口与契约、数据模型与迁移、前端解构页、前端 API、前端样式、回归测试、发版数据、发版流程、系统版本
**变更摘要**：承接 V4.117 三层模型与 V4.118 图片解构结果，落地 Q4 冻结的分类体系与 Q5/Q6 决议。新增 `asset_merge.py` 纯函数层：按「12 类主分类相同 + 推广目的相同 + 钩子类型相同 + 信息结构相似度 ≥ 45%」形成归并候选组；只有「已解构 + 框架完整度 ≥ 50% + 分类已归一」的素材进候选，完整度低 / 不可用 / 分析失败一律排除并给出原因。golden 默认按框架完整度最高选取，并列时最近导入打破平局（仅 tie-break，不替代 Q6 主规则）；人工可覆盖 golden、可在解构详情中确认 / 修正分类（AI 原始建议保留可追溯）。人工确认归并后沉淀为一条**只含图片骨架**的模板，素材原件与解构永久保留，以 `merged_template_id` 软归并标记，可逐条撤销；模板删除只解标记不删原件。所选素材必须落在同一自动聚类，跨归并键或相似度不足一律 400，不允许硬凑。
**更新要点**
- 【新增】`backend/asset_merge.py`：归并规则唯一来源。`taxonomy()` 输出 12 类主分类 / 5 种目的 / 5 种钩子 / 45% 相似度阈值 / 50% 完整度门限；`information_similarity()` 用信息结构（标题角色 / 卖点 / CTA / 证据形式）做 Jaccard，中文按相邻 2 字切 token；`build_candidates()` 同键内并查集聚类并给出排除原因；`choose_golden()` 完整度优先、最近导入 / 置信度 / id 稳定打破平局；`build_skeleton()` + `build_variables()` 沉淀图片骨架与变量字典（不写任何具体品牌 / 数字）；`confirm_category()` 保留 `ai_suggestion` 供回溯。
- 【新增】数据模型：`CreativeAssetSource` 新增 `merged_template_id`（索引列），由既有 `ensure_schema()` 自动补列，旧库免手工迁移；`AssetSourceOut` 同步输出归并归属。
- 【新增】路由：`GET /template-library/taxonomy`（字典与阈值单一来源）、`GET /template-library/merge-candidates`（候选组 + 排除原因）、`PATCH /template-library/analyses/{id}/category`（人工确认分类，不虚增视觉解构完整度）、`POST /template-library/merge/confirm`（确认归并并沉淀模板）、`POST /template-library/templates/{id}/golden`（人工覆盖唯一表达，仅限本模板成员且不放宽候选资格）、`POST /template-library/templates/{id}/unmerge`（撤销软归并，golden 需先改选）。
- 【优化】删除保护：已归并素材禁止直接删除（提示先撤销归并），模板删除自动清除成员与 golden 的软标记并把状态回写 `analyzed`，避免悬空引用；golden 素材保持 `analyzed`，其余成员置 `merged`，数量与归属以模板为准。
- 【优化】前端 `CreativeAnalysis.tsx` 新增第三 Tab「分类归并 · 模板沉淀」：规则说明、候选组卡片（成员勾选 / golden 单选 / 完整度 / 相似度 / 建议名）、模板卡片（golden 预览 / 归并数量 / 改选 golden / 撤销归并）；素材卡显示主分类 + 目的 + 钩子与「已归并到 模板X」；解构详情内可人工确认分类。所有下拉取自后端分类字典，不写死第二套口径。
- 【新增】前端 `api.ts` 六个方法 `tlTaxonomy/tlMergeCandidates/tlMergeConfirm/tlConfirmCategory/tlSetGolden/tlUnmerge`；`styles.css` 补候选组 / golden / 模板卡片样式。
- 【新增】专项测试 `tests/test_merge_v4119.py`（13 项）：相似度阈值与聚类、完整度 / 最近导入 tie-break、不可用排除、分类确认回溯、候选组 API、软归并沉淀、跨键拒绝、golden 覆盖、撤销归并、删除解标记、前端静态契约。
**本次优化与更改的功能 / 模块**
- 【新增】素材创意模板库 V3：分类归并候选 + golden 沉淀模板，完成「导入 → 解构 → 分类归并 → 模板」链路。
- 【新增】软归并机制：原件与解构永久保留，归属可撤销，模板只承载图片骨架与变量。
- 【优化】人工始终可覆盖：分类可修正、golden 可改选，但所有覆盖都受候选资格与成员范围约束，AI 建议可追溯。
- 【优化】诚实降级：低完整度 / 不可用 / 未归一分类不进候选并给出可见原因，不允许跨键硬凑。

**影响范围**
- 新增能力：素材库第三 Tab 与六个只读 / 写接口；模板沉淀后可在工作坊按模板创作（V4.120 接入）。
- 兼容：V4.117 三表与 CRUD、V4.118 导入 / 解构链路不变；未参与归解的素材行为完全不变；原「文本快速分析」Tab 保留。
- 数据：旧库由 `ensure_schema()` 自动补 `merged_template_id` 列，无数据重写；软归并只写标记，不删除任何素材原件或解构记录。
- 部署：纯代码与 schema 自愈升级，无新增外部依赖；真实环境的真实付费视觉模型解构与人工确认归并效果为外部验收项。

**验证**
- 专项 13/13 通过（归并规则与接口全链路）；全量回归 512 项 0 失败 / 2 跳过；`npx tsc --noEmit` 0 错误；`npm run build` 成功。
- 真实浏览器冒烟：本地 5180 前端 + 8033 后端登录成功，「分类归并 · 模板沉淀」Tab 正确渲染规则说明 / 候选组 / 排除原因 / golden 标记；点击「确认归并并沉淀模板」成功落模板，模板卡显示 golden、骨架字段与归并数量，原件保留；无可见报错。
- 发版数据由 `prepare_release --sync` 重建，独立进程执行 `--check` 通过（同进程模块缓存会导致误报旧版本）。

## V4.118 素材创意模板库 V2：三态素材导入 + 图片解构引擎（真实视觉模型 + 诚实不可用）

**发布日期**：2026-11-20 14:25
**变更类型**：新增 / 优化 / 安全加固
**涉及模块**：素材创意模板库（导入 + 解构工作台）、后端解构引擎（新模块）、后端 SSRF 防护（新模块）、后端网页截图（新模块）、后端路由与契约、前端解构页、前端 API、前端样式、后端 Dockerfile、回归测试、发版数据、发版流程、系统版本
**变更摘要**：承接 V4.117 数据骨架，本版为素材创意模板库接入「导入 → 解构 → 沉淀」的前两步。导入支持三种方式：本地上传（图片/视频）、图片 URL、网页链接自动截图；视频按 Q1/Q7 只归档 + 封面帧，解构留 V4.121。图片解构新建独立引擎 `asset_deconstruct.py`，按版本化维度字典 `asset-deconstruct/1.0`（布局3+视觉3+信息4+分类2=12 项）调用**真实视觉模型**产出结构化 JSON，含布局/视觉/信息/效果/分类与模板归属建议，并按 Q6 口径计算框架完整度。解构严守诚实交付红线：无视觉配置 / 非 OpenAI 协议 / 调用失败 / 无有效维度一律落 `status=unavailable` 且 `dims_json` 为空，绝不走 Mock/Fallback、绝不臆造；效果层只做创意推断并标注「非真实投放数据」（Q3）。外网 URL 访问新增统一 SSRF 闸门 `ssrf_guard.py`（scheme 白名单、本地主机名拦截、DNS 解析后复检内网/回环/私有/CGNAT、逐跳校验重定向、流式大小限制），图片 URL 与截图接口均接入。网页截图用 headless chromium 命令行实现，服务端未装浏览器时诚实返回 unavailable；Dockerfile 预装 chromium 作为部署前置。
**更新要点**
- 【新增】`backend/asset_deconstruct.py`：图片解构引擎。`FRAMEWORK_VERSION=asset-deconstruct/1.0`，12 类主分类轴 + 推广目的/钩子/证据标签口径来自冻结的 Q4；复用 `creative_tasks._vision_model_cfg(db)` 取真实视觉配置，base64 data URL 直连 OpenAI 兼容 `/chat/completions`，与 `video_vision_audit` 同源但绝不 import MockLLM/FallbackLLM。`compute_completeness()` 按 Q6「有值且 conf≥0.6 占比 / 12」计分。effect 每维附 caveat「创意推断，非真实投放数据」。`_normalize()` 把模型输出白名单化，未归类的主分类标 `in_taxonomy=false` 供人工确认；全空结果降级为 unavailable。
- 【新增】`backend/ssrf_guard.py`：`validate_url()`（仅 http(s)、禁 userinfo、禁非 80/443 端口、禁 localhost/*.internal/云元数据主机名、IP 字面量直达判定、域名 DNS 复检全部 A/AAAA）、`fetch_remote_bytes()`（逐跳校验 302/301/307/308 重定向、流式累加限 12MB）、`is_public_ip()`（拒绝私有/回环/链路本地/保留/组播/CGNAT/未指定）。修复测试暴露的关键漏洞：`SSRFError` 继承 `ValueError`，原用 `except ValueError` 做 IP 字面量判断会吞掉自身抛出的拦截异常，导致 127.0.0.1/169.254.169.254 被放行——改为标志位控制流。
- 【新增】`backend/web_screenshot.py`：headless chromium 命令行截图，`find_chromium()` 按 CHROMIUM_PATH → Playwright 缓存 headless shell → 系统/Docker 路径探测；`screenshot()` 输出 PNG 字节并校验魔数/大小，缺浏览器或失败返回 unavailable + 原因，不假装成功。
- 【新增】路由：`POST /api/assets/screenshot`（SSRF 准入 + 截图 + 内容完整性诚实标注）、`POST /api/assets/upload-video`（视频容器校验 + ffmpeg 抽首帧封面 + 时长，无效视频拒绝）、`POST /api/template-library/import`（文件落盘后统一登记，screenshot 的完整性标注写入 rights_note）、`POST /api/template-library/analyze/{asset_id}`（图片解构落库 + 回写素材状态；视频在 V4.121 前返回 400）。`fetch-url` 改为接入统一 SSRF 闸门。
- 【优化】`schemas.py`：`AssetAnalysisCreate` 补 `model_info` 字段（归因真实视觉模型，不含密钥）；新增 `AssetImportRequest`。
- 【优化】前端 `CreativeAnalysis.tsx` 扩展为「素材库 · 导入与解构」工作台：三态导入 Tab（本地上传含视频 / 图片 URL / 网页截图）、素材卡片列表（缩略图/来源/状态/版权/删除）、解构触发与按维度分区的结果展示（布局/视觉/信息/效果/分类/模板建议/完整度/置信度/模型归因）、unavailable 诚实提示；保留原「文本快速分析」Tab 作为兜底。
- 【新增】前端 `api.ts`：`tlImport/tlAnalyze/screenshotAsset/uploadVideoAsset` 四个方法；`styles.css` 补 V4.118 工作台样式。
- 【新增】`backend/Dockerfile` 预装 chromium + 字体，作为网页截图的部署前置（镜像增大约 150MB）。
- 【新增】专项测试 `tests/test_deconstruct_v4118.py`（14 项）：解构 unavailable 四路径、黄金样例命中预期（前后对比/暖光/三理由/低风险 CTA 维度与完整度≥0.9）、effect caveat、完整度评分、未归类标记、SSRF 内网/回环/元数据/file/非标端口/DNS 复检/CGNAT 拦截、截图与 fetch-url 的 SSRF 接口级拦截、前端静态断言、Dockerfile chromium。
**本次优化与更改的功能 / 模块**
- 【新增】素材创意模板库 V2：三态导入（本地上传/图片 URL/网页截图）+ 视频归档 + 图片解构引擎 + 解构结果工作台。
- 【新增】外网 URL 安全闸门：图片 URL 与网页截图统一走 SSRF 防护，补齐 DNS 复检与重定向逐跳校验。
- 【优化】解构链路：真实视觉模型产出版本化维度 JSON，完整度可量化，不可用诚实标注不臆造、不冒充。

**影响范围**
- 新增能力：素材导入与解构全链路；网页截图（依赖服务端 chromium，真实环境需随镜像部署）；视频仅归档不解构（V4.121）。
- 安全：`fetch-url` 接入 SSRF 防护（此前仅有弱校验），内网/云元数据地址将被拒绝；截图同源防护。
- 兼容：原「文本快速分析」入口保留为独立 Tab；V4.117 三表与 CRUD 不变；创意工作台 / 素材工作坊默认创作流程不受影响。
- 部署：backend 镜像新增 chromium 依赖，真实环境需 `docker compose up -d --build` 重建镜像；若运行在 DNS 劫持到保留地址段（如 198.18.x.x）的代理环境，截图会被 SSRF 正确拦截，需直连外网或放宽为受信代理出口。

**验证**
- 专项 14/14 通过（解构引擎 + 黄金样例 + 完整度 + SSRF 单元与接口级 + 前端静态断言）；`tsc --noEmit` 0 错误；`npm run build` 成功。
- 真实浏览器冒烟：新页渲染正常（单主标题「素材创意模板库」、三态导入、素材库区、两 Tab），无 console/page 错误；隔离库端到端上传→导入→解构（无视觉模型）正确落 unavailable 且维度为空。
- 截图函数本机 headless chromium 实测输出有效 PNG；SSRF 在当前 DNS 劫持环境正确拦截保留地址。真实付费视觉模型解构效果为外部验收项。
- 发版数据由 `prepare_release --sync` 生成，独立进程 `--check` 通过。

## V4.117 素材创意模板库 V1：全球创意分析改名并入素材工作坊 + 三层数据模型与基础 CRUD

**发布日期**：2026-11-20 12:10
**变更类型**：新增 / 优化
**涉及模块**：素材创意模板库（新模块）、素材工作坊（菜单分组）、创意工作台（菜单项迁移）、后端数据模型与迁移、后端路由、前端 API、回归测试、发版数据（release_notes_data）、发版流程、系统版本
**变更摘要**：按确认方案启动「素材创意模板库」建设。本版为 V4.117–V4.121 分期的第一刀，只交付数据骨架 + 基础 CRUD + 菜单改造，不引入解构引擎 / 截图服务 / 视频处理（后续版本）。原「全球创意分析」正式改名「素材创意模板库」，从创意工作台分组迁入「素材工作坊」分组成为第二个子项——工作坊分组由 1 条升为 2 条，自动渲染为可折叠二级菜单。新增三层数据模型 `CreativeAssetSource`（素材条目，含视频长期归档）/ `CreativeAssetAnalysis`（解构分析记录）/ `CreativeTemplate`（可复用模板，只含图片骨架），由 `ensure_schema()` 自动建表；提供素材/分析/模板的增删改查接口，人工编辑模板时 version 自增并支持重置为 AI 建议。所有参数按用户 Q1–Q13 答复冻结。
**更新要点**
- 【新增】三张新表：`creative_asset_sources`（18 列，含 source_type=upload/url/screenshot/video、file/thumb、宽高时长、rights_note、file_hash 去重键、status）、`creative_asset_analyses`（13 列，含 dims_json/category_json/template_guess/completeness/confidence）、`creative_templates`（16 列，含 primary_category、image_skeleton_json、variables_json、golden_asset_id、merged_asset_ids、edit_note、version）；`models.py` 补 `Float` 导入。
- 【新增】CRUD 路由：`GET/POST /api/template-library/assets`、`DELETE /api/template-library/assets/{id}`（作为模板 golden 时拒绝删除、级联清分析记录）、`GET/POST /api/template-library/analyses`（写入后回写素材状态）、`GET/POST /api/template-library/templates`、`PATCH /api/template-library/templates/{id}`（字段更新 + version 自增 + reset_to_ai 清空 edit_note）、`DELETE /api/template-library/templates/{id}`；全部 editor 权限。
- 【优化】菜单改造：`creativeanalysis` 项从 `GROUP_WORKBENCH` 移到 `GROUP_WORKSHOP`，label 改「素材创意模板库」；`groupOpen` 增第三键 `workshop`，`openKey` 增 `GROUP_WORKSHOP → 'workshop'` 映射，避免与 workbench/system 折叠串台；内部 hash 保持 `#/creativeanalysis` 不变（用户 Q11 决定不做重定向）。
- 【优化】`CreativeAnalysis.tsx` 删除组件内重复 `page-head`（标题/说明统一由全局页头渲染，沿用 V4.116 约定），更新注释为「素材工作坊·素材创意模板库」。
- 【新增】前端 `api.ts` 加 9 个模板库方法（`tlAssets/tlAddAsset/tlDeleteAsset/tlAnalyses/tlAddAnalysis/tlTemplates/tlAddTemplate/tlUpdateTemplate/tlDeleteTemplate`）。
- 【新增】文档 `docs/素材创意模板库与工作坊改造方案_20261120.html`：参数冻结稿，含三层模型、解构六步流程、12 类主分类轴 + 9 辅助标签分类体系、框架完整度评分口径、分期规划与 Q1–Q13 决议。
- 【新增】专项测试 `tests/test_template_library_v4117.py`（14 项）：建表、素材 CRUD、分析写入与状态回写、模板版本与 reset、非法入参、删除保护、鉴权、前端菜单/改名/api/hash 静态断言。
**本次优化与更改的功能 / 模块**
- 【新增】素材创意模板库：三层数据模型（素材条目 / 分析记录 / 模板）与基础 CRUD，新建模块骨架。
- 【优化】素材工作坊分组：由单条目升为可折叠二级菜单，纳入「素材创意模板库」子项。
- 【变更】创意工作台分组：原「全球创意分析」项迁出；后端 models/schemas/routers、前端 App.tsx/CreativeAnalysis.tsx/api.ts 同步更新。

**影响范围**
- 新增入口：素材工作坊下「素材创意模板库」子菜单；原「全球创意分析」入口位置与显示名变化，hash 不变故旧链接仍可达。
- 数据与接口：新增三张业务表与一组 `/api/template-library/*` 接口；现有创意工作台 / 工作坊默认流程不受影响。

**验证**
- 专项 14/14 通过（建表 + CRUD + 边界 + 鉴权 + 前端静态断言）；全量 `run_all.py` 0 失败；`tsc --noEmit` 0 错误；`npm run build` 成功。
- 发版数据由 `prepare_release --sync` 生成，独立进程 `--check` 通过。

## V4.116 创意工作台顶部收敛为单一主标题+说明；补充创意指令二次点击确认生效并可见

**发布日期**：2026-11-20 10:42
**变更类型**：新增 / 优化 / 排查确认
**涉及模块**：创意工作台（顶部页头、图片规划补充指令区、生成提示行）、全局页头（App.tsx）、前端样式、回归测试、发版数据（release_notes_data）、发版流程、系统版本
**变更摘要**：按需求把创意工作台顶部从「两组标题 + 两组说明」收敛为「一个页面主标题 + 一个说明文字」——主标题与说明统一由 App.tsx 全局页头（page-head）呈现，组件内部不再重复渲染「创意工作台」标题与「输入产品链接…」说明；全局说明精简为一句，组件顶部只留「新建创作 / 任务」两个常驻按钮（右对齐）。同时排查用户关心的问题：第一次「确认并批量生成」后补填「补充创意指令（可选）」、再次点击时该指令是否生效。结论是**当前链路本已生效**：textarea 双向绑定 `imageSupplement`，每次点击 `batchGenerate` 都新建 `style_opts.creative_plan.supplement` 并生成全新 `idempotency_key`，后端以裸 dict 收单、落 DB 快照、worker 读快照现场重建、`build_image_prompt_rule()` 把补充指令以最高优先级渲染进 `rule_text` 并拼入 `bg_prompt` 发给文生图模型，全链路无字段丢弃、无旧 prompt 缓存。真正的缺口是界面缺少「已采纳」反馈，用户无法确认指令是否随二次点击生效。本版补上两处可见反馈（输入框下方实时提示 + 生成提示行采纳标记），并用专项测试固化整条链路。
**更新要点**
- 【优化】顶部去重：`CreativeWorkbench.tsx` 删除组件内的 `<h2 cwb-title-only>创意工作台</h2>` 与 `<p cwb-intro>输入产品链接…</p>`，只保留 `.cwb-top-actions-only`（新建创作 / 任务，右对齐）；App.tsx 全局 `workbench.desc` 精简为一句「输入落地页 / 应用链接或产品信息并选择推广媒体，AI 自动完成产品分析、创意规划与素材生成。」
- 【排查结论】补充创意指令二次点击生效：确认 `supplement: imageSupplement || ''` 读最新 state、`idempotency_key` 每次点击唯一（含 `Date.now()` + 随机数，不命中幂等）、`style_opts` 为后端通用 dict（嵌套 `creative_plan.supplement` 不被 Pydantic 丢弃）、worker 读 DB 提交快照现场重建 prompt、`rule_hash`/`config_id` 随补充指令变化（无缓存复用旧规则）。
- 【新增】可见反馈①：补充指令输入框下方，填写后显示「已填写 N 字 · 点击下方『确认并批量生成』即随本次出图生效（改后可再次点击，按最新内容重新生成）」（`.cwb-supp-live`）。
- 【新增】可见反馈②：生成提示行在补充指令非空时追加「补充创意指令（N 字）已确认采纳，将随本次点击一并生效」（`.cwb-supp-applied`），让二次点击前即可确认本次会携带最新指令。
**本次优化与更改的功能 / 模块**
- 【优化】创意工作台页头：`frontend/src/pages/CreativeWorkbench.tsx`（移除重复标题/说明、顶部按钮右对齐）
- 【优化】全局页头：`frontend/src/App.tsx`（workbench 说明精简为一句）
- 【新增】补充指令可见反馈：`frontend/src/pages/CreativeWorkbench.tsx`（`.cwb-supp-live` / `.cwb-supp-applied`）、`frontend/src/styles.css`（对应样式）
- 【新增】专项回归 `tests/test_header_supplement_v4116.py`（7 项：顶部去重、说明精简、payload 读最新 state、幂等键唯一、后端保留嵌套 supplement、规则随补充变化、可见反馈）

**影响范围**
- 顶部展示：仅合并重复的标题/说明，不改变路由、权限、新建创作与任务入口的行为；全局 page-head 现为唯一主标题 + 说明来源。
- 补充指令：不改变出图链路与计费，指令内容、优先级（仅视觉表达、不绘制文字、不编造事实）与证据门均保持原状；本版只做可见性增强，二次点击本就已生效。
- 幂等 / 缓存：未改动任何幂等键规则或 hash 逻辑；每次点击仍生成新 key、新任务，历史任务不受影响。
- 真实付费出片与真实投放效果仍为外部验收项，模拟与浏览器测试不能替代。

**验证**
- 专项 `test_header_supplement_v4116` **7/7 通过**：组件内无重复标题/说明、全局说明为单句、payload 读最新 `imageSupplement` state、`idempotency_key` 含时间+随机数、`MediaImageRequest` 保留嵌套 `creative_plan.supplement`、`rule_hash` 与 `config_id` 随补充指令变化、两处可见反馈与样式存在。
- 全量回归与 `npx tsc --noEmit` / `npm run build` 见下方发布校验记录。
- 真实付费文案出片与真实投放效果仍为外部验收项。

## V4.115 任务栏显示创建时间 + 进行中任务可手动停止；修复「确认并批量生成」422 报错

**发布日期**：2026-11-20 10:18
**变更类型**：缺陷修复 / 优化 / 新增
**涉及模块**：创意工作台（文案生成链路、任务抽屉）、后端接口（文案/图片/路线请求契约、创作任务取消）、前端（任务栏交互、时间显示）、回归测试、发版流程、系统版本
**变更摘要**：修复「确认并批量生成」后 `Meta：文案生成失败：请求失败 422: Input should be a valid dictionary` 的报错。根因是未确认创意 brief 时前端 `confirmedBrief()` 返回 `null`，直接作为 `brief` 传给后端，而 `MediaCopyRequest.brief: dict` 在 Pydantic v2 下对**显式 null** 报 `dict_type` 422（缺省才用默认值 `{}`）；文案失败又连带图片任务显示「未提交」。同类隐患还包括 `analysis.creative_intent`/`evidence_ref_audit`、`style_opts`、`copy_fields`、`CWRoutesRequest.user_brief` 为 null 时的同类 422。修复后在后端对请求体 dict 字段做 `null → {}` 收敛、前端调用点用 `|| {}`，并用端到端测试确认 `brief: null` 从 422 变为 200。同时按需求优化任务抽屉：每条任务显示创建时间（`YYYY-MM-DD HH:MM`，后端 naive UTC 正确换算到本地时区），进行中任务提供行内「停止」按钮，停止后落 `MANUAL_STOP` 标记、显示「手动停止」，可在「需处理」查询。
**更新要点**
- 【修复】422 根因：`MediaCopyRequest` / `MediaImageRequest` / `CWRoutesRequest` 新增 `@model_validator(mode="before")`，把显式为 None 的 dict 字段（`brief`/`style_opts`/`copy_fields`/`user_brief`/`creative_intent`）收敛成 `{}`；`analysis_contract` 新增 `coerce_request_dicts()` 与 `DICT_FIELDS`，`normalize_analysis()` 一并处理 `creative_intent`/`evidence_ref_audit` 为 null 的情况。
- 【修复】前端三处 API 调用点（文案 `mediaCopy`、图片 `creative_plan`、`cwRoutes.user_brief`）把 `confirmedBrief()` 改为 `confirmedBrief() || {}`，不再把 null 发往后端；归一化只针对 null，真正的类型错误（如 brief 给成数组）仍会被 Pydantic 拒绝，不掩盖问题。
- 【语义】未确认 brief 归一成 `{}` 后 `confirmed` 为空，后端 `if req.brief and not req.brief.get("confirmed")` 短路，不会被误判为「已确认」，证据门与模型调用口径不变。
- 【新增】任务创建时间：`CreativeTasksDrawer` 新增 `parseUtcMs()`（无时区 ISO 补 Z 按 UTC 解析）与 `formatCreatedAt()`（本地时区 `YYYY-MM-DD HH:MM`），任务行第二行显示「创建 YYYY-MM-DD HH:MM」；`elapsedText()` 同步改用同一解析口径，修正此前把 UTC 串当本地解析导致「已等待」偏差 8 小时的问题。
- 【新增】手动停止：`creative_tasks.cancel()` 新增 `reason` 参数（默认 `user`），手动停止落 `error_code=MANUAL_STOP`、`stage=manual_stopped`，`status` 仍为 `canceled`（TERMINAL / worker 语义不变）；子任务标签显示「手动停止」，`/creative-tasks/{id}/cancel` 路由透传 `reason`，前端 `api.cancelCreativeTask` 与 `useCreativeTasks.cancel` 同步扩展。
- 【新增】任务抽屉进行中任务行内「停止」按钮（无需展开详情），带防重复点击与「停止中…」态；详情底部按钮文案改为「手动停止」；停止成功后提示可在「需处理」查询。
**本次优化与更改的功能 / 模块**
- 【修复】请求契约：`backend/schemas.py`（三个请求模型 before-validator）、`backend/analysis_contract.py`（`coerce_request_dicts` / `DICT_FIELDS`）
- 【新增】任务取消标记：`backend/creative_tasks.py`（`cancel(reason=...)`、`job_to_task` 标签）、`backend/routers.py`（取消路由透传 reason）
- 【优化】前端：`frontend/src/pages/CreativeWorkbench.tsx`（三处 `|| {}`、任务回调 reason）、`frontend/src/CreativeTasksDrawer.tsx`（时间与停止交互）、`frontend/src/api.ts` 与 `frontend/src/useCreativeTasks.ts`（reason 透传）、`frontend/src/styles.css`（`.ctd-stop`）
- 【新增】专项回归 `tests/test_task_panel_v4115.py`（11 项，含 `brief: null` 端到端 200）；同步更新 `tests/test_creative_ui_v4101.py` 的静态断言

**影响范围**
- 生成链路：仅修复请求体 null dict 的校验 422，不改变模型选配、提示词、计费与证据门口径；已确认 brief 的处理完全不变。
- 任务数据：`MANUAL_STOP` 只写入 `error_code` / `stage` / `error_message`，`status` 仍为 `canceled`，不改变状态机与列表分组（手动停止归入「需处理」）；历史 `CANCELED` 任务仍显示「已停止」，向后兼容。
- 时间显示：创建时间由 UTC 换算到浏览器本地时区显示；同一时区内口径一致。「已等待」计时纠正为此前偏差 8 小时的正确值。
- 数据模型：本版不新增数据库列、不迁移历史数据，只复用既有 `error_code` 字段承载手动停止标记。
- 真实付费模型调用与真实投放仍为外部验收项，模拟与浏览器测试不能替代。

**验证**
- 专项 `test_task_panel_v4115` 11/11：brief/analysis/请求体各 null dict 场景不再 422、已确认 brief 与真正类型错误不被误处理、前端三处 `|| {}`、任务时间与停止按钮静态断言、后端 reason 落库字段；`TestClient` 端到端构造 `brief: null` 调 `/api/media-campaign/copy` 返回 200（修复前 422）。
- 全量回归 **464 项 0 失败 / 0 错误 / 2 跳过**；`npx tsc --noEmit` 0 错误；`npm run build` 通过；`python3 -m py_compile` 四个后端文件通过。
- 无头浏览器实测（隔离库 8041 + 前端 5181）：进行中任务显示「创建 2026-11-20 10:07」（UTC 02:07 正确换算到本地）、行内「停止」按钮可见；点击停止后「需处理 1」出现、任务标签显示「手动停止」，全程无 console / page 错误。
- 真实付费文案出片与真实投放效果仍为外部验收项。

## V4.114 图片创意规划改为单选——默认选中一条、有且只展示这一条全部内容，「改一句」意见直达出图

**发布日期**：2026-11-19 18:25
**变更类型**：优化 / 新增 / 缺陷修复
**涉及模块**：创意工作台（图片创意规划子模块、路线卡展示与交互、图片生成任务数）、后端接口（路线 PATCH 白名单）、数据模型（`CWRoute` 新增 `user_note`）、提示词规则（`image_prompt_rule` 升级 v4）、前端与菜单（路线区样式）、回归测试、发版流程、系统版本
**变更摘要**：按「默认只显示一条 / 有且只显示选中的一条 / 默认选中一条」的要求，把「图片创意规划（10 条路线）」从**多选**改为**单选**，并补齐单卡完整内容与「改一句」的真实作用链路。自查发现三处缺口：① V4.112 虽已把 10 条路线收进下拉，但 `routes` 初始是 `selected: false`，**默认一条都没选中**，同时保留「全选 / 清空 / 已选 N/10 / 用于生成勾选」，本质上仍是多选；② 单卡只渲染 `angle / description / framework_label / hook / visual_hook / proof / tags`，**漏掉 `framework`、`cta_role`**，且 `proof` 被外层条件 `framework_label || hook || visual_hook` 挡住时整块不显示；③ 「改一句」是把 `description` 原文塞进输入框直接重写，一次微调会覆盖整条规划，不是「输入修改意见」，也没有「意见已作用于图片」的反馈。修复后：下拉选中的一条即唯一参与生成的路线，默认选中第一条；切换下拉自动把选中态收敛为这一条，界面有且只展示这一条的全部字段；「改一句」改为输入**修改意见**（新增 `user_note`），原描述保留不动，意见随本条路线进入出图提示词规则，作为本路线最高优先级的视觉调整指令，并在卡片上标注「已作用到本条路线生成的图片」。生成任务数相应收敛为「平台数 × 1」。
**更新要点**
- 【优化】单选模式：分析完成与「换一批路线」后默认选中第一条（`selected: i === 0`）；下拉切换时执行 `selected: j === idx`，始终只有一条参与生成，界面只渲染当前这一条。
- 【优化】移除多选控件：删除「全选」「清空」「已选 N / 10」「用于生成」勾选，工具栏只保留「换一批路线」；下拉保留「第 N / 10 条」定位与「（当前）」标记。
- 【修复】单卡完整展示全部字段：切入角度、推荐描述、转化框架（`framework_label · framework`）、收口意图（`cta_role`）、钩子、证据表达（`proof`）、视觉钩子、标签；不再按外层条件吞掉字段，空值显示「未指定」。新增 `cwb-route-detail` 两列定义列表（窄屏回落单列）与 `cwb-route-active`「当前用于生成」标记。
- 【新增】`user_note`：`CWRoute` 新增字段（默认空，历史路线向后兼容）；`PATCH /cw/routes/{plan_id}/{key}` 白名单放行，与 `description` 分开保存，互不覆盖。
- 【新增】出图提示词消费修改意见：`image_prompt_rule` 规则版本 `3 → 4`，把 `user_note` 单独成行「用户对本条路线的修改意见（本组最高优先级，仅调整视觉表达）」；新增硬约束「用户修改意见与本路线原始描述冲突时以修改意见为准，但同样仅限视觉表达，不得改写已确认的商品事实」；`user_note` 纳入 `rule_hash`，意见变化即产生新的配置指纹，可追溯。
- 【优化】「改一句」交互：点击后输入框为空（不再预填原描述），placeholder 给出可视示例；保存按钮为「保存并作用到图片」；保存后卡片显示「你的修改意见」+「已作用到本条路线生成的图片」；清空意见可保存为空并提示。
- 【修复】保存后保留本地单选状态（`selected: r.selected`），避免后端返回的 `selected: true` 把 10 条全部点亮。
- 【优化】任务数预告与生成按钮沿用实际选中数计算，单选后稳定为「平台数 × 1」，并标注当前路线名与「修改意见已并入出图提示词」。
**本次优化与更改的功能 / 模块**
- 【优化】创意工作台路线区：`frontend/src/pages/CreativeWorkbench.tsx`（单选收敛、完整字段、修改意见区、改一句交互、移除多选控件）
- 【新增】数据模型：`backend/schemas.py` 的 `CWRoute.user_note`
- 【新增】接口白名单：`backend/routers.py` 的 `patch_cw_route`（`user_note` 可保存）
- 【新增】提示词规则：`backend/image_prompt_rule.py`（`RULE_VERSION=4`、`_clean_route` 读取 `user_note`、规则行与硬约束、`rule_hash` 纳入意见）
- 【优化】前端接口与样式：`frontend/src/api.ts` 的 `patchCwRoute` payload；`frontend/src/styles.css` 的 `.cwb-route-detail / .cwb-route-field / .cwb-route-note / .cwb-route-active`
- 【新增】专项回归 `tests/test_route_single_select_v4114.py`（6 项）；同步更新 `tests/test_image_plan_rule_v496.py`（默认选中语义）与 `tests/test_route_independent_v4104.py`（规则版本 v4）

**影响范围**
- 生成任务数：由「平台数 × 勾选路线数」收敛为「平台数 × 1」。此前可一次勾选多条路线各出一组图，现在同一时间只有一条路线参与生成；换路线用下拉切换，不需要重新分析。
- 交互：路线区从「下拉 + 勾选 + 全选/清空」简化为「下拉选一条 + 看这一条」，界面高度与信息量都下降，但单卡内容更完整。
- 文案与事实：修改意见只调整构图 / 光线 / 色调 / 场景 / 镜头语言等视觉表达，不写入画面文字、不编造价格 / 评分 / 效果数据；原 `description` 保留，证据链不受影响。
- 数据：`user_note` 为新增可选字段，历史方案与历史路线默认空，无需迁移；已有 `routes_json` 可直接读取。
- 提示词（素材创作链路的出图规则）：规则版本 `3 → 4`，`rule_hash` 会因修改意见变化，历史资产的 `prompt_rule_hash` 仍可对照，不追溯改写；本版不涉及大模型配置、模型选配与计费口径的任何改动。
- 真实付费出图效果（修改意见是否被模型完全遵循）仍为外部验收项。

**验证**
- 新增 `test_route_single_select_v4114` 6/6：`CWRoute.user_note` 默认空；提示词含意见原文与「最高优先级」、原描述不被覆盖、`rule_hash` 随意见变化、零文字与不编造事实约束仍在、`RULE_VERSION=="4"`；空意见不产生多余行；前端静态断言（默认 `selected: i === 0` 两处、切换 `selected: j === idx`、无全选/清空/勾选、9 个字段全部渲染、改一句保存 `user_note` 且进入 `creative_plan`）；`PATCH /api/cw/routes/{id}/A` 真实调用保存 `user_note`、原 `description` 不变、`changed` 含 `user_note`。
- 全量回归 **453 项 0 失败 / 0 错误 / 2 跳过**；`npx tsc --noEmit` 0 错误；`npm run build` 通过；`python3 -m py_compile` 三个后端文件通过。
- 无头浏览器实测（隔离库 + 演示模式）：路线区默认 1 张卡、下拉 10 个选项、「当前用于生成」显示；切换下拉后卡片内容联动（前后对比实验 → 晨间日常切片），仍只有 1 张卡；任务数显示「1 个平台 × 1 条路线」；点「改一句」输入「把场景换成夜间办公室，主色调改冷色」并保存后，卡片出现「已作用到本条路线生成的图片」与意见原文；全程无 console / page 错误。
- 真实模型对修改意见的遵循度、真实付费出图仍为外部验收项；模拟与浏览器测试不能替代。

## V4.113 创意工作台生成修复——模型失败不再静默回退，错误原因与模型自检直接可见

**发布日期**：2026-11-19 17:29
**变更类型**：缺陷修复 / 优化 / 新增
**涉及模块**：创意工作台（文案生成链路、失败原因展示、模型自检条、图片任务状态）、素材工作坊（文案卡原因透出）、后端接口（文案模型选配与复用、失败原因映射、只读自检端点）、素材创作平台（文案结果契约）、前端与菜单（结果区提示与样式）、回归测试、发版流程、系统版本
**变更摘要**：修复创意工作台「生成文案和图片依然报错」且提示无法定位的问题。根因是**模型调用失败被静默换成 Mock 文案**：文案模型返回 401 / 超时 / 限流时，`generate_media_copy` 把异常吞掉并回退本地 Mock；Mock 的键是 `titles` / `descriptions`，与平台 schema（`primary_text` / `headline` / `description` / `cta`）对不上，字段全空后只剩一句「文案未生成成功，请检查模型配置」，用户无法判断是 Key 过期、限流、没配置还是返回格式不对；随后每个图片任务又被记成 `failed`，页面再补一句「请调整媒体或重试」，把用户引向改尺寸 / 换平台，而实际该修的是模型配置。另一个常见成因是真实环境只勾了「分析」用途、没单独勾「文案」用途，`copy` 用途找不到配置就直接回退 Mock。修复后：模型失败一律显式 `blocked` 并给出**具体原因与处理动作**；文案模型缺失时按 `USAGE_REUSE` 复用分析模型且如实标注来源；打开创意工作台即在结果区显示三类用途的模型自检；文案没出来时图片记成「未提交」而非「生成失败」，两条提示分开写。素材工作坊的文案卡读同一份原因，不另写一套话术。同时清掉 `workshop.py` 里被重复定义的旧函数块（`copy_view` / `landing_payload` / `group_targets` / `_first` 各留一份）。
**更新要点**
- 【修复】`generate_media_copy` 不再吞异常：新增 `_copy_block_state()`，覆盖「调用抛错 / 回退 Mock / 无可用配置 / 返回非 JSON / 解析成功但零个平台字段」五种失败，统一返回 `validation.status="blocked"`、`blocked.code/message/action/model`，`message` 直接写到页面。
- 【新增】`providers.LLM_ERROR_TEXT` + `llm_error_text()`：把 `auth` / `rate_limit` / `timeout` / `network` / `upstream` / `init_error` / `invalid_response` 映射成人话原因与可执行建议（如「模型鉴权失败（401 / 403）（千问大模型/qwen-plus）。到「系统设置 → 大模型配置」检查 API Key 与 Base URL，重新点测试连通性」）。
- 【新增】`get_llm_with_info(..., allow_reuse=True)` 与 `USAGE_REUSE = {"copy": ("analysis",)}`：文案用途没有独立配置时复用同一个文本模型，`model_info.resolved_from` 如实标注，不冒充独立配置；压缩重试链路同步复用。
- 【修复】`blocked` 时跳过语义压缩与证据审计：空字段的证据结论不再掩盖「模型没跑成功」这个真正原因；`validation` 用 `blocked` 而不是 `invalid`，避免被读成「文案写得不合规」。
- 【新增】只读自检端点 `GET /api/cw/model-status`：返回分析 / 文案 / 图片三类用途的生效配置、未就绪原因与「文案复用分析模型」标注。自检口径与 `providers._pick_config` 的实际调用行为对齐——工作坊硬门仍要求「测试通过」，创意工作台是既有链路，配置未测试时仍会被真实调用，因此不误报成「未就绪」。
- 【新增】创意工作台结果区模型自检条（`cwb-model-alert`）：只提示与本次勾选素材类型相关的未就绪项，并给出直达「大模型配置」的入口；文案失败后自动刷新自检。
- 【修复】逐平台失败原因进入文案工作区（`copyErrors` + `cwb-copy-blocked`），不再只在页面底部堆一句笼统提示；`generateCopy` / 批量生成 / 新一轮生成三处状态都同步该字段。
- 【修复】文案缺失导致的图片任务状态由 `failed` 改为 `blocked`，结果区单列「以下图片未提交生成」并附真实原因；步骤条把 `blocked` 计入已完成，不再一直停在 running。
- 【修复】`workshop.copy_view()` 优先读 `result.blocked.message`，素材工作坊与创意工作台展示同一份原因。
- 【清理】删除 `backend/workshop.py` 中重复定义的第二份「文案整形」块（约 80 行），`group_targets` / `_first` / `copy_view` / `landing_payload` 各保留一份，避免后续改动只命中旧定义。
**本次优化与更改的功能 / 模块**
- 【修复】文案生成：`backend/media_ad.py`（`_copy_block_state`、异常保留、`blocked` 结果契约、压缩与审计跳过）
- 【新增】模型路由：`backend/providers.py`（`USAGE_REUSE`、`allow_reuse`、`LLM_ERROR_TEXT` / `llm_error_text()`、`exception_type` 透出）
- 【新增】只读自检：`backend/routers.py` 的 `GET /api/cw/model-status`；`backend/workshop.py` 的 `workbench_model_status()` 与重复函数块清理
- 【修复】素材工作坊：`backend/workshop.py` 的 `copy_view()` 透出同一份 blocked 原因
- 【修复】创意工作台：`frontend/src/pages/CreativeWorkbench.tsx`（`copyErrors`、模型自检条、逐平台原因、图片未提交区、步骤条计数）；`frontend/src/api.ts` 的 `cwModelStatus()`；`frontend/src/styles.css` 的 `.cwb-model-alert` / `.cwb-copy-blocked`
- 【新增】专项回归 `tests/test_creative_copy_v4113.py`（9 项）；更新 `tests/test_analysis_contract_v4112.py` 的桩函数签名以适配 `allow_reuse`

**影响范围**
- 文案：模型配置正常时行为不变；失败时不再伪装成「文案不合规」，而是明确「模型没跑成功 + 具体原因 + 处理动作」。
- 配置：只勾「分析」用途的环境现在能自动出文案；`model_info.resolved_from` 会标注复用，不产生额外费用。
- 图片：文案失败时图片是「未提交」，不再误导用户去改尺寸 / 换平台；成功路径与计数口径不变。
- 界面：结果区新增一条黄色模型自检条（仅在相关用途未就绪时出现）与红色失败原因区；其余布局、下拉路线、勾选、下载等行为不变。
- **外部依赖（重要）**：若真实环境的 API Key 确实失效（401 / 403），代码无法代为修复，仍需在「系统设置 → 大模型配置」更新 Key / Base URL 并重新点「测试连通性」；本版保证的是「原因可见、可定位、可复用可用模型」，不是替用户改凭据。
- 工作坊硬门口径未变（仍要求测试通过）；仅创意工作台的自检与其实际调用口径对齐。
- 数据：本版不改动任何表结构与字段定义，历史已落库的方案 / 文案 / 任务数据无需迁移，可直接重试。
- 兼容：`blocked` 是新增的返回字段，旧前端忽略即可；`get_llm_with_info` 新增的 `allow_reuse` 为可选关键字参数，其他调用方行为不变。

**验证**
- 新增 `test_creative_copy_v4113` 9/9：401 变「鉴权失败 + 去改 Key」、无配置变「没有可用的文案模型」、非 JSON 被点名、合法模型输出不被误判 blocked、工作坊文案卡同源、仅配分析模型时复用并标注、前端静态断言、未测试配置的自检口径一致性、`/api/cw/model-status` 端点 200 且返回三类用途。
- 真实失败场景复现（本地真实模型配置 + 隔离库）：修复前 `model_info.source=mock / fallback=true` 但用户只看到「文案未生成成功」；修复后 `validation.status=blocked`，`message` 明确为「文案未生成：模型鉴权失败（401 / 403）（千问大模型/qwen-plus）。到「系统设置 → 大模型配置」检查 API Key 与 Base URL，重新点测试连通性」。
- 全量回归 447 项 0 失败 / 0 错误 / 2 跳过；`npx tsc --noEmit` 0 错误；`npm run build` 通过；`python3 -m py_compile` 四个后端文件通过。
- 真实付费文案 / 出图、真实环境 Key 有效性仍为外部验收项；模拟测试不能替代。

## V4.112 创意工作台生成修复——真实模型字段形态不再让文案与出图整体失败，10 条路线改为下拉

**发布日期**：2026-11-19 17:05
**变更类型**：缺陷修复 / 优化 / 新增
**涉及模块**：创意工作台（文案与出图的请求契约、图片创意规划交互）、素材创作平台（文案生成链路与输出形态兼容）、后端接口（分析结果类型契约、模型输出兜底）、数据模型（`LandingAnalysis` 入参归一化）、前端与菜单（失败原因展示、路线下拉与样式）、回归测试、发版流程、系统版本
**变更摘要**：修复创意工作台「文案和素材图片都生成不出来」。根因不在模型配置，而是**分析结果的类型契约被真实模型输出打破**：真实大模型经常把 `industry` 给成对象（`{"main": "Consumer Electronics"}`）、把 `advantages` / `sellingPoints` 给成一段字符串、把 `channels` 给成 `["Meta"]`，而 `_build_cw_result` 把这些值原样写进 `analysis`；文案接口与出图接口的入参是强类型 `LandingAnalysis`，因此请求在模型调用之前就被 422 拒绝。前端又把文案接口的异常 `.catch(() => null)` 吞成「未返回结果」，图片任务也因为「文案失败」被整段跳过——最终表现就是截图里的「文案未生成成功」「部分图片任务生成失败」，且拿不到任何可操作原因。修复后：分析结果在落库前统一收敛到接口声明的类型（只改类型不改语义，原文与证据链完整保留），历史已落库的旧分析在入参校验时走同一套兜底；文案失败改为显示真实原因；「图片创意规划（10 条路线）」由平铺 10 张卡片改为下拉选择，只展开当前一条。
**更新要点**
- 【修复】新增 `backend/analysis_contract.py`：把模型输出收敛成 `LandingAnalysis` 的类型契约——文本字段统一成字符串（对象取可读值、数组用「；」连接）、字符串数组字段统一成 `list[str]`（按换行/分号/竖线切分，逗号仅在短句时切分，长句不拆碎）、`channels` 统一成 `[{platform, reason}]`（去重保序）。
- 【修复】`_build_cw_result` 在写入 `analysis` 前统一收敛：`audience` 不再把字符串按字符逐个拼接（此前 `"、".join("urban commuters")` 会变成「u、r、b、a、n…」），`advantages` / `targetAudience` / `sellingPoints` 一律按数组落库，`channels` 一律为对象数组。
- 【修复】`LandingAnalysis` 增加入参归一化（`model_validator(mode="before")`）：历史方案里已落库的脏分析（industry 是对象、advantages 是字符串、channels 是平台名）不再 422，文案 / 出图 / 出片接口共用同一套兜底。
- 【修复】`workshop.landing_payload()` 改为复用统一收敛，只保留「按字段白名单裁剪」，不再就地维护第二套 channels 修补逻辑。
- 【修复】文案失败不再静默：`buildCopies()` 捕获接口异常并带上真实原因（例如「文案生成失败：证据校验未通过…」），批量生成结束后在结果区完整展示，图片任务也能看出是「因为文案失败而跳过」而非无故失败。
- 【优化】「图片创意规划（10 条路线）」改为下拉选择：下拉列出 `A · 前后对比实验` … `J · 价值锚定对照`，已选路线带「（已选）」标记；下方只展开当前这一条的切入角度、推荐描述、框架 / 钩子 / 视觉钩子、标签与「改一句」；「用于生成」勾选、已选计数、换一批 / 全选 / 清空全部保留。
**本次优化与更改的功能 / 模块**
- 【新增】分析结果类型契约 `backend/analysis_contract.py`（文本 / 数组 / channels 三组收敛规则，幂等）
- 【修复】创意分析落库：`backend/routers.py` 的 `_build_cw_result` 写入前统一收敛
- 【修复】数据模型：`backend/schemas.py` 的 `LandingAnalysis` 增加入参归一化，兼容历史脏数据
- 【修复】素材工作坊：`landing_payload()` 复用统一收敛，删除重复的 channels 修补
- 【修复】创意工作台：文案失败原因可见（`frontend/src/pages/CreativeWorkbench.tsx`）
- 【优化】创意工作台：10 条创意路线改为下拉选择 + 单卡展开，配套样式（`frontend/src/styles.css`）
- 【新增】专项回归 `tests/test_analysis_contract_v4112.py`（10 项）

**影响范围**
- 文案：真实模型输出形态不再影响接口可用性；模型配置正常时文案能正常生成，配置缺失或证据门阻断时页面给出具体原因。
- 图片：不再因为「文案失败」整段跳过而无提示；出图任务创建与分析类型解耦。
- 历史数据：已落库的旧方案（脏类型）可直接重试，无需重新分析。
- 交互：路线区高度从 10 张卡片降为「一行下拉 + 一张卡」，其余操作（勾选、换一批、全选、清空、改一句）位置与行为不变。
- 兼容：`analysis_contract` 只做类型收敛，不改写任何事实、数字与证据编号；`LandingAnalysis` 的字段定义未变。

**验证**
- 新增 test_analysis_contract_v4112 10/10：收敛规则（对象转文本、字符串转数组、长句不拆碎、channels 转对象）与幂等性、证据链不被改写；模拟真实模型输出（industry 对象 / advantages 字符串 / channels 平台名）跑通 `/cw/analyze` → `LandingAnalysis(**analysis)` 通过 → `/media-campaign/copy` 真的产出合规文案 → `/generation-jobs` 真的入队；历史脏分析同样通过；前端失败原因与路线下拉结构断言。
- 端到端复现（本地桩模型 + 隔离库）：修复前 `/media-campaign/copy` 返回 422（`industry: Input should be a valid string`），修复后 200 且标题 / 正文 / CTA 合规；`/generation-jobs` 修复前 422，修复后 202。
- 浏览器实测（无头 Chromium，独立库 + 演示模式）：路线区渲染为 1 个下拉 + 1 张卡片，下拉 10 个选项、切换后卡片内容随之变化、「用于生成」与已选计数联动，无 console / page 错误。
- 全量回归 438 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过。
- 真实付费文案与出图仍为外部验收项；本版不改变模型调用规模。

## V4.111 素材工作坊出图修复——可选尺寸必能出图、文案超长自动收敛、缩略图正常显示

**发布日期**：2026-11-19 18:20
**变更类型**：缺陷修复 / 优化
**涉及模块**：素材工作坊（尺寸选项、出图任务、结果展示）、媒体规则引擎（尺寸放行口径）、素材创作平台（图内文字收敛）、后端接口（生成接口入队前预校验、任务结果字段）、数据模型（请求体新增可选开关与结果标记）、前端与菜单（工作坊页面渲染）、回归测试、发版流程、系统版本
**变更摘要**：修复素材工作坊「选了尺寸却生成不出图片」。定位到三条独立成因并逐条修掉：①尺寸双口径——工作坊按素材标准库列出尺寸，出图执行时 `validate_task_matrix()` 却只认旧的媒体规则目录，Google 的主素材尺寸（1200x1200 / 1200x628 / 1200x1500 / 960x1200）与 TikTok 640x640 等「界面能选、任务必败」的组合被摆到界面上；任务在后台被判「不在允许清单」后直接 failed，而页面拿不到任何原因。②图内文案超预算——工作坊没有「编辑文案」这一步，文案稍长就会让整批图被判 `needs_revision`（图内文案无法完整排版），结果是一张图都没有且用户无从修改。③缩略图路径错误——结果里的 `url` 是服务端文件系统路径，前端直接塞进 `<img src>`，浏览器请求必然 404，图片区块显示为裂图。修复后：尺寸清单直接以执行期同一套规则函数判定「能选即能出图」；工作坊显式开启 `fit_overlay`，由出图链路按真实版式与 Logo 预留框把图上那一行收敛到可排版长度（完整文案仍作为投放字段保留）；缩略图与灯箱统一走 `api.fileUrl()`；任务失败时页面显示真实原因，不再静默。
**更新要点**
- 【修复】`media_platforms.validate_task_matrix()` 尺寸放行改为「旧规则目录 ∪ 本条 spec 登记尺寸」：spec_id 命中标准库且尺寸确在该 spec 的 `sizes` 内即放行。成员校验本身就是防篡改，伪造 spec_id 拿不到不属于它的尺寸；跨平台 spec_id 仍拒绝。
- 【修复】`workshop.platform_options()` 不再手写第二套尺寸判断，改为逐条调用 `validate_task_matrix()`，与出图执行阶段共用同一函数；`resolve_targets()` 同源继承，杜绝「选项与执行不一致」。
- 【修复】素材工作坊出图任务显式传 `style_opts.fit_overlay = True`：`media_ad.fit_overlay_text()` 按实际 layout 与 Logo 预留框压缩图内标题 / 副标 / CTA，`overlay_fit` 随图返回，批次备注注明「图内文字已按版式自动收敛」。未开启该开关的链路（创意工作台等）仍维持「超预算阻止出图、不输出省略号残图」的原策略。
- 【修复】工作坊缩略图与灯箱预览统一使用 `api.fileUrl(it.url || it.file)`，不再把 `/app/uploads/...` 这类文件系统路径交给浏览器；下载仍走带 token 的下载接口。
- 【新增】出图任务终态失败时把真实原因显示出来（任务级 `error` 优先，其次子任务 `outcome_note`），并在图片区块出现「图内文字已按版式收敛」一行提示（仅收敛时出现）。
- 【优化】工作坊生成接口在入队前用 `validate_task_matrix()` 预校验每组尺寸，必败组合当场以 warning 说明，不再排进付费队列。
- 【优化】打开工作坊时按最新尺寸清单剔除旧会话里已不可用的尺寸，避免升级后因 localStorage 旧选择整单 422。
**本次优化与更改的功能 / 模块**
- 【修复】媒体规则引擎：尺寸放行口径与素材标准库对齐（`backend/media_platforms.py`）
- 【修复】素材工作坊：尺寸选项 / 入队前预校验 / 图内文字收敛开关（`backend/workshop.py`、`backend/routers.py`）
- 【修复】图片链路：按真实版式自动收敛图内文字，结果带 `overlay_fit` 与批次备注（`backend/media_ad.py`）
- 【修复】工作坊页面：缩略图 / 灯箱路径归一化、失败原因可见、旧尺寸清理（`frontend/src/pages/MaterialWorkshop.tsx`）
- 【新增】专项回归 `tests/test_workshop_image_v4111.py`（9 项）

**影响范围**
- 尺寸：工作坊平台清单恢复 Google（4 个主素材尺寸），TikTok 增加 1200x628 / 640x640；Meta 四个尺寸不变。所有列出组合均能通过出图校验。
- 出图：文案较长时不再整批失败，图上文字会被收敛到可排版长度；完整文案仍在「文案素材」中可复制 / 下载，投放字段不改写。
- 其它链路：`validate_task_matrix()` 只对「带合法 spec_id 且尺寸属于该 spec」的请求放宽，未带 spec_id 的旧调用口径不变；创意工作台的超预算阻断行为不变。
- 展示：缩略图与预览不再裂图；任务失败时页面出现一行原因说明。
- 兼容：历史任务与旧请求不受影响；`fit_overlay` 为新增可选开关，默认关闭。

**验证**
- 新增 test_workshop_image_v4111 9/9：全部可选尺寸均通过执行期校验、Google 主素材尺寸回归、spec 尺寸放行且不可绕过、跨平台 spec 拒绝、`resolve_targets` 同源、超长文案收敛后通过预算、工作坊专属开关生效、前端 fileUrl 与失败原因渲染、入队前预校验早于创建任务。
- 端到端复现（隔离库 + 本地桩供应商，真实执行 `run_job`）：修复前 Google 1200x1200 任务 failed、0 图；修复后 succeeded、2 图。超长文案用例修复前 needs_revision、0 图；修复后 succeeded、2 图且带收敛标记。
- 全量回归 428 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过。
- 真实付费出图、真实 OCR 抽检与投放效果仍为外部验收项。

## V4.110 创意工作台精简输入区——删除素材图片选择 / 参考图 / 品牌

**发布日期**：2026-11-19 17:05
**变更类型**：删除 / 优化 / 新增
**涉及模块**：创意工作台（输入区与生成请求）、视频素材模块（图生视频参考图迁移）、素材创作平台（图片提示词链路）、后端接口（参考图闸门、视频请求字段）、数据模型（请求体字段清理）、大模型配置（图片模型参考编辑参数清理）、图片供应商适配、图片能力目录、前端与菜单、回归测试、发版流程、系统版本
**变更摘要**：按需求删除创意工作台输入区三块当前没有使用场景的组件：「素材图片选择」「参考图」「品牌」。删除不是只藏 UI：输入区对应的 state、上传/URL 处理、请求字段（`overlay_mode`、`style_opts.reference_image`、`style_opts.reference_role/authorized`、`brand_logo`、`logo`）一并清掉，图片生成统一固定「纯图片」（无字 / 无按钮 / 无 Logo，与删除前的默认值一致，输出行为不变）。参考图唯一还有真实用途的是视频「图生视频」（以参考图作首帧），因此把上传入口迁到视频规划区：选「图生视频」时才出现上传 / 缩略图 / 移除 / 图片 URL 输入，父级提交仍带 `reference_image`，能力不丢。后端同步删除仅服务该输入框的图片参考链路：`reference_image` 模块（风格学习与商品保真）、两个出图入口的参考图闸门、供应商 `/images/edits` 参考编辑分支与 `supports_reference_edit` 能力声明、`brand_logo` 视频字段与提示词注入。`analysis.brand`（品牌事实，由分析结论与文案继承）保留不动——删的是手工输入框，不是品牌事实。
**更新要点**
- 【删除】输入区「素材图片选择」下拉（纯图片 / 图片+文字 / 图片+文字+按钮）及 `overlayMode` 状态：图片请求固定 `overlay_mode: 'pure'`，与删除前的默认输出一致。
- 【删除】输入区「参考图」上传 / URL / 角色 / 授权确认四段控件与 `referenceImage / refRole / refAuthorized` 状态，以及 `style_opts.reference_image / reference_role / reference_authorized` 下发。
- 【删除】输入区「品牌」名称输入、Logo 上传、Logo 预览与「注入生成链路」开关，以及 `brand_logo`、`logo` 字段下发；品牌事实仍由分析结论与文案结果提供。
- 【新增】图生视频参考图上传迁入视频规划区（`VideoStudio`）：仅当表现形式选「图生视频」时出现，支持上传、缩略图、移除与图片 URL，父级 `videoRef` 透传到出片请求。
- 【删除】后端图片参考链路：删除 `backend/reference_image.py`（风格学习、角色判定、商品保真提示词块）、`_enforce_reference_gate()` 及其在两个出图入口的调用、`providers._post_image_edit()` 与四类图片供应商的 `reference` 形参、`image_capabilities` 的 `supports_reference_edit` 声明。
- 【优化】图片提示词不再拼接参考图风格块（`style_block` 参数移除），只由文案 + 行业视觉约束 + 提示词规则 + 零文字契约组成，链路更短且无空参分支。
- 【保留】视频 `reference_image`、`video_asset_gate()`（图生视频缺参考图仍诚实标草案）、`analysis.brand`、图片叠加能力（其它链路仍在使用，工作台固定 pure）均保留。
- 【优化】大模型配置侧同步收敛：图片模型的 `params.reference_edit` / `edit_endpoint` 不再被读取，配置页照常保存但不影响生成。
- 【优化】清理过期注释与前端无用 API 包装，避免「代码里还写着参考图但界面没有」的误导。
- 【验证】专项 test_remove_input_fields_v4110 11/11、test_input_layout_v499 6/6；全量回归 419 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；发版校验通过。
**本次优化与更改的功能 / 模块**
- 【删除】创意工作台输入区：素材图片选择、参考图、品牌三块组件及其状态与请求字段
- 【新增】视频规划区：图生视频参考图上传（原输入区能力的唯一真实用途）
- 【删除】素材创作平台：图片侧参考图风格学习、商品保真闸门、供应商参考编辑与能力声明
- 【删除】后端接口 / 数据模型：`brand_logo` 字段与视频提示词注入、`_enforce_reference_gate`
- 【优化】回归测试：删除参考图专项（V4.97 / V4.106）与更新输入区排版断言，新增 V4.110 删除边界测试

**影响范围**
- 界面：输入区少三行，表单更短；「素材类型」「创作要求」「演示模式 / 开始分析」不变，控件高度与两列网格未改动。
- 图片：输出与此前默认一致（纯图片，无叠加文字 / 按钮 / Logo）；手工选择叠加模式的能力下线，其它链路（素材工作坊等）的叠加能力不受影响。
- 视频：文生视频与图生视频都保留，图生视频的参考图改在视频规划区上传；未上传参考图仍按草案交付并提示补图。
- 品牌：不再手工指定品牌名与 Logo；品牌事实来自落地页分析与文案结果，图片提示词中的品牌约束不变。
- 兼容：历史任务里已存的 `style_opts.reference_image` / `brand_logo` 字段按未知键忽略，不影响读取与重试。

**验证**
- 专项 test_remove_input_fields_v4110 11/11（三块组件与 state 删净、图片请求固定 pure、视频参考图迁移与父级透传、后端模块/闸门/供应商/能力字段删除、brand 事实仍流动、图片提示词可正常构造）
- test_input_layout_v499 6/6（输入区无残留组件、视频上传控件同容器、素材类型下拉交互与 Esc / 清理）
- 全量回归 419 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过
- 真实出图 / 真实出片 / 投放效果仍为外部验收项；本版只保证链路可运行与字段一致

## V4.109 模型识别口径修正——已配置的图片 / 视频模型不再被判成「未配置」

**发布日期**：2026-11-19 16:12
**变更类型**：新增 / 缺陷修复 / 优化
**涉及模块**：大模型配置（用途解析、生效选路）、素材工作坊（模型闸门与提示文案）、创意工作台（视频模型选路）、后端接口（workshop options 返回项）、数据模型（配置用途字段兼容）、真实环境排查工具（新增只读自检脚本）、回归测试、发版流程、系统版本
**变更摘要**：上一版把「图片模型未配置」当成了真实环境的事实，实际是拿本地开发库的模型表做的判断——真实环境在容器卷里的库，模型配置与本地并不相同。核对代码后确认两处口径会放大这种误判：一、配置的「用途」新旧两列（`usages` 数组 / `usage` 单值）此前是二选一，`usages` 只要存在但为空数组（编辑时取消过勾选、或迁移写入 `[]`），就会盖掉仍有内容的 `usage` 列，一条真实存在的图片 / 视频配置在选路阶段被整体跳过，表现得就像「系统里没有这条配置」；二、未就绪原因只有一句「未配置」，把「配了但没点测试」「测试没过」「被停用」「要素不全」全压成同一句话，无法区分是配置问题还是测试问题。本版把用途解析改成两列并集去重，未就绪原因细分为五态并给出该用途的候选条数，同时新增一个只读自检脚本，在服务器上一条命令即可打印「每条配置的用途 / 启停 / 测试结果」与「各用途实际生效的配置」，真实环境无需再靠猜。
**更新要点**
- 【缺陷修复】`_usages_of` 改为 `usages` 与 `usage` 取并集并去重保序：空数组不再覆盖单值列，历史配置（只有 `usage`）与新配置（多用途勾选）同样可被选中。
- 【缺陷修复】工作坊模型闸门的未就绪原因细分为：未配置 / 已配置但已停用 / 配置不完整（缺 Key、地址、模型）/ 尚未测试通过 / 最近一次连通测试未通过。
- 【优化】模型状态新增 `candidates`（该用途被勾选的配置条数）：`0` 才是真的没配，`>0` 说明配了但不可用，排查不必再翻设置页。
- 【优化】工作坊提示文案带出具体原因：`图片模型未就绪（尚未测试通过），本次只出文案`，并保留「配置图片模型」直达入口。
- 【新增】只读自检脚本 `backend/model_diagnose.py`：打印全部模型配置与各用途实际生效项，明确给出工作坊分析 / 文案 / 图片与创意工作台视频的可用结论；只读，不写库、不调用模型、不产生费用。
- 【说明】视频模型不参与工作坊：工作坊只出文案与图片，视频出片仍在创意工作台，本版仅同步修正其选路的用途解析口径。
- 【验证】专项 test_model_gate_v4109 11/11；全量回归 430 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；发版校验通过。
**本次优化与更改的功能 / 模块**
- 【缺陷修复】大模型配置：用途解析（`usages` / `usage` 并集）、空 `usages` 导致配置被跳过
- 【缺陷修复】素材工作坊：图片模型「已配置却报未配置」、未就绪原因不可区分
- 【优化】素材工作坊：模型提示行显示具体原因，仍保持一行不堆说明
- 【新增】真实环境排查：`model_diagnose.py` 只读自检（服务器一条命令核对配置与生效项）
- 【优化】创意工作台：视频模型选路复用同一份用途解析，历史配置不再被漏选

**影响范围**
- 选路逻辑放宽为「并集」：只会让此前被漏选的历史配置重新进入候选，不会把停用或要素不全的配置选进来（`is_active` 与三要素校验仍在前面）。
- 未就绪判定标准不变：仍要求该用途当前生效配置「最近一次连通测试通过」，工作坊不会拿未验证的模型跑真实费用。
- 前端只改提示文案与 tooltip，布局、控件高度、结果区与下载链路均未变；无图片模型时仍降级为只出文案。
- 自检脚本只读，不影响运行中的服务；可在容器内直接执行，无需重启。

**验证**
- 专项 test_model_gate_v4109 11/11（用途并集与去重、空 `usages` 旧配置可选中、停用 / 要素不全不入选、五态原因、图片未测试时只降级不牵连文案、前端原因展示、脚本只读）
- 全量回归 430 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过
- 本地库实跑 `python3 backend/model_diagnose.py`：能正确输出 2 条配置、分析 / 文案可用、图片 / 视频未生效
- 真实环境的模型连通与真实出片仍为外部验收项：本版只保证「配了就能被认出来」，不等于已产生真实图片

## V4.108 素材工作坊——独立一级模块，链接直达文案与图片

**发布日期**：2026-11-19 16:05
**变更类型**：新增 / 优化
**涉及模块**：素材工作坊（新增一级菜单与页面）、后端接口（workshop 三接口）、数据模型 schemas（LandingAnalysis 创作意图字段、工作坊请求体）、大模型配置（已验证模型闸门）、统一分析链路（分析核心函数抽取复用）、文案与图片生成链路、素材标准库（尺寸与 spec_id）、前端样式、回归测试、发版流程、系统版本
**变更摘要**：按产品策划文档新增独立功能模块「素材工作坊」，作为系统一级菜单，与「创意工作台」并列。它只做一件事：输入一个落地页链接或一句产品描述，选平台与尺寸，直接得到可预览、可下载的文案与图片素材——路线规划、brief 确认、版位矩阵等专业步骤全部留在创意工作台，不进这个入口。模型来源严格限定为「大模型配置」里该用途**当前生效且连通性测试通过**的配置：未配置、未测试、测试失败或配置不完整一律在调用前阻断，文本模型回退 Mock、图片回退 Pillow 模板时如实标注，不把兜底内容冒充 AI 交付物。尺寸不硬编码，全部取自「素材标准库」并带 spec_id，与标准库页面、生成链路同源。界面按产品要求重做：单列上下布局、同类控件统一高度（输入 58 / chip 30 / 主按钮 38）、说明性文字默认不出现，结果按「图片素材 / 文案素材」分类，图片按平台分组，每张标比例与像素尺寸并配预览、下载。图片模型缺失时降级为「只出文案」，不阻断、不假装出图。本版同时修复 V4.105 的一个真实缺陷：创作意图写在 analysis 字典里，但出图任务用强类型模型序列化时会把它裁掉，导致图片提示词拿不到受众与禁止项。
**更新要点**
- 【新增】一级菜单「素材工作坊」：单条目分组直接渲染成一级入口，不再套「分组标题 + 唯一子项」的重复层级。
- 【新增】`POST /workshop/analyze`：链接或产品描述 → 统一分析结论（复用工作台同一份 `_cw_analyze_core`，抓取 / 证据包 / 创作意图完全一致）。
- 【新增】`POST /workshop/generate`：按平台出文案、按尺寸建出图任务；尺寸先经标准库复核，未登记的「平台 + 尺寸」在调用前拒绝。
- 【新增】`GET /workshop/options`：模型就绪状态 + 标准库尺寸选项，前端不写任何尺寸与模型名，避免与配置页 / 标准库漂移。
- 【新增】`backend/workshop.py` 纯函数模块：输入拆分、模型闸门、尺寸解析与比例标签、文案整形（回退即判失败）、图片结果整形（模板兜底标注）。
- 【优化】模型闸门以「测试通过」为唯一放行条件（`last_test_ok is True`）：未测试与测试失败同样不可用，工作坊不拿没验证过的模型跑真实费用。
- 【优化】图片模型缺失时降级为只出文案，返回 `images_skipped` 与一行原因；前端隐藏尺寸选择、按钮改为「生成文案」。
- 【优化】文案回退 Mock 的平台不出图，避免把模拟文案叠进真实图片冒充交付物；图片模板兜底在结果卡上标「模板兜底」。
- 【缺陷修复】`LandingAnalysis` 新增 `creative_intent` 正式字段，修复 V4.105 创作意图在出图任务序列化时被裁掉的问题。
- 【优化】界面：单列上下布局、控件统一高度、页头说明行在本模块隐藏、结果按素材类型与平台分类，图片带比例 + 像素尺寸与预览 / 下载。
- 【优化】会话快照按「state 初值」方式恢复，刷新后仍能看到上次的输入与结果；出图任务仍按 job_id 从服务端回填，关页不丢。
- 【验证】专项 test_workshop_v4108 12/12；全量回归 419 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；发版校验通过。
**本次优化与更改的功能 / 模块**
- 【新增】素材工作坊：一级菜单、单页工作流、按素材类型与平台分类的结果区、图片预览灯箱与下载
- 【新增】workshop 三个接口与 `workshop.py` 纯函数模块
- 【优化】大模型配置：工作坊只采用测试通过的配置，未就绪给出可执行入口（管理员直达配置页）
- 【优化】素材标准库：工作坊尺寸选项直接来自标准库并携带 spec_id，主素材类之外（logo 位、展示横幅）不进选项
- 【缺陷修复】创作意图随出图任务落库（LandingAnalysis）

**影响范围**
- 新增一级入口，不影响原有菜单顺序与权限：管理员 / 投放经理 / 投放执行可见，只读账号仍只能看「新版通知」。
- 图片模型未配置时，工作坊只出文案，并在界面上用一行说明原因；配好图片模型并通过测试后自动恢复出图，无需改代码。
- 文案与图片仍走原有生成链路（同一份文案 schema、同一套图片规则与标准库），不产生第二套生成逻辑。
- 工作坊的解析会落一条创意方案草稿（与工作台同源），便于追溯；不影响工作台已有草稿。

**验证**
- 专项 test_workshop_v4108 12/12（输入拆分、标准库尺寸与比例、未登记尺寸拒绝、模型闸门三态、文案回退判失败、意图字段落到出图任务、仅文案降级、接口与前端接线）
- 全量回归 419 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过
- 界面用真实浏览器（1440×950）核对：单列布局、控件高度一致、结果分类与尺寸标注、预览灯箱、仅文案降级提示
- 真实付费出片 / 图片模型真实连通 / 投放效果为外部验收项，模拟测试不可替代

## V4.107 图片任务服务端恢复与部分成功口径——超时不再判失败、请求/合格/待处理分开计

**发布日期**：2026-11-19 16:55
**变更类型**：新增 / 缺陷修复 / 优化
**涉及模块**：素材创作平台 / 创意工作台（生成轮询、结果区、下载）、后端接口（creative-tasks 批次详情）、数据模型（子任务视图字段）、大模型配置（轮询模型配置读取）、前端与菜单、回归测试、发版流程、系统版本
**变更摘要**：按诊断报告 9 类优化方案，第五批实施方案 F（B02 图片任务服务端恢复 + B04 部分成功口径）。此前图片结果只在浏览器 120s 轮询窗口内可见：窗口一过、页面一刷新、网络短暂中断，已产出的图片就看不到了；批次详情只回填视频，图片任务在服务端跑完也不会反映到结果区；「4 个目标出 2 张」被当成整体完成，逐尺寸失败原因藏在接口里没人看见。本版做三件事：一、建批次即订阅，图片与视频统一按 asset_id 从批次详情回填，超时 / 刷新 / 短断网后仍能展示已产出素材与逐尺寸原因；二、轮询窗口结束但任务未到终态时只标「仍在后台处理中」，不写 failed、不计入错误、不触发「请重试」；三、结果区明确「请求 N / 合格 M / 待处理 K」，成功数只按可用资产计，下载只含可用文件，逐尺寸失败原因直接列在结果区。本版不引入服务端草稿存储改造（未确认项），草稿仍按浏览器会话恢复。
**更新要点**
- 【缺陷修复】`job_to_task` 为图片子任务新增 `tally`：按逐尺寸 task_results 统计请求 / 合格 / 失败 / 待处理，并给出逐尺寸原因（最多 12 条）；成功数仍只按可用资产计。
- 【缺陷修复】前端建批次即 `setPendingBatch(batchId)`，图片批次与视频批次一样进入服务端追踪，不再只依赖 120s 轮询窗口。
- 【缺陷修复】回填逻辑新增图片分支：按 `asset_id`（缺失时退回 url）去重合并到结果区，保留尺寸与版位，刷新或断网恢复后不丢结果、不重复。
- 【缺陷修复】轮询窗口结束但状态未到终态 → 标记「仍在后台处理中」，不写 failed、不产生错误提示；有图无图都不影响后续回填。
- 【优化】结果区新增「请求 N / 合格 M / 待处理 K（待核实 J）」计数条与逐尺寸原因列表；仅有待处理任务时进入结果区等待回填，而不是报错。
- 【优化】下载路径复核：已选下载与整包下载都只取真实存在的可用资产文件，不用「成功任务数」冒充文件数。
- 【边界说明】服务端草稿存储（按 draft_id 恢复会话）为未确认项，本版不引入；草稿仍按浏览器会话恢复，丢失时任务与素材仍在服务端批次里可查。
- 【验证】专项 test_partial_success_v4107 6/6；全量回归 407 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；发版校验通过。
**本次优化与更改的功能 / 模块**
- 【缺陷修复】创意工作台 / 生成轮询：超时与刷新后仍能恢复图片结果，不误判失败
- 【缺陷修复】后端 / 批次详情：图片子任务补逐尺寸统计与原因
- 【优化】创意工作台 / 结果区：请求 / 合格 / 待处理分开计，逐尺寸原因可见
- 【优化】下载：只导出可用文件，成功数以可用资产为准

**影响范围**
- 图片任务超过轮询窗口、页面刷新或短断网后，结果区会继续显示已产出素材，并提示仍在处理中的数量；不再出现「明明在跑却提示失败」。
- 部分成功不再显示为整体完成：4 个尺寸出 2 张即显示 2/4，并列出另 2 个的具体原因。
- 不改变生成策略、不改变费用路径；未确认的服务端草稿存储改造未纳入本版。

**验证**
- 专项 test_partial_success_v4107 6/6（部分成功计数、待处理计数、视频不受影响、空结果不造计数、订阅与回填、下载只含可用文件）
- 全量回归 407 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过
- 真实付费出片 / 真实视觉质检抽检 / 品牌方确认 / 投放效果为外部验收项，模拟测试不可替代

## V4.106 参考图角色区分与商品保真——风格参考只学配色、商品参考按图编辑

**发布日期**：2026-11-19 16:20
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台 / 创意工作台（参考图控件与生成链路）、参考图模块、图片供应商适配、图片能力目录、大模型配置（参考编辑能力声明）、后端接口与闸门、数据模型（style_opts 角色与授权字段）、前端样式、回归测试、发版流程、系统版本
**变更摘要**：按用户对诊断报告 9 类优化方案的决策，第四批实施方案 D（参考图角色区分与产品保真）。此前 V4.97 把参考图统一改成「只学配色」，精确 SKU / 界面 / 结构保不住：实体商品会被重画成「差不多」的同款，软件会把虚构界面当功能。本版把参考图分成两种角色，共用一个上传入口：风格参考（默认，行为不变）只学配色与质感、生成全新画面；商品参考（保真）要求模型按参考图编辑，保留型号 / 颜色 / 材质 / 结构。保真不是「提示词写狠一点」就能做到的——文生图模型没有参考像素必然重画，因此本版在调用付费模型之前加了一道闸门：缺商品图、缺投放授权、供应商不具备参考图编辑能力，三者任一不满足即 needs_input 阻断，绝不用通用商品替代、也绝不退回本地模板画的替代品。同时为 OpenAI 兼容 /images/edits 增加真实编辑适配（multipart 上传参考图），并把「是否支持参考编辑」做成显式能力声明，未声明即按不支持处理。本版不改三步流程与双工作区布局，风格参考的既有行为完全不变。
**更新要点**
- 【新增】参考图角色 `style_reference` / `product_reference`，`normalize_role()` 对历史草稿与未知写法统一按风格参考处理（安全默认）。
- 【新增】`reference_requirement()` 保真闸门（纯函数）：商品参考需同时满足「有参考图 + 有投放授权 + 供应商支持参考编辑」，否则返回 needs_input 与可执行的 required_action。
- 【新增】`render_product_fidelity_block()` 保真提示词块：锁定型号 / 轮廓 / 比例 / 颜色 / 材质 / 结构，只允许改背景、光线与场景，禁止重绘商品、替换同类商品、虚构配件规格与画面文字。
- 【新增】`_enforce_reference_gate()`：`/media-campaign/images` 与 `/generation-jobs` 两个实际出图入口在入队与付费调用前拦截，422 返回 reference_gate 与 required_action。
- 【优化】`media_ad` 商品保真模式按参考图编辑：参考图字节交给供应商，调色板只借品牌底色不改商品本色；闸门未过时返回 needs_input，不生成任何替代图。
- 【新增】图片能力目录补 `supports_reference_edit`（四个供应商默认 False），可由 `params.reference_edit` 显式开启，绝不以「供应商名字像」推定支持。
- 【新增】OpenAI 兼容 `/images/edits` 真实编辑适配（multipart 上传参考图）；编辑失败直接返回失败，不静默退回文生图——否则「保真」会变成「凭想象重画」。
- 【优化】前端参考图控件新增角色下拉与「我确认拥有该商品素材的投放授权」勾选，提示文案按角色切换；角色与授权随 style_opts 下发并沉淀到素材库 meta。
- 【验证】专项 test_reference_role_v4106 12/12；全量回归 401 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；发版校验通过。
**本次优化与更改的功能 / 模块**
- 【新增】创意工作台 / 参考图角色：风格参考与商品保真共用上传入口，按角色切换语义与提示
- 【新增】商品保真闸门：缺商品图 / 缺授权 / 模型不支持参考编辑，一律生成前阻断
- 【新增】供应商能力声明与 /images/edits 真实编辑适配
- 【优化】图片生成链路：商品保真只改背景与场景，不重绘、不替换、不虚构
- 【优化】素材沉淀库：参考图条目记录角色与授权状态

**影响范围**
- 默认仍是风格参考，不勾选角色时行为与 V4.105 完全一致。
- 选商品参考时：未上传参考图、未确认授权、或当前图片模型未声明参考编辑能力，生成会在入队前被拦截并给出补齐指引（needs_input），不产生费用。
- 商品保真只保证「按参考图编辑」这一路径；模型是否真的具备编辑能力需部署方核验并在模型配置中显式声明，未声明一律按不支持处理。
- 真实付费出片与品牌方对商品保真的确认仍为外部验收项。

**验证**
- 专项 test_reference_role_v4106 12/12（角色归一、三类阻断、全条件放行、保真提示词块、能力目录默认值、供应商真实编辑路径、链路与前端接线）
- 全量回归 401 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过
- 真实付费出片 / 商品编辑效果抽检 / 品牌方确认 / 投放效果为外部验收项，模拟测试不可替代

## V4.105 创作意图打通分析与生成——分析前确认创作要求、路线卡可就地改一句

**发布日期**：2026-11-19 15:50
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台 / 创意工作台（输入区、图片创意规划、路线卡）、后端接口与生成链路、数据模型 schemas、创意意图模块（新增）、文案与图片提示词、视频分镜规划、前端样式、回归测试、发版流程、系统版本
**变更摘要**：按用户对诊断报告 9 类优化方案的决策，第三批实施方案 C（意图打通 analyze + 路线卡可编辑）。此前 V4.101 的 brief 已进入文案 / 路线 / 图片 / 视频规划，但「分析」阶段不接收任何用户意图，补充框里的文字只作用于图片视觉，路线卡只能勾选不能修改——用户想说的「面向谁、重点讲什么、不要什么」到不了概念层。本版新增结构化创作意图（受众 / 目标 / 核心价值 / 场景 / 风格 / 禁止项）：输入区新增「创作要求」一句话入口，按规则解析成 intent_patch（不调用模型、零成本、结果可复现），给出字段级变更摘要与冲突提示；意图随分析写入统一分析，进入路线规划、文案、图片与视频分镜提示词；禁止项为硬约束，与其它要求冲突时以禁止项优先。路线卡新增「改一句」就地编辑推荐描述（只改这一条，不重规划整批），并按「只改风格 / 场景 → 只重编译视觉；改受众 / 目标 / 核心价值 / 禁止项 → 必须重策划概念与文案」区分改动类型。本版不改三步流程、不动双工作区布局，事实与授权参考不变。
**更新要点**
- 【新增】`creative_intent` 模块（纯函数）：parse_text 规则解析、merge 变更摘要、conflicts 冲突提示、classify_change 视觉 / 概念改动判定、prompt_block 提示词块。
- 【新增】`POST /cw/intent/parse`：分析前「确认创作要求」即时预览，输入一句话即得结构化字段与冲突提示，不调用大模型、不产生费用。
- 【优化】`CWAnalyzeRequest` 新增 creative_intent / intent_text；分析结果把意图写入 analysis.creative_intent，并回传变更摘要 / 冲突 / 摘要行，供三类素材共用。
- 【优化】`/cw/routes` 请求与提示词带创作意图；系统提示词明确「每条路线必须体现受众与核心价值，禁止项一条都不能碰」。
- 【新增】`PATCH /cw/routes/{plan_id}/{key}`：路线卡「改一句」就地保存名称 / 描述 / 角度 / 标签，只改这一条；非本人方案返回 403。
- 【优化】文案提示词（_analysis_context）与图片提示词（_media_image_prompt）注入意图块，放在零文字契约之前，契约继续做最后兜底。
- 【优化】视频分镜提示词注入 creative_intent_block，禁止项对字幕 / VO / 钩子 / 画面文字同时生效。
- 【优化】前端输入区新增「创作要求」文本框与解析结果（意图摘要 / 未归类提示 / 冲突警告）；规划区显示本次创作要求；路线卡新增「改一句」内联编辑。
- 【优化】未识别的文字片段不静默丢弃：写进 notes 并提示「已按原文附加保留」，避免用户约束因未匹配规则而失效。
- 【验证】专项 test_creative_intent_v4105 12/12；全量回归 389 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；发版校验通过。
**本次优化与更改的功能 / 模块**
- 【新增】创意工作台 / 创作要求：一句话解析为结构化意图，分析前可确认、可查看冲突
- 【优化】创意工作台 / 路线卡：可就地「改一句」推荐描述，只影响这一条路线
- 【优化】后端分析接口 / 路线接口：意图随分析入库并进入策划与生成提示词
- 【优化】文案 / 图片 / 视频提示词：意图块 + 禁止项硬约束
- 【新增】creative_intent 纯函数模块与 /cw/intent/parse 接口

**影响范围**
- 输入区多一个可选文本框，不填时行为与 V4.104 完全一致；三步流程与双工作区布局未变。
- 填了创作要求后，分析产出的简报、路线与三类素材都会体现该意图；禁止项与风格 / 核心价值冲突时会显式提示并以禁止项为准。
- 路线「改一句」只改当前方案里这一条路线的展示与表达，不重新规划、不产生模型费用；已生成的历史素材不回溯修改。

**验证**
- 专项 test_creative_intent_v4105 12/12（含文档验收原句、禁止项去动词、目标不被误读为受众、未归类不丢弃、冲突、视觉 / 概念改动判定、接口与前端接线）
- 全量回归 389 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过
- 真实付费出片 / 真实视觉质检抽检 / 品牌方确认 / 投放效果为外部验收项，模拟测试不可替代

## V4.104 路线独立生成与图片四维质检——废弃多路线融合、质检开关可关

**发布日期**：2026-11-19 15:20
**变更类型**：优化 / 新增
**涉及模块**：素材创作平台 / 创意工作台（图片生成、结果卡与资产区）、系统设置、大模型配置（视觉质检模型复用）、后端接口与生成链路、数据模型 schemas、视觉复核模块、图片内容体检、提示词规则、前端样式、回归测试、发版流程、系统版本
**变更摘要**：按用户对诊断报告 9 类优化方案的决策，第二批实施方案 B（路线成为独立生成概念）与方案 E（质检从「有画面」扩展为「有效素材」）。B：此前多条创意路线只被当作同一概念的「辅助修饰」，同一文案概念被路线词缀反复叠加，路线差别最终落不到画面上；本版删除融合修饰语义，每条路线按 route_key 独立构造概念与视觉简报，concept_key / config_id 随路线变化，前端按路线逐条下单，提示词规则改为「本组独立路线」。E：此前质检只判断图片是否有画面（纯色拦截），无法回答「这张图能不能投」；本版在系统设置新增质检开关（默认打开、可关闭，持久化到 SystemState KV，无需 seed），开启时对每张合格图调用真实视觉模型做四维质检（主体 / 文案可读 / 品牌一致性 / 投放可用），结果写入 quality_status / quality_checks，视觉模型不可用时如实标 unverified 且不影响交付。本版不涉及意图打通、参考图编辑、服务端恢复、提示词管理接线与投放对照实验。
**更新要点**
- 【优化】删除「多路线融合修饰」：`image_prompt_rule.py` 规则升到 v3，去掉「辅助路线 / 多路线融合」表述，改为「本组独立路线」，同批图片不再被路线词缀污染。
- 【优化】`build_concept(..., route=None)` 把路线键绑入 concept_key 与承诺语，`build_visual_brief(..., route=None)` 写入 route_key / route_visual_hook；不传 route 时行为与旧版一致（向后兼容）。
- 【优化】`media_ad.generate_media_images` 用 route_by_key 建索引，按 slot 的 route_key 取单条路线构造概念与视觉简报，不再跨路线共享概念。
- 【优化】前端每条创意路线单独下单，slots 携带 route_key；结果卡按资产 meta 的 spec_library 展示真实规格，资产区新增「质量未核验 / 质检异常」标签。
- 【新增】`app_settings` 布尔配置（get_bool / set_bool，基于 SystemState KV），质检开关默认打开、可关闭，无需数据迁移。
- 【新增】`video_vision_audit.audit_image_quality()` 四维视觉质检：OpenAI 兼容真实视觉模型，未配置 / 调用失败 / 返回不可解析一律 unavailable，绝不走 Mock 或 Fallback 冒充通过。
- 【新增】`/settings/image-quality-audit` GET / PUT 接口与系统设置卡片开关，前端可即时关闭质检以节省视觉调用成本。
- 【优化】`image_content_guard.inspect_image_content(path, extended_check)` 保留旧 ok / verdict / metrics 字段，新增 quality_status / checks；未传扩展结论标 unverified，纯色拦截同时标 quality_status=fail。
- 【验证】专项 test_route_independent_v4104 7/7、test_quality_audit_v4104 9/9；全量回归 377 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；发版校验通过。
**本次优化与更改的功能 / 模块**
- 【优化】创意工作台 / 图片生成：每条路线完全独立生成，概念键与视觉简报随路线区分
- 【新增】系统设置 / 图片质检开关：默认打开、可关闭，持久化到 SystemState
- 【新增】视觉复核 / 四维质检：audit_image_quality 真实视觉模型，不可用标 unavailable
- 【优化】资产结果卡 / 质量标签：quality_status 与 quality_checks 透出，未核验如实标注
- 【优化】提示词规则 / image_prompt_rule v3：删除多路线融合表述，改为本组独立路线

**影响范围**
- 同一批图片的路线差别现在真正体现在概念与画面上，不再出现「同一句主标题 + 不同修饰词」的近似图；路线数量与下单方式不变，用户交互无需改变。
- 质检开关默认打开，开启时每张合格图会多一次视觉模型调用（产生额外调用成本与耗时）；可在系统设置关闭，关闭后仅保留纯色拦截。
- 视觉模型未配置或调用失败时，图片仍正常交付，仅质量状态标 unverified，不会被误判为不合格而重发已计费的调用。

**验证**
- 专项 test_route_independent_v4104 7/7、test_quality_audit_v4104 9/9
- 全量回归 377 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过
- 真实付费出片 / 真实视觉质检抽检 / 品牌方确认 / 投放效果为外部验收项，模拟测试不可替代

## V4.103 证据硬门与规格统一引用——真实抓取无证据阻断生成、spec_id 稳定下发

**发布日期**：2026-11-19 14:40
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台 / 创意工作台（文案生成、图片生成、视频出片、落地页分析）、后端接口与证据链、数据模型 schemas、媒体规格标准库、前端与菜单与结果卡、系统设置、部署依赖、回归测试、发版流程、系统版本
**变更摘要**：按用户对诊断报告 9 类优化方案的决策，第一批实施「事实层」两项——方案 A（证据链入统一分析 + 无证据硬阻断生成）与方案 H（规格标准库统一引用）。A：真实抓取的证据包此前只用于拼提示词、未写进分析，导致证据门读到空快照、evidence_status=unverified；本版把 evidence_index / snapshot_id / gate 等字段写入统一分析，并在文案 / 图片 / 视频 / 通用任务四个生成入口增加统一的证据硬门，真实抓取无可用证据时在调用付费模型 / 入队前阻断（needs_input），演示样例与手工粘贴文本不受影响。H：标准库每条规则新增稳定 spec_id，前端生成请求引用、后端按 ID 精确解析（命中即跳过展示名精确匹配），结果卡展示标准库登记的真实格式与容量，不再硬编码 JPG/PNG ≤30MB。本版不涉及路线路线独立、质检扩展、创作要求确认、参考图编辑、提示词接线与投放验证。
**更新要点**
- 【新增】`claims.generation_evidence_gate()` 统一证据硬门（纯函数）：仅当分析带真实抓取标记（evidence_snapshot_id / 显式 needs_input / snapshot=real_fetch）且无可用证据时才 needs_input；演示 / 粘贴 / 历史简化分析放行，不破坏既有分析与测试。
- 【新增】`_build_cw_result` 接受 `evidence_pack`，把证据索引、编号全集、快照 ID、门状态等 10 个字段内嵌进统一 analysis；真实抓取分支传入 pack，落库与接口一并返回。
- 【优化】四个生成入口（media-campaign/copy、media-campaign/images、generation-jobs、cw-video/generate-jobs）在调用模型 / 入队前统一过证据门；空快照不再冒充通过。
- 【新增】媒体规格标准库 `SpecEntry.spec_id`（确定性派生、稳定唯一）+ `entry_for_spec_id` / `image_target_for_spec_id`；library_payload 与 image_targets 透出 spec_id。
- 【优化】前端出图 slots 携带服务端下发的 spec_id；`validate_task_matrix` 与 `media_ad` 优先按 spec_id 解析（命中以标准库 ad_product/asset_role 为准，平台不一致拒绝），失败回退展示名匹配。
- 【优化】结果卡 `specOf` 读取资产 meta 中的真实 formats / max_bytes，标准库未登记才标注「待核验」，不再硬编码容量。
- 【验证】专项 test_evidence_gate_v4103 8/8、test_spec_id_v4103 7/7；全量回归 361 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；发版校验通过。
**本次优化与更改的功能 / 模块**
- 【新增】claims 证据硬门 / 创意工作台证据链：generation_evidence_gate 纯函数，真实抓取无证据 needs_input
- 【新增】媒体规格标准库 / spec_id：SpecEntry.spec_id 与按 ID 精确解析；前端出图与结果卡统一引用
- 【优化】后端接口 / 生成入口：文案、图片、视频、通用任务四入口接入证据门
- 【优化】前端与菜单 / CreativeWorkbench + SpecLibrary：slots 带 spec_id、结果卡读真实规格

**影响范围**
- 真实抓取落地页且无可定位原文证据的任务，生成将在调用模型前被拦截并提示 needs_input（此前会以 unverified 继续生成）；演示模式与手工粘贴文本不受影响
- 已登记规格的图片任务按稳定 spec_id 出图，结果卡规格展示更准确；未登记规格仍保留旧兼容路径

**验证**
- 专项 test_evidence_gate_v4103 8/8、test_spec_id_v4103 7/7
- 全量回归 361 项 0 失败 / 0 错误 / 2 跳过；tsc 0 错误；npm run build 通过；prepare_release --check 通过
- 真实付费出片 / OCR 抽检 / 品牌确认 / 投放效果为外部验收项，模拟测试不可替代

## V4.102 诊断报告确定性缺陷修复——批次状态、逐图错误、任务越权与提示词冲突

**发布日期**：2026-11-19 12:20
**变更类型**：新增 / 缺陷修复 / 优化
**涉及模块**：素材创作平台 / 创意工作台（图片生成、任务状态）、系统设置 / 提示词管理、后端接口与任务服务、数据模型、前端与菜单、依赖与部署、回归测试、发版流程、系统版本
**变更摘要**：依据《创意工作台素材吸引力与用户创意干预诊断及修复实施方案 V4.100》逐项自查后，先修复其中 7 项具备确定性对错的缺陷（不改变产品交互与生成策略）：图片子任务成功后批次状态滞留 queued、被拦截图片丢失 task_index 导致子任务永远 running 且失败原因互相覆盖、提示词管理自动匹配读错会话键、保存成功文案误导用户以为会影响出图、纯图提示词同时含「预留文案区」与「禁止留白」的自相矛盾指令、成片视觉复核抽帧依赖未在依赖清单声明导致容器审核降级、通用任务接口缺少归属过滤可被越权读取/取消/重试。文档其余涉及产品决策与较大重构的条目（意图打通 analyze、证据入统一分析、路线独立概念、参考图产品保真、质检扩展、服务端恢复、部分成功口径、提示词管理接线、规格统一引用、投放验证）单列为待确认优化方案，本版不动。
**更新要点**
- 【缺陷修复】B01 图片任务进入终态即重算所属批次状态（函数内延迟导入规避循环依赖），并在启动时对历史批次做幂等重算迁移；列表 status 与 active_count 不再滞留 queued。
- 【缺陷修复】B03 逐图结果统一携带 task_index / target_id / route_id / stage 与脱敏 provider_error；内容体检拦截与供应商失败分成两条原因，不再互相覆盖，子任务可被正确收敛与分项重试。
- 【缺陷修复】S01 通用任务接口（generation-jobs 列表/详情/取消/重试）按 owner_id 过滤，普通用户只能看改自己的任务；admin 保留跨账号例外。
- 【缺陷修复】C04 纯图模式不再注入旧版式 composition（copy block / negative space / 底板），改为无字满版描述；叠加图片+文字模式保留原行为。
- 【缺陷修复】B06 「自动匹配心理层」改读工作台实际会话键 admb_cw_session_v1，不再拿空对象或残留产品。
- 【缺陷修复】B05 提示词管理保存文案改为如实说明「仅沉淀/复制，不改变出图出片」，不再误导。
- 【优化】Q02 依赖清单补 imageio-ffmpeg，成片视觉复核抽帧在干净容器可用，避免审核降级为 unavailable。
- 【边界说明】resetAll 清空图片补充指令经核查 V4.101 已修复；真实付费出片、OCR 抽检、品牌确认仍为外部验收项。

**本次优化与更改的功能 / 模块**
- 【缺陷修复】`job_service.py`：`_touch_batch_status` 终态重算批次，`_set_status` / `cancel_job` 接入；`models.py` 补 CreativeBatch 引用。
- 【缺陷修复】`creative_tasks.py`：新增 `recount_all_batches` 幂等迁移入口；`main.py` 启动重算（在中断回收之后）。
- 【缺陷修复】`media_ad.py`：逐图 `common` 补可定位字段、内容拦截保留 provider_error、`task_results` 透出；`creative_config.py`：`brief_prompt_block` 增加 overlay_mode 参数。
- 【缺陷修复】`routers.py`：`_job_row` 带 owner 校验，generation-jobs 四入口接入归属过滤。
- 【缺陷修复】前端 `MaterialPromptManage.tsx`：会话键与保存文案修正。
- 【优化】`requirements.txt`：新增 imageio-ffmpeg。

**影响范围**
- 不改变三步流程、双工作区布局、创意 brief / 框架 / 换一批等 V4.101 已有能力；叠加图片+文字/按钮模式的构图行为保持不变。
- 权限收紧仅作用于通用 generation-jobs 接口；批次的 creative-tasks 接口原本已按 owner 过滤，行为不变；admin 跨账号能力保留。
- 历史批次在下次启动时按当前子任务状态重算一次（幂等），有进行中任务的批次仍判 running/queued，不误判完成。
- 提示词管理三类模板仍仅作管理/沉淀/复制用途，本次只纠正误导文案，不改变「不替换生成链路」的定位。

**验证**
- 专项 `test_diagnosis_fixes_v4102.py` 14/14 通过（B01 重算与迁移、B03 字段与原因、B06 会话键、B05 文案、C04 提示词、Q02 依赖、S01 越权均覆盖）。
- 全量回归 346 项 0 失败 / 0 错误 / 2 跳过；`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 真实模型出图出片、成片 OCR 抽检与品牌方确认仍为外部验收项，模拟测试不可替代。

## V4.101 高转化创意框架体系——文案 / 图片 / 视频提示词重构，支持用户提示词补全确认与换一批

**发布日期**：2026-11-19 12:01
**变更类型**：新增 / 优化 / 缺陷修复
**涉及模块**：素材创作平台 / 创意工作台（文案、图片、视频生成与提示词）、提示词管理、后端接口、数据模型、前端与菜单、回归测试、发版流程、系统版本
**变更摘要**：针对海外大媒体投放师与推广人员，重构文案 / 图片 / 视频三类素材的提示词与规划，解决「规划不吸引人、无宣传效果、缺少转化引导」的结构性问题。新增三类素材共用的 `CreativeBrief` 契约与 9 类高转化框架（AIDA / PAS / BAB / HSO / 4P / 对比证明 / 场景代入 / 社会认同 / 稀缺紧迫），复用「提示词管理」的六层心理链条（痛点识别 / 渴望激发 / 可信证据 / 能力归因 / 决策降本 / 行动收口）。用户可输入自己的提示方案，系统补全为结构化 brief 并展示风险提示，用户确认后才进入生成；对系统规划不满意可换一批路线 / 文案 / 分镜。事实数字仍以证据链为准，创意表达只作为策略，不编造卖点。同步修复视频出片 prompt 丢失 `hook/cta/camera/motion` 的断点，视频三道文字防线与证据门保持不变。
**更新要点**
- 【新增】共享创意框架契约：`creative_brief.py` 定义 9 类框架 + 六层心理链条，三类素材统一补全 / 预览 / 确认流程，`brief_hash` 写入结果便于追溯。
- 【新增】用户提示词补全预览：输入原始方案 → 系统补全为结构化 brief（钩子 / 利益 / 证据 / 归因 / 决策 / CTA + 视觉钩子 / 节奏）→ 展示风险提示 → 确认后生成；未确认时生成按钮禁用且后端二次拦截（400）。
- 【新增】换一批：图片路线 / 文案 / 视频分镜均支持重新生成，seed + 排除上一批，避免重复同一版；文案版本递增标注。
- 【优化】文案提示词：路线、品牌、行业画像、创意 brief 真正进入 system prompt；统一「钩子 → 具体利益 → 可信证据 → CTA 收口」表达链，CTA 仍取自平台候选值。
- 【优化】图片提示词：10 条路线框架化（含 hook / proof / visual_hook / cta_role），统一规则升级 v2 注入主干框架细项；按框架反推 D01–D20 高转化预设，参考图仍仅学习风格。
- 【优化】视频提示词：规划新增 framework / 五段节奏 / 音效建议；修复运镜、动作/转场、CTA 意图未进入出片 prompt 的断点；新增「补充出片提示词」入口。
- 【兼容性】确认后的 brief 才影响生成，不传时链路与 V4.100 完全一致；三道文字防线、零文字契约与 D0 证据门均未被绕过。
- 【新增】P0–P4 专项回归 35 项 + V4.96 旧断言同步升级（解耦规则版本号、新增 10 条框架化校验）。

**本次优化与更改的功能 / 模块**
- 【新增】`creative_brief.py`：9 类高转化框架注册表、brief 补全 / 预览、三类素材提示词块，未确认 brief 返回空块不污染提示词。
- 【新增】接口：`/api/creative-frameworks`、`/api/creative-brief/preview`、`/api/media-campaign/copy/prompt-preview`；文案 / 路线 / 视频规划请求支持 brief 与换一批参数。
- 【优化】文案链路：`prompt_catalog` 的 `[[USER_BRIEF]]` 与输出契约、`media_ad.generate_media_copy(brief=...)`、结果回传 `creative_brief`。
- 【优化】图片链路：`CWRoute` 框架字段、`image_prompt_rule` v2、`creative_config` 框架反推 D01–D20、`_CW_ROUTES_SYS` 与 10 条框架化兜底路线。
- 【优化】视频链路：`_CW_VIDEO_PLAN_SYS` 增加框架与节奏，`seg_lines` 注入运镜 / 动作，`prompt_parts` 注入框架与钩子 / 收口 / 音频建议，meta 记录框架与 brief hash。
- 【优化】前端：统一 brief 补全确认块、三处换一批入口、视频补充提示词框与最小必要样式；不改既有布局结构。

**影响范围**
- 仅影响创意工作台文案 / 图片 / 视频的规划与提示词生成方式；不传 brief 时行为与 V4.100 一致，历史计划与素材可继续查看下载。
- 事实类数字、折扣、评分、倒计时与背书仍受证据链约束，brief 只表达策略不新增事实；平台 CTA 候选值、素材规格校验与交付门不变。
- 视频零文字三道防线（源头词典 / 播放层 DOM 叠加 / 成片视觉 OCR 复核）保持启用；换一批仅改变创意表达，不绕过审查。
- 新增 4 个 Pydantic 请求字段与 3 个只读 / 预览接口，均向后兼容；旧提示词管理模板与变量来源不变。

**验证**
- 专项：P0 `test_creative_brief_v4101.py` 9/9、P1 `test_copy_brief_v4101.py` 6/6、P2 `test_image_plan_v4101.py` 7/7、P3 `test_video_plan_v4101.py` 6/6、P4 `test_creative_ui_v4101.py` 7/7；V4.96 旧规则专项 8/8（断言已解耦版本号并新增 10 条框架化校验）。
- 全量回归 332 项 0 失败 / 0 错误 / 2 跳过；`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 真实模型出图出片、成片 OCR 抽检与品牌方确认仍为外部验收项，模拟测试不可替代。

## V4.100 「素材提示管理」改名「提示词管理」——修复菜单点击被重定向

**发布日期**：2026-11-19 10:48
**变更类型**：优化 / 缺陷修复 / 新增
**涉及模块**：素材创作平台 / 提示词管理、前端与菜单、后端接口、系统版本、回归测试、发版流程
**变更摘要**：将创意工作台二级菜单「素材提示管理」统一改名为「提示词管理」（菜单标题、页面标题、接口元数据与模板说明同步）。排查确认点击无法进入的根因不在页面组件，而在前端 `allowedTabs()` 角色白名单漏列 `materialprompts`：菜单项能渲染，但点击后校验立即把页面重定向回工作台。本版补入白名单，点击与 `#/materialprompts` 直达均可正常打开。后端模块标识同步改名，但保留旧名查询兼容，已保存的三类模板按 key 读写不丢数据；页面改为从后端元数据动态读取模块名，避免再次因改名硬编码失效。
**更新要点**
- 【缺陷修复】`App.tsx` 的 `allowedTabs()` 把 `materialprompts` 加入可编辑角色白名单，点击菜单不再被重定向回工作台。
- 【优化】菜单与页面标题统一改为「提示词管理」；后端 `MODULE` 改为「提示词管理」，三类模板说明同步更新。
- 【优化】兼容旧名：新增 `LEGACY_MODULE=素材提示管理`，提示词列表接口接受旧名筛选并返回同一批模板；元数据接口返回 `module` 与 `legacy_module`。
- 【优化】页面不再写死模块字符串，改为按 `materialPromptMeta().module` 取数，杜绝后续改名造成空白页。
- 【新增】专项 `test_prompt_manage_rename_v4100.py`：菜单白名单、标题、模块常量、新旧模块名查询与页面动态取数全覆盖。

**本次优化与更改的功能 / 模块**
- 【优化】提示词管理：菜单名与页面名统一，进入路径修复。
- 【缺陷修复】前端路由白名单：`materialprompts` 可被 admin / manager / editor 正常打开。
- 【新增】旧模块名兼容查询与 V4.100 专项回归测试。

**影响范围**
- 仅提示词管理页的显示名称、进入权限校验与模块筛选标识；三类模板内容、变量来源、六层心理链条与自动匹配逻辑不变。
- 已保存的用户模板按 key 存储与更新，改名不丢内容；按旧模块名「素材提示管理」筛选仍返回同一批模板，旧缓存 / 外部调用不受影响。
- 生成链路提示词与出图出片行为零改动。

**验证**
- 专项 `test_prompt_manage_rename_v4100.py` 6/6 通过；原 `test_material_prompt_manage_v498.py` 12/12 通过。
- 全量回归 297 项 0 失败 / 0 错误 / 2 跳过；`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 真实模型出图出片仍为外部验收项，模拟测试不可替代。

## V4.99 创意工作台输入区排版修正——参考图说明归位 + 素材类型下拉点外收起

**发布日期**：2026-11-19 10:39
**变更类型**：优化 / 缺陷修复 / 新增
**涉及模块**：素材创作平台 / 创意工作台（输入表单与素材类型下拉）、前端与菜单、后端接口、系统版本、回归测试、发版流程
**变更摘要**：修复输入区「参考图」说明被折成窄条并撑高整行的排版缺陷：该说明原是两列表单网格的第三个子元素，自动掉进 84px 标签列，才出现截图中红框内的多行窄文字。现把上传/URL 控件与说明一起收进控件列，说明按整列宽度展示，行高恢复正常。同时优化「素材类型」多选下拉：选择完成后点击页面任意其他区域即收起选项，支持 Esc 收起，多选过程中保持展开以便连续勾选，并在下拉内提示收起方式。生成链路、字段与接口均未改动。
**更新要点**
- 【缺陷修复】参考图行：说明文字移入 `.cwb-ov-col` 控件列，与上传/URL 控件同列纵向排列，不再作为第三个网格子元素落入标签列。
- 【优化】素材类型下拉：容器加 ref，展开时监听 document 的 mousedown / touchstart，点击容器外即收起；Esc 同样收起，卸载/收起时清理监听。
- 【优化】下拉提示文案补充「点击空白处收起」，明确多选结束后的交互方式；多选勾选本身不自动关闭，保留连续勾选体验。
- 【新增】专项静态回归 `test_input_layout_v499.py`，固定「说明在控件列内」「网格仍为两列」「点外/Esc 收起且监听清理」。

**本次优化与更改的功能 / 模块**
- 【缺陷修复】创意工作台输入区参考图行高度：说明文字按控件列宽度展示，不再撑高表单。
- 【优化】素材类型多选下拉交互：点空白处 / Esc 收起，带状态提示。
- 【新增】V4.99 专项回归测试与发版同步。

**影响范围**
- 仅创意工作台输入表单的前端排版与下拉展开/收起行为；产品链接、投放平台、素材图片选择、品牌、演示模式与开始分析按钮位置不变。
- 文案 / 图片 / 视频生成链路、提示词、后端接口与数据模型零改动；已有选择与历史数据完全兼容。

**验证**
- 专项 `test_input_layout_v499.py` 6/6 通过；全量回归 291 项 0 失败 / 0 错误 / 2 跳过。
- `npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 真实模型出图出片仍为外部验收项，模拟测试不可替代。

## V4.98 新增二级菜单「素材提示管理」——三类通用模板 + 六层心理链条 + 真实变量

**发布日期**：2026-11-19 10:32
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台 / 创意工作台（素材提示管理二级菜单）、后端接口、数据模型、提示词注册表、前端与菜单、回归测试、发版流程、系统版本
**变更摘要**：在「创意工作台」分组新增二级菜单「素材提示管理」（位于素材标准库之后、素材历史之前），统一管理文案 / 图片 / 视频三类通用提示词。每条提示词含一句话意图、可勾选的六层心理链条、以及中文带变量模板；变量严格取自系统实际生成逻辑（文案 6 个 / 图片 10 个 / 视频 8 个），逐项标注来源，不臆造。支持按产品分析自动匹配覆盖层级，管理员编辑保存即生效。复用既有提示词注册表与接口，不改动实际出图出片链路。
**更新要点**
- 【新增】`material_prompt_manage.py`：三类通用中文模板 + 六层心理链条常量 + 每类变量来源表 + auto_match_layers 自动匹配；三条模板注册进 PROMPT_REGISTRY（module=素材提示管理）。
- 【新增】数据字段：`PromptConfig` 增加 intent（一句话意图）与 psychological_layers（六层逗号分隔）；schema 自愈自动补列；list/update/reset 接口全程透传。
- 【新增】接口：`GET /settings/material-prompts/meta`（类型 / 六层 / 变量来源）、`POST /settings/material-prompts/match-layers`（按分析自动匹配）。
- 【新增】前端 `MaterialPromptManage.tsx`：三类 Tab 切换、意图输入、六层勾选（自动匹配 / 全选）、模板编辑保存重置复制、变量来源表；管理员可编辑，其他人只读。
- 【优化】App.tsx 新增 materialprompts 菜单项与路由渲染，最小改动既有布局。

**本次优化与更改的功能 / 模块**
- 【新增】素材提示管理二级菜单：文案 / 图片 / 视频三类通用模板集中管理。
- 【新增】六层心理链条结构化字段与自动匹配：痛点识别 / 渴望激发 / 可信证据 / 能力归因 / 决策降本 / 行动收口。
- 【新增】中文带变量模板与变量来源说明：变量严格对应系统真实生成逻辑。

**影响范围**
- 仅新增管理视图与两条元数据接口；不改生成链路提示词（出图出片行为不变）；旧提示词目录 / 编辑 / 重置接口保持兼容。
- 三类模板仅作管理 / 沉淀 / 复制用途，不替换 media_copy_sys / media_image_sys / 视频出片提示词。

**验证**
- 专项 `test_material_prompt_manage_v498.py` 12/12（含变量合法性、六层匹配、注册表合入、接口分组与持久化）。
- 全量回归 285 项 0 失败 / 0 错误 / 2 跳过；`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 真实模型出图出片仍为外部验收项，模拟测试不可替代。

## V4.97 参考图改为「学习风格」——不再把用户原图直接合成进素材图片

**发布日期**：2026-11-19 09:48
**变更类型**：优化 / 新增 / 缺陷修复
**涉及模块**：素材创作平台 / 创意工作台（图片生成 · 参考图）、后端接口、数据模型、参考图风格学习（新增）、图片生成链路、前端展示、回归测试、发版流程、系统版本
**变更摘要**：纠正「参考图」用途——它应供 AI 学习配色与画面质感、生成全新推广图，而非把用户上传的原图直接集成进素材。排查确认图片生成链路所有 provider 的 generate() 均不支持 reference_image 参数，`provider_reference` 为死分支，实际 100% 走 `local_composite` 用 Pillow 把原图 paste 到主体区，与用户预期相反。本版移除该贴图链路，改用纯 Pillow 提取参考图配色/明暗/冷暖覆盖到调色板并注入「仅学习」提示词；视频侧图生视频用参考图作首帧是合理用途，保持不变。
**更新要点**
- 【新增】`reference_image.py`：用 Pillow 从参考图提取主色/配色/明暗/冷暖，输出 palette_override 与 learn-only 提示词块；fail-open、不修改入参文件、不调用视觉模型、不产生费用。
- 【缺陷修复】`media_ad.py` 彻底移除 `local_composite` 贴图与 `provider_reference` 传参分支，渲染时 product_image_path 恒为 None，参考图原图永不再进入成品。
- 【优化】参考图风格学习结论在 V4.88 零文字契约之前注入提示词，契约继续做最后兜底；palette 用学习到的配色覆盖既有键。
- 【优化】资产 meta 记 `reference_style`（mode / learned / traits / original_composited=false），用途与「未合成原图」承诺可追溯。
- 【优化】前端参考图区加「仅学习配色与画面质感、生成全新画面、原图主体/文字/Logo 不出现在素材中」说明，并更新上传按钮 title。

**本次优化与更改的功能 / 模块**
- 【新增】参考图风格学习模块：Pillow 提取配色/明暗/冷暖，生成 learn-only 提示词块与配色覆盖。
- 【缺陷修复】图片生成链路：移除本地贴图与供应商参考图传参，参考图不再被直接集成进素材。
- 【优化】提示词与调色板：风格学习结论注入 + 配色覆盖 + 资产追溯快照。
- 【优化】前端参考图说明：明确「学习用途、生成新画面」。

**影响范围**
- 仅创意工作台图片生成链路的参考图处理；视频链路 `image_to_video` 用参考图作首帧保持不变。
- 品牌 Logo 注入、文案、素材标准库、V4.96 创意规划规则均不受影响；未上传参考图时行为不变。

**验证**
- 专项 `test_reference_style_v497.py` 10/10（含真实测试图配色提取、明暗翻转、不改入参文件、贴图链路清除、前端文案）。
- 全量回归 273 项 0 失败 / 0 错误 / 2 跳过；`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 真实付费出片仍为外部验收项，模拟测试不可替代。

## V4.96 图片创意规划扩展至 10 条——所选路线 + 补充指令统一为单一出图提示词规则

**发布日期**：2026-11-18 17:05
**变更类型**：优化 / 新增 / 缺陷修复
**涉及模块**：素材创作平台 / 创意工作台（图片创意规划）、数据模型（schemas）、后端路线规划接口、统一提示词规则（新增）、创意配置快照、图片生成链路、前端与菜单、回归测试、发版流程、系统版本
**变更摘要**：把「图片创意规划（3 条路线）」扩展为最多 10 条（key A–J，count 可配 1–10），并把用户勾选的多条路线与「补充创意指令」合并为后端唯一实现的统一提示词规则；顺带修复补充指令输入框误绑视频状态、对图片出图完全失效的既有缺陷。接口默认仍为 3 条，仅创意工作台前端显式请求 10 条，其他调用零影响。
**更新要点**
- 【新增】统一提示词规则：`image_prompt_rule.py` 合并主干路线、辅助路线、补充指令与融合硬约束（不编造事实/价格/评分、不绘制画面文字、遵循平台规格），输出 rule_text + rule_hash。
- 【优化】路线接口：`/api/cw/routes` 新增 count（默认 3，钳制 1–10）；系统提示词、截断、A–J key 生成、10 条差异化兜底全部按 count 动态化。
- 【优化】配置快照：`resolve_creative_config()` 收口把 `style_opts.creative_plan` 生成 prompt_rule 并写入配置快照；规则变化即换 config_id，不改历史。
- 【优化】提示词注入：`_media_image_prompt()` 在零文字契约之前注入规则块（契约最后兜底）；资产 meta 记 prompt_rule_hash / route_keys，规则可追溯。
- 【优化】前端展示：10 条路线自适应两列 + 全选/清空 + 已选计数 + 任务数预告；每条勾选路线各出一组，当前路线置首为主干。
- 【缺陷修复】补充创意指令由 `vs.options.prompt_hint` 改为图片专用状态 `imageSupplement`，不再与视频微调串值。

**本次优化与更改的功能 / 模块**
- 【优化】创意工作台（图片创意规划）：路线由 3 条扩展至最多 10 条，默认不勾选，支持全选 / 清空。
- 【新增】统一提示词规则模块：所选路线 + 补充指令合并为唯一规则块，带 rule_hash 可追溯。
- 【优化】图片生成链路：配置快照收口、提示词注入顺序、资产 meta 增加规则快照。
- 【缺陷修复】前端补充创意指令输入框：由视频状态改为图片专用状态。

**影响范围**
- 仅创意工作台图片生成链路；视频链路 `vs.options.prompt_hint` 保持不变。
- 文案与素材标准库不受影响；历史方案（3 条）仍可复用。

**验证**
- 专项 `test_image_plan_rule_v496.py` 8/8；全量回归 263 项 0 失败 / 0 错误 / 2 跳过。
- `npx tsc --noEmit` 0 错误；`npm run build` 通过；发版校验三方一致。
- 真实付费出片与真实模型规划仍为外部验收项，模拟测试不可替代。

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
**变更类型**：优化 / 新增
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

**验证**：`run_all.py` 169 项全过；`prepare_release --check` 通过；`release_notes_data.py` 首条 V4.62 的 `date` 为 `2026-11-12 11:28（含时分）。

### 热修复（2026-11-12）：出图渲染重构 —— 透明遮罩替代实心面板 + 安全容器 + 字阶精修

**目标**：「创意工作台」生成的素材图存在四类系统性缺陷（与具体落地页无关，属渲染层设计问题）：
1. 文字区垫一层**不透明深色面板**，直接遮住背景场景，用户无法建立产品情境印象；
2. 品牌名落在「面板 / 背景」硬边交界处，位置不协调；
3. 中间文案字号过大（基准 `0.105*min(w,h)`），视觉突兀；
4. CTA 按钮同样落在面板 / 背景硬边，且文字块增长后易越出面板底。

**根因**：`backend/imaging.py` 的 `render_ad_png` 用 `fill=pal["bg1"]` 实心矩形当可读性保障，一次性制造了遮场景、硬边、错锚点、字号失控四类问题；四类同源于「实心色块保证可读性」这一个设计决策。

**修复（类型级统一方案，一次改全版式受益）**
- **A. 透明局部遮罩替代实心面板**：新增 `_draw_scrim()`，用半透明（深色 alpha=135 / 浅色卡片 alpha=175）圆角遮罩 + 边缘高斯羽化替代实心面板——背景场景透出、无生硬硬边（修复①②③④）。
- **B. 统一文字安全容器与锚点**：品牌 / 标题 / 副标 / CTA 全部落在由文字包围盒算出的安全容器内，CTA 通过 `top_max` 钳制永不越出容器底（修复②④的错位）。
- **C. 字阶精修**：标题基准由 `0.105` 降到 `0.082*min(w,h)`，并按行数 / 实际占用宽度二次收拢；行高由 `1.24` 收到 `1.12`（修复③）。`text_budget()` 同步改用 `0.082` 基准，与渲染层预算口径一致。
- **D. 统一强调元素**：短黄条 / 顶带 / 圆角半径沿用既有 `rule`/`band` 规则，仅清理冗余分支。
- `render_ad_png` 新增 `trace["render"]`（layout / 各字号 / text_container / scrim_alpha / cta_box）供线上排障。

**验证**：新增 `tests/test_imaging_render.py` 6 项断言（场景透出方差 > 100、CTA 在画布与容器内、标题字号 ≤ 0.09*min、trace 字段完整、长标题自适应收缩、banner 仍可用）；`run_all.py` **175 项全过**（169 + 6）；`prepare_release --check` 通过。

### 热修复（2026-11-12）：创意工作台选 Google 报「尺寸 160x600 与版位 display_mrec 不匹配」整批失败

**目标**：用户在「创意工作台」输入落地页、选择 Google、选一条创意路线后，生成失败并提示「媒体规则校验未通过：第 2 个任务尺寸 160x600 与版位 display_mrec(展示广告 MREC) 不匹配；该版位仅支持 300x250、336x280」。

**根因（类型级，非单页）**：前端为每个平台允许尺寸构造任务时统一填 `placement="Google"`（把平台名作为版位兜底值）；后端 `validate_task_matrix` 将 `"Google"` 视为「未真正指定版位」，回退调用 `default_placement("Google", size)`。而 `160x600` 当时在 Google 目录里**没有任何版位声明**（仅出现在 `image_sizes`，属孤儿尺寸；真实 Skyscraper 版位只登记在 Adsterra）。`default_placement` 在尺寸找不到对应版位时回退到第一个 default 版位 `display_mrec`，于是 160x600 与 display_mrec 不匹配 → 整批 `MediaRuleError` 被拒。该模式会在任意「允许尺寸含孤儿尺寸」的平台复现。

**修复（类型级统一方案）**
- **A. 补齐目录孤儿尺寸**：Google 新增版位 `display_skyscraper`（sizes=["160x600"]）并登记交付语义（ad_product / asset_role=display_banner / os=Web），使 `160x600` 成为可正确交付的 Google 尺寸。
- **B. default_placement 信号化**：尺寸在目录中无任何版位支持时返回空字典 `{}` 作为「无法解析」信号，不再回退到不匹配的默认版位（旧逻辑返回首个 default 版位，正是本 bug 的直接成因）。
- **C. validate_task_matrix 兜底改为丢弃告警**：`placement` 为平台名兜底、且 `default_placement` 返回空（孤儿尺寸）时，丢弃该任务并写入 `placement_warnings`，而非用不匹配版位导致整批失败；真正写错版位（如 "foobar"）仍按 N04 严格报错。

**验证**：新增 `tests/test_media_rules_160600.py` 4 项断言（160x600 → display_skyscraper；全平台无孤儿尺寸自检；Google 全尺寸 + placement="Google" 整批通过且 160x600 正确落版位；default_placement 对真孤儿返回空）；复现原失败调用已 `VALIDATE OK`（10 个任务全部正确分配版位）；`160x600` 在 offer/banner/hero 三种版式均可正常渲染。

### 热修复（2026-11-12）：创意工作台素材图改为「无背景板浮字 + 按钮不压字」（对齐样例素材风格）

**目标**：用户参照两张户外/生活类广告样例，要求素材图的文字不使用背景板、直接浮于照片之上以突出背景场景，且按钮不得与文字相互叠加/交叉显示。

**根因（设计层，非单页）**：上一轮（V4.63）虽用半透明圆角遮罩替代了实心面板，但遮罩本质仍是「板」，会压暗背景并自带硬边；按钮固定在文字块紧下方，视觉上仍与文字同处一个承载区，未彻底解决「文字与按钮共处一块底板」的观感。

**修复（类型级统一方案）**
- **A. 彻底移除所有背景板**：删除 `_draw_scrim` 半透明遮罩调用，文字区不再绘制任何矩形底板，背景场景完全透出（像素方差由原实心级提升至数千级）。
- **B. 无板可读性保障**：新增 `_draw_text` 的 `shadow` / `outline` 参数与 `_legibility(size)` 推导；标题/副标/品牌/按钮文字统一采用「右下暗投影 + 暗描边光晕」（白字配暗描边，亮/暗背景均通用），无需任何底板即可辨读。
- **C. 按钮自适应不压字**：新增 `_place_cta` / `_boxes_overlap`，CTA 按「右下角 → 文字正下方 → 左下角 → 右上角 → 底部居中」顺序选首个与文字块包围盒不相交的清晰区落位（对齐样例「文字左下、按钮右下」的底边两端布局）；按钮本体增加暗投影，浮于照片之上。
- 标题字阶、行高精修、trace.render 字段（scrim=False / legibility / text_container / cta_box）同步更新，供线上排障。

**验证**：新增 / 更新 `tests/test_imaging_render.py` 断言（文字区无板、场景透出方差 > 100、CTA 在画布内且与文字块不相交、标题字号 ≤ 0.09·min、trace 字段含 scrim=False 与 legibility）；`run_all.py` **180 项全过**（169 + 6 成像 + 5 媒体规则）；`prepare_release --check` 通过。

### 热修复（2026-11-12）：创意工作台界面布局优化（纯排版，不涉及功能 / 处理流程 / 输出结果）

**目标**：按用户要求精简创意工作台界面、突出重要信息。① 顶部仅标题 + 一句话介绍；② 输入模块收敛为 4 个一致表单行（产品链接 / 投放平台[下拉单选] / 参考图 / 品牌[文字或导入 Logo]），非必要子模块（演示模式、复用、历史、新建）收进「更多选项」；③ 新增「创作流程」工作流模块（解析产品 → 规划创意 → 批量生成 三步可视化，含 done / cur / pending 状态与进度条），突出当前进度与待处理内容；④ 文字性分析结果（产品摘要 / 行业·人群·动机·价格带 / 来源徽标）统一收进右侧「项目简报」面板；⑤ 素材创作输出（图片 / 视频 + 尺寸规格 + 文案）保持既有样式不变。

**改动（仅前端 UI，无功能 / 逻辑变更）**
- `frontend/src/pages/CreativeWorkbench.tsx`：
  · 顶部加一句话介绍；输入改为统一 `.cwb-form` 表单行，投放平台由多选 chips 改为下拉单选（内部仍保持 [platform] 数组，下游生成逻辑不变）；
  · 品牌支持文字输入或「导入 Logo」文件（上传 + 预览，UI 预览，不改变出图 / 文案链路）；
  · 「更多选项」折叠演示模式 / 复用（产品·参考图·品牌）/ 历史 / 新建项目；
  · 新增「创作流程」工作流卡片：三步状态机（view 驱动 done / cur / pending）+ 进度条（仅此模块展示）+ 结果汇总；
  · 产品摘要 / 4 盒 / 来源徽标从正文移入右侧「项目简报」面板，正文仅保留可交互的创意路线。
- `frontend/src/styles.css`：新增 V4.65 布局样式（表单行、下拉、品牌行、工作流步骤、右侧摘要等）与窄屏自适应。

**验证**：`tsc --noEmit` 通过；`npm run build` 成功（dist 产出，CSS 90.9 kB / JS 321 kB）；投放平台下拉单选、工作流步骤状态切换、右侧简报聚合均为纯 UI 改动，不触达 `analyze` / `generate` 等处理函数。

## V4.63 创意工作台·素材图叠加模式（纯图片 / 图片+文字 / 图片+文字+按钮）

**发布日期**：2026-11-12
**变更类型**：优化 / 新增
**涉及模块**：素材创作平台、后端接口、数据模型、前端与菜单、系统版本、新版通知
**变更摘要**：创意工作台生成素材图新增三种叠加形态，默认纯图片（不叠加文字 / logo / 按钮）；并在创意路线子模块提供「纯图片 / 图片+文字 / 图片+文字+按钮」三选项，按场景选择成图形态。

**更新要点**
- 后端 `render_ad_png` 新增 `overlay_mode` 三态：`pure` 仅保留背景与商品合成，不绘制文字 / CTA / logo；`text` 叠加文字 + logo 无按钮；`text_button` 保留旧默认行为
- 请求层全链路透传：`MediaImageRequest` / `generate_media_images` / `routers` / `job_service` 均透传 `overlay_mode`（默认 text_button，向后兼容）
- 前端创意路线子模块新增三选项控件，默认「纯图片」；`pure` 模式跳过文案生成与 invalid 硬阻断，直接以空文案出图

**本次优化与更改的功能 / 模块**
- 【优化】素材创作平台 / 版本更新：render_ad_png 按 overlay_mode 控制绘制形态
- 【优化】后端接口 / 版本更新：generate_media_images 与出图端点透传 overlay_mode
- 【优化】数据模型 / 版本更新：MediaImageRequest 新增 overlay_mode 字段
- 【优化】前端与菜单 / 版本更新：创意路线子模块新增叠加模式三选项

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：本次改动涉及 素材创作平台、后端接口、数据模型、前端与菜单；旧数据与旧接口保持兼容（缺省 text_button）。

**验证**
- python3 -m py_compile 五个后端文件通过；tests/test_imaging_render.py 6 项断言全过；脚本验证 pure 输出 text_container=[0,0,0,0]、cta_box=None，text 有文字无 CTA，text_button 文字 + CTA 均存在。

## V4.64 创意工作台·移除生成成果区初始态静态引导文案

**发布日期**：2026-11-12
**变更类型**：优化
**涉及模块**：前端与菜单、系统版本、后端接口、新版通知
**变更摘要**：创意工作台「生成成果」区在初始态展示的静态引导文案与上方工作流提示重复，现已移除；仅保留分析 / 生成流程中的对应提示，初始态不再渲染空虚线框。

**更新要点**
- 「生成成果」区 `cwb-results-empty` 改为仅当处于分析 / 生成流程中（view 为 analyzing / generating）才渲染提示框，保留「正在分析产品…」「正在生成素材…」流程提示
- 初始态不再渲染空虚线框，删除与流程提示重复的静态引导文案，避免冗余

**本次优化与更改的功能 / 模块**
- 【优化】前端与菜单 / 版本更新：生成成果区初始态静态引导文案移除，仅保留流程中提示
- 【优化】系统版本 / 版本更新：系统版本升至 V4.64

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：本次改动仅涉及前端 UI；旧数据与旧接口保持兼容。

**验证**
- grep 确认目标静态文案已从 CreativeWorkbench.tsx 移除（EXIT 1）；cwb-results-empty CSS 仍保留仅用于流程中提示。

## V4.65 创意工作台·素材图片选择前置至顶部输入框（下拉单选，默认纯图片）

**发布日期**：2026-11-13
**变更类型**：优化
**涉及模块**：前端与菜单、系统版本、新版通知
**变更摘要**：将「创意工作台」生成素材时对成图形态（纯图片 / 图片+文字 / 图片+文字+按钮）的选择，从「创意路线子模块」上移至顶部输入框子模块，改为下拉单选、默认「纯图片」；用户在开始分析落地页时即可确认生成素材要求，点击「开始分析」即按所选形态出图。

**更新要点**
- 顶部输入框子模块新增「素材图片选择」下拉单选（选项：纯图片 / 图片+文字 / 图片+文字+按钮），默认纯图片
- 移除创意路线子模块原有的三选项按钮组，避免与分析前设置重复
- 下拉选项与生成链路 overlay_mode 绑定：pure 模式跳过文字 / 按钮 / logo 绘制（沿用 V4.63 渲染能力）

**本次优化与更改的功能 / 模块**
- 【优化】前端与菜单 / 版本更新：素材图片选择前置至顶部输入框，下拉单选默认纯图片
- 【优化】系统版本 / 版本更新：系统版本升至 V4.65

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：仅前端 UI 位置与交互形态调整，overlay_mode 透传链路与后端渲染逻辑不变；旧数据与旧接口保持兼容。

**验证**
- tsc --noEmit 零错误；npm run build 成功；产物中检索「素材图片选择」命中，旧三选项描述文案（只有纯图片，没有文字，没有按钮；有纯图片和文字，没有按钮；有纯图片，文字和按钮）与旧 CSS 类（cwb-overlay-modes / cwb-ov-desc）均归零，确认旧控件已移除、新下拉已生效。

## V4.66 创意工作台·素材图渲染重做（实景满铺 + 单一纯色对比字，无蒙版/无描边）

**发布日期**：2026-11-13
**变更类型**：优化
**涉及模块**：素材创作平台、后端成像、系统版本、新版通知
**变更摘要**：针对「创意工作台」生成的素材图反馈（实景只占一部分 + 大量纯色/渐变区 + 蒙版柔化 + 文字带描边显粗制），重做渲染层——背景改为实景照片满铺整图，文字改为单一纯色浮字（按背景亮度自动选深/浅、不透明、无描边、无投影），彻底移除纯色填充边与蒙版/柔化。

**更新要点**
- `backend/imaging.py`：`_prepare_bg` 新增 `full_bleed` 路径，用 `_cover_fit` 把实景照片居中裁切填满整图；`render_ad_png` 默认 `full_bleed=True`，不再走「主体子矩形 + 纯色 fill」，也不再调用 `_apply_local_veil`（去除蒙版/柔化）
- 文字可读性改为对比色：`_text_color_for` 按文字区背景平均亮度选「暗底→浅字 / 亮底→深字」；`_draw_text` 调用统一去掉 `outline`（描边）与 `shadow`（投影），文字为单一纯色、不透明
- 纯图 / 图片+文字 模式下图片本身不再叠加任何颜色蒙版或透明度遮盖（满足「不通过蒙版遮盖实际景物」）
- 测试 `test_imaging_render.py` 同步更新：断言 `legibility={shadow:False,outline:False}`，新增 `test_full_bleed_no_solid_margins` 校验四角保留底图原色（无纯色边/蒙版）

**本次优化与更改的功能 / 模块**
- 【优化】后端成像 / 渲染：素材图背景实景满铺、文字单一纯色对比字、无蒙版无描边
- 【优化】系统版本 / 版本更新：系统版本升至 V4.66

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：仅后端成像逻辑调整，前端交互（叠加模式下拉）与接口不变；旧数据与旧接口保持兼容。

**验证**
- 合成四角异色底图渲染 pure/text/text_button 三种模式：输出四角颜色与底图原色一致（证明满铺、无纯色边）；`composition.mode == full_bleed`；`legibility == {shadow:False,outline:False}`；`pure` 模式 `text_container=[0,0,0,0]`、`cta_box=None`。
- `tests/test_imaging_render.py` 7 项全部通过（含新增满铺回归）。

## V4.67 创意工作台·视频素材创作区

**发布日期**：2026-11-13
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台、大模型配置、后端接口、数据模型、系统版本、前端与菜单
**变更摘要**：在创意工作台新增独立的「视频素材创作区」（与图片创作区上下分区、互不干扰），支持对话式分镜策划与多轮微调，并直连「大模型配置」中 video 用途的主流视频模型（Runway / 可灵 / Pika 等）生成成片，未配置时安全回退可执行分镜脚本。

**更新要点**
- 新增视频素材创作区：创意工作台下方独立分区，与图片流程互不干扰
- 对话式分镜策划：针对提示词/构想/方案多轮微调，输出 15 秒四镜分镜（钩子→功能→支撑→收口）
- 直连主流视频模型：经「大模型配置」按需选择 Runway/可灵/Pika 等，未配置回退分镜脚本
- 后端按 provider 路由：新增可灵原生异步适配器，通用 /video/generations 走 ModelVideo，视频文件 /.mp4 等可安全下载

**本次优化与更改的功能 / 模块**
- 【优化】素材创作平台 / 版本更新：相关代码与配置已同步更新。
- 【优化】大模型配置 / 版本更新：相关代码与配置已同步更新。
- 【优化】后端接口 / 版本更新：相关代码与配置已同步更新。
- 【优化】数据模型 / 版本更新：相关代码与配置已同步更新。
- 【优化】系统版本 / 版本更新：相关代码与配置已同步更新。
- 【优化】前端与菜单 / 版本更新：相关代码与配置已同步更新。

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：本次改动涉及 素材创作平台、大模型配置、后端接口、数据模型、系统版本、前端与菜单；旧数据与旧接口保持兼容。

**验证**
- 系统版本与 CHANGELOG 版本一致性由发版校验强制检查；该条目由本次改动文件自动归纳。

## V4.68 创意工作台·视频生成链路修复（通用视频模型异步取片）

**发布日期**：2026-11-13
**变更类型**：缺陷修复
**涉及模块**：后端接口、视频 Provider、大模型配置、系统版本
**变更摘要**：修复「视频素材创作区」直连已配置视频模型时无法真正生成视频的链路缺陷。原 `ModelVideo` 仅做单次同步 POST 并期望立即返回视频，而 Runway / Pika / Luma / 302.ai / 可灵聚合网关等主流视频 API 均为异步任务（返回 task_id 后需轮询取片），导致已配置模型被静默回退为分镜脚本。现 `ModelVideo` 支持「同步直出 + 异步轮询」双形态，通用递归解析各厂商响应字段，确保配置正确后稳定产出成片。

**更新要点**
- 修复视频模型异步生成：提交后按 task_id 自动轮询任务状态并下载成片（最多约 6 分钟），轮询地址与状态/URL 字段做通用匹配，覆盖 OpenAI/Sora、Runway、Pika、Luma 等形态
- 视频产物优先落盘到后端 uploads 并返回 /files 直链，外链不可达时退回外链播放，保证前端结果网格与下载按钮可用
- 大模型配置已支持 video 用途（generic-video 协议 + 可灵/Runway/Pika 等预设），视频区与图片区上下分区、互不干扰，本次仅修复视频生成链路，未改动前端布局

**本次优化与更改的功能 / 模块**
- 【修复】后端接口 / 视频生成：ModelVideo 同步+异步双形态，通用响应解析，避免静默回退
- 【优化】大模型配置 / 视频模型：generic-video 协议已可正常驱动真实视频生成（非仅分镜脚本）
- 【优化】系统版本 / 版本更新：相关代码与配置已同步更新

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：仅后端视频 Provider 逻辑变更，前端与数据模型保持兼容；旧分镜脚本回退路径不变。

**验证**
- 解析单测覆盖 OpenAI/Pika/Luma/Runway 响应形态、task_id 多键名、状态多键名、字符串内嵌 URL；模拟异步轮询（queued→succeeded）成功产出本地视频文件；routers 模块导入通过；前端 build 通过。
- 系统版本与 CHANGELOG 版本一致性由发版校验强制检查；该条目由本次改动文件自动归纳。

## V4.69 大模型配置·视频模型用途可达 + 可灵原生协议入口

**发布日期**：2026-11-13
**变更类型**：功能完善 / 缺陷修复
**涉及模块**：大模型配置、前端弹窗、视频 Provider、系统版本
**变更摘要**：修复「大模型配置 → 添加大模型」弹窗中用户无法选择「视频模型」用途、因而无法配置视频生成模型的问题。原「用途」勾选区按所选协议模态过滤（文本模态只显示分析/文案），导致用户停留在默认文本模态时根本看不到视频选项。现「用途」勾选区始终展示全部四种用途（落地页分析 / 文案 / 推广图片 / 视频模型），用户可在任意协议下明确勾选「视频模型」。同时新增「文生视频 · 可灵 Kling（原生异步）」协议选项（provider=keling），让此前在 UI 中不可达的原生可灵异步路径（JWT 鉴权 + 任务轮询）可被直接选用。

**更新要点**
- 「用途」勾选区改为始终展示全部四种用途（含「视频模型」），不再因协议模态被锁死，彻底解决无法新增视频生成模型的问题
- 新增可灵 Kling 协议选项：默认 base_url=https://api.klingai.com，支持 Access Key / Secret Key（自动签发 HS256 JWT），仅填 API Key 时自动退化为 Bearer 网关模式（兼容 302.ai 等聚合网关）
- 用途标签「推广视频」更名为「视频模型」，与弹窗选项及创意工作台视频区保持一致
- 视频模型配置成功后，创意工作台「视频素材创作区」的生成调用链路经集成测试全场景验证通过

**本次优化与更改的功能 / 模块**
- 【修复】大模型配置 / 添加弹窗：用途勾选区始终展示「视频模型」，用户可正常配置视频生成模型
- 【优化】大模型配置 / 视频协议：新增可灵 Kling 原生异步协议入口（provider=keling），原生路径在 UI 中可达
- 【优化】大模型配置 / 展示：视频用途标签统一为「视频模型」
- 【优化】系统版本 / 版本更新：相关代码与配置已同步更新

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：仅前端弹窗用途渲染与协议下拉、PROVIDED 标签映射变更；后端视频 Provider 与配置解析逻辑不变，数据模型（usages 数组）保持兼容；旧配置中 usages 已含 video 者不受影响。

**验证**
- 后端集成测试 5 场景全部通过：① 无 video 配置 → 回退分镜；② generic-video + usages=[video] → ModelVideo；③ keling + usages=[video] → KlingVideo；④ 仅一个未激活 video 配置 → 回退分镜；⑤ 仅有文本模型(usages=[analysis]) → 不被误用于视频。
- 前端 vite build 通过（48 模块，无 TS 错误）；routers 模块导入通过；系统版本与 CHANGELOG/发布数据一致性由发版校验强制检查。

## V4.70 创意工作台·三步流程重构（素材类型 / 品牌 Logo 注入 / 双工作区 / 视频微调）

**发布日期**：2026-11-13
**变更类型**：重构 / 新增 / 删除 / 优化
**涉及模块**：创意工作台（素材创作平台）、后端接口、数据模型、前端与菜单、系统版本
**变更摘要**：对「创意工作台」按需求文档重构为「解析产品 → 规划创意 → 批量生成」三步流程，新增素材类型选择、品牌 Logo 上传与「注入生成链路」开关、图片/视频双工作区与视频生成后微调对话框；同步删除「更多选项」「历史」「新建项目」等冗余入口，补齐分析框架自检（5.1 自动阻断）与品牌 Logo 注入链路（网站分析=推理大模型 / 图片=文生图大模型 / 视频=视频大模型）。

**更新要点**
- 输入框子模块：保留落地页网址与投放平台，新增「素材类型」下拉（图片 / 视频 / 图片和视频，默认图片和视频）；品牌行改为 Logo 上传按钮，Logo 预览显示在品牌标题下方，并新增「注入生成链路」勾选（默认不勾选，勾选则 brand_logo 传入图片与视频生成链路）
- 删除「更多选项」（复用产品 / 复用参考图 / 复用品牌）与「历史」「新建项目」入口，输入区更聚焦
- 第二步规划创意分而治之：图片按现有 routes 规划并支持补充指令；视频通过受控 VideoStudio 对话式分镜规划，分别作用于图片与视频任务
- 第三步批量生成双工作区：图片工作区按现有素材样式展示进度与成片；视频工作区直连视频大模型生成，并新增「生成后微调对话框」（输入新调整提示词后先精修分镜再重生成），仅展示进度不暴露内部流程
- 品牌 Logo 注入贯通前后端：schemas（CWVideoPlanRequest / CWVideoGenerateRequest 新增 brand_logo）→ routers（注入视频 prompt 与 meta，图片经 style_opts.brand_logo / logo 字段）→ 生成链路
- 自检 5.1 自动阻断：分析框架（title / summary / boxes×4 / brief×3）不完整则提示重新分析并停留输入态；5.2 图片定位与 5.3 视频流转仅人工查看，不硬拒

**本次优化与更改的功能 / 模块**
- 【重构】前端与菜单 / 创意工作台：输入模块、三步流程、图片/视频双工作区重写，VideoStudio 改为受控组件（plan/work 双模式共享分镜状态）
- 【新增】前端与菜单 / 素材类型与品牌 Logo：素材类型下拉、Logo 上传与预览、注入生成链路开关
- 【新增】后端接口 / 视频规划与生成：CWVideoPlanRequest、CWVideoGenerateRequest 新增 brand_logo 字段并注入 prompt/meta
- 【删除】前端与菜单 / 冗余入口：移除「更多选项」「历史」「新建项目」
- 【优化】前端与菜单 / 自检：isFrameOk 校验分析框架完整性，缺失时阻断并引导重新分析
- 【优化】系统版本 / 版本更新：系统版本升至 V4.70

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：涉及创意工作台输入模块、三步流程、视频受控组件、相关样式，以及后端视频请求模型与路由注入；未改动数据模型表结构（schemas 仅新增可选字段、默认空串），旧接口与历史生成数据保持兼容；「更多选项 / 历史 / 新建项目」移除为纯前端入口删除，不影响后端接口。

**验证**
- 后端 py_compile 通过：backend/schemas.py、backend/routers.py、backend/version.py 编译无误；routers 视频生成函数已确认在构造 prompt 与 meta 处注入 brand_logo。
- 前端类型检查 npx tsc --noEmit 0 错误；npx vite build 通过（48 模块，无 TS 错误），产出 dist 资源。
- 分析框架自检：isFrameOk 校验 title/summary、boxes 四大项（industry/coreAudience/purchaseMotivation/priceBand）、brief 三项（promotionGoal/targetAudience/sellingPoints），与 cwAnalyze（_build_cw_result）返回结构一致，缺失时阻断进入下一步。
- 系统版本与 CHANGELOG / 发布数据一致性由发版校验（prepare_release --check）强制检查；该条目由本次改动文件自动归纳（含后端接口、数据模型、前端与菜单、系统版本）。

## V4.71 视频 Provider 适配阿里云百炼 MaaS（wan3.0-video 开箱可用）

**发布日期**：2026-11-13
**变更类型**：新增 / 优化
**涉及模块**：大模型配置、视频 Provider、前端设置页、系统版本
**变更摘要**：在「大模型配置 → 视频模型」新增「阿里云百炼 MaaS（wan3.0-video）」预设，并扩展通用视频 Provider（ModelVideo）以参数化开关兼容阿里云 MaaS 契约，使该模型可在创意工作台视频素材区直接驱动出片，且不改动其它厂商路径。

**更新要点**
- 新增视频预设「阿里云百炼 MaaS（wan3.0-video）」：默认 base_url 为本次实测网关地址，选中即预填 endpoint / body_shape=dashscope_maas / poll_path=/api/v1/tasks / async_header=true 四个参数，用户只需补填 API Key 与 Model 即可保存测试
- ModelVideo 扩展参数化开关（写在模型配置「参数(JSON)」中，均为字符串）：endpoint（提交路径，默认 /video/generations）、body_shape="dashscope_maas"（改用 {model, input:{prompt}, parameters:{size,count}} 提交体）、async_header="true"（附加 X-DashScope-Async: enable 头）、poll_path（自定义轮询路径，优先于内置候选）
- 前端设置页：选中预设时若含 default_params 则自动带入参数，免去手敲 JSON
- 实测：提交后约 3 分钟出 5s/1080p/30fps/9:16 竖屏 MP4，成片 URL 有效期约 24h；API Key 须将部署机公网 IP 加入白名单

**本次优化与更改的功能 / 模块**
- 【新增】大模型配置 / 视频预设：阿里云百炼 MaaS（wan3.0-video）预设与 default_params
- 【优化】视频 Provider / ModelVideo：参数化兼容阿里云 MaaS 提交体、异步头与轮询路径，其它厂商契约不变
- 【优化】前端设置页 / 大模型配置：预设选中时预填 default_params
- 【优化】系统版本 / 版本更新：系统版本升至 V4.71

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：仅新增视频预设、扩展 ModelVideo 的 params 分支（默认分支行为不变）、前端预设参数预填；未改动数据模型表结构，旧 generic-video 配置（如 Pika/Luma/可灵聚合网关）行为完全不变。

**验证**
- 后端 py_compile 通过：backend/providers.py、backend/llm_catalog.py、backend/version.py 编译无误；ModelVideo 的 dashscope_maas 提交体 / 异步头 / 自定义轮询路径分支已按阿里云实测契约实现，且 _video_find_media/_video_find_status/_video_find_task_id 原生支持 video_url / task_status / task_id 字段，轮询可直接取片。
- 前端类型检查：api.ts 的 ModelPreset 增加可选 default_params 字段；LLMSettings.tsx 选中预设预填 default_params；npx tsc --noEmit 与 npx vite build 验证（构建含本次改动）。
- 阿里云 MaaS 接口已实测闭环：提交（X-DashScope-Async: enable）→ 轮询 /api/v1/tasks/{id}（task_status: RUNNING→SUCCEEDED）→ 取回 9:16 竖屏 MP4（video_url 预签名 URL，HTTP 206 验证可下载）。
- 系统版本与 CHANGELOG / 发布数据一致性由发版校验（prepare_release --check）强制检查；该条目由本次改动文件自动归纳。

## V4.72 视频大模型连通测试修复（按真实调用契约提交，含请求头/参数）

**发布日期**：2026-11-13
**变更类型**：修复 / 优化
**涉及模块**：大模型配置、后端连通测试、前端设置页、系统版本
**变更摘要**：修复「大模型配置 → 视频模型」连通性测试不读取 params 开关，导致阿里云百炼 MaaS 等需要特殊端点/请求体/异步头的视频模型「保存并测试」必败的问题；测试链路透传 params，使测试按真实生成契约（ModelVideo 同款开关）提交，并正确判定通过，补齐视频模型「配置信息可视化」。

**更新要点**
- 后端 `_test_generic_video` 重构：读取 `params.endpoint`（提交路径）、`params.body_shape`（提交体形状，dashscope_maas → {model, input:{prompt}, parameters:{size,count}}）、`params.async_header`（true → 附加 `X-DashScope-Async: enable` 头）；识别到 `task_id` 即判通过（异步任务不阻塞轮询）；默认通用视频（无 params）仍走 /video/generations 契约，行为不变
- 测试链路透传 params：路由 `test_model` 与 `model_health._cfg_request` 均把完整 `params` 传入 `test_llm_connection`，使「保存并测试」「测试已保存配置」「每日健康测试」三处均生效
- 前端 `LLMSettings.testOnly` 提交时带上 `form.params`，保存前测试即可用预设开关
- 阿里云预设 `notes` 显式补充【请求头】/【提交参数】/【轮询】三段说明，用户可在配置卡直接看清关键配置（无需翻 default_params 原始 JSON）

**本次优化与更改的功能 / 模块**
- 【修复】后端连通测试 / 视频：_test_generic_video 按 params 构造端点/请求体/请求头，与 ModelVideo 真实生成一致
- 【优化】后端连通测试 / 透传：test_model 与 _cfg_request 透传完整 params
- 【优化】前端设置页 / 测试：testOnly 携带 form.params
- 【优化】大模型配置 / 配置信息：阿里云预设 notes 显式列出请求头与参数
- 【优化】系统版本 / 版本更新：系统版本升至 V4.72

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：仅改动视频连通测试函数与测试请求透传；旧通用视频配置（Pika/Luma/可灵聚合网关等）默认契约路径不变；未改动数据模型表结构；params 字段为既有 JSON 列，读取按 dict 容错。

**验证**
- 离线构造校验：对阿里云预设 params 复刻 _test_generic_video 的端点/请求体/头构造，输出 URL=`.../api/v1/services/aigc/video-generation/video-synthesis`、headers 含 `X-DashScope-Async: enable`、body=`{model,input:{prompt},parameters:{size,count}}`，与 V4.71 实测成功调用逐一一致。
- 默认通用视频路径校验：无 params 时仍构造 /video/generations 契约且不含异步头，回归安全。
- 真实联调：用真实 Key 调用 `test_llm_connection`，请求正确抵达阿里云网关（返回结构化 `AccessDenied` 而非 404/400 格式错），证明端点/请求体/请求头已被网关接受；仅剩「Key 的 IP 白名单」为账户侧配置（非代码缺陷）。
- 后端 py_compile 通过：backend/llm_catalog.py、backend/routers.py、backend/model_health.py 编译无误。
- 系统版本与 CHANGELOG / 发布数据一致性由发版校验（prepare_release --check）强制检查；该条目由本次改动文件自动归纳。

## V4.74 视频生成链路「输出比例 9:16」显式标注（模型固定比例如实标注）

**发布日期**：2026-11-13
**变更类型**：优化 / 透明度增强
**涉及模块**：后端视频 Provider、后端视频生成路由、后端视频预设目录、前端视频工作室、前端样式
**变更摘要**：实测阿里云百炼 MaaS（wan3.0-video）忽略提交体中的 size、固定输出 9:16 竖屏——即使分镜/用户在「比例」里选了 16:9 或 1:1，出片仍是 9:16。此前链路只在 size 推导里隐式按宽高比给一个 size，既未向用户说明、也未在结果上标注真实比例。本次把「实际输出比例」做成显式、可信的标注：后端据模型配置参数 `output_aspect`（dashscope_maas 默认 9:16）推导真实输出比例，贯穿「分镜规划 → 生成提示词 → 成片结果」全链路；前端在规划头、生成工作区头、生成结果区都以标签明示「输出比例 9:16（竖屏）」，并在所选比例与模型固定比例不一致时给出醒目提示，杜绝“选了横版却出竖版”的困惑。

**更新要点**
- 后端 `ModelVideo` 新增「实际输出比例」推导：读配置参数 `output_aspect`，未显式声明且 `body_shape=dashscope_maas` 时默认 `9:16`；命中后强制把 meta.aspect 覆写为该比例，使提交提示词、size 推导、回传结果三处一致。
- `ModelVideo` 全部返回路径（同步直出 / 异步轮询取片 / 各类回退分镜）统一携带 `output_aspect` 字段，保证结果比例可追溯。
- 后端 `api_cw_video_generate`：据视频配置参数推导 `output_aspect`，提示词与 storyboard 的比例一律标注为实际输出比例；当模型固定比例与用户所选比例不一致时，拼接醒目 note（如「⚠️ 当前视频模型固定输出 9:16（竖屏），已按实际比例标注（与所选「16:9」不一致）」）。
- 后端 `api_cw_video_plan`：分镜规划阶段即据当前视频配置返回 `output_aspect`，规划头可提前明示真实比例。
- 阿里云百炼 MaaS 预设（`aliyun-maas-video`）的 `default_params` 新增 `output_aspect: "9:16"`，使「选预设即声明固定竖屏」；该参数为通用开关，任意固定比例模型均可声明。
- 前端 `VideoStudio` 新增 `AspectChip`：在「视频创意规划」头、「视频生成工作区」头、「生成结果」区三段均显式标注「输出比例 9:16（竖屏）」，并按竖屏/方版/横版着色；`VideoState` 新增 `outputAspect` 并在规划、生成、微调、父级 CreativeWorkbench 各入口贯通。
- `CWVideoPlanResult` / `CWVideoGenerateResult` 新增 `output_aspect` 字段；`CreativeWorkbench` 两处生成入口均透传该字段。

**本次优化与更改的功能 / 模块**
- 【优化】后端 / 视频 Provider：引入 output_aspect 推导与强制覆写，结果全链路携带真实比例
- 【优化】后端 / 视频生成路由：提示词、storyboard、note 按实际输出比例标注；比例不一致时给出提示
- 【优化】后端 / 视频规划路由：规划阶段即回传 output_aspect
- 【新增】后端 / 视频预设：阿里云预设声明 output_aspect=9:16（通用开关）
- 【新增】前端 / 视频工作室：AspectChip 在三段显式标注实际输出比例（竖屏/方版/横版着色）
- 【优化】前端 / 状态贯通：VideoState.outputAspect 在规划/生成/微调/父级入口贯通
- 【优化】系统版本 / 版本更新：系统版本升至 V4.74

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：仅新增 `output_aspect` 字段与展示标签，未改动数据模型表结构；旧 generic-video 配置（Pika/Luma/可灵聚合网关等）为空参数时 `output_aspect` 取用户所选比例，行为不变；已存 aliyun-maas-video 配置若未带 `output_aspect`，后端仍据 `body_shape=dashscope_maas` 默认 9:16，升级后自动如实标注。

**验证**
- 后端校验：py_compile 通过；`ModelVideo.generate` 在 `params.output_aspect=9:16` 或 `body_shape=dashscope_maas`（无 output_aspect）时，返回 dict 含 `output_aspect=9:16` 且 meta.aspect 被覆写；非固定比例模型返回用户所选比例。
- 前端类型检查：npx tsc --noEmit 0 错误；npm run build（tsc && vite build）通过，产出 dist 资源。
- 逻辑自检：`api_cw_video_generate` 当 `forced != requested_aspect` 时，note 含「固定输出 9:16」一致性提示；storyboard.aspect/output_aspect 均被覆写为实际比例；`api_cw_video_plan` 的 `output_aspect` 在视频模型配置存在时等于声明/默认比例。
- 系统版本与 CHANGELOG / 发布数据一致性由发版校验（prepare_release --check）强制检查；该条目由本次改动文件自动归纳。

## V4.73 视频大模型配置可用化：阿里云百炼做成「接口协议」一等公民，通用视频开放四项契约参数

**发布日期**：2026-11-13
**变更类型**：修复 / 优化
**涉及模块**：大模型配置、前端设置页、后端预设目录、后端连通测试、系统版本
**变更摘要**：修复「阿里云百炼 MaaS（wan3.0-video）」在「大模型配置」弹窗中无法被选择的问题——此前它仅登记在后端 VIDEO_PRESETS 目录，既不在前端协议下拉框，也因缺 modality/mainstream 标记而无法出现在快捷预设芯片，导致用户完全选不到；同时把「文生视频 · 通用兼容」协议开放 endpoint / body_shape / async_header / poll_path 四项契约参数，使用户可自主添加任意视频大模型并测试成功。

**更新要点**
- 阿里云百炼 MaaS 提升为「接口协议」下拉里的一等公民选项（key=aliyun-maas-video，名称「文生视频 · 阿里云百炼 MaaS（wan3.0-video）」），与 OpenAI / 可灵等并列直接可选，不再依赖隐藏的预设目录
- 选中该协议即自动装配 default_params：endpoint=/api/v1/services/aigc/video-generation/video-synthesis、body_shape=dashscope_maas、poll_path=/api/v1/tasks、async_header=true，用户仅需填 Key 与 Model 即可保存并测试
- 通用视频协议（generic-video）开放四项契约参数（extra_fields）：提交端点路径、请求体结构（default / dashscope_maas）、异步请求头（X-DashScope-Async）、轮询路径，满足「自主添加任意视频大模型」需求
- 新增「高级参数」可编辑区：把已自动装配的契约参数（如阿里云的 4 项）以可编辑输入框呈现并附中文说明，用户可手动微调或排查
- 后端测试路由补登记：_TESTERS 增加 aliyun-maas-video → _test_generic_video，使该 provider 的「保存并测试 / 仅测试」正确走视频契约而非误判为文本模型
- 预设目录标注：阿里云预设补 modality=video 并加入 MAINSTREAM_KEYS，使其在「视频」模态下也出现在快捷预设芯片（与协议下拉双入口）

**本次优化与更改的功能 / 模块**
- 【修复】前端设置页 / 协议下拉：阿里云百炼 MaaS 成为可选协议选项，解决「选不到」
- 【优化】前端设置页 / 通用视频：开放 endpoint / body_shape / async_header / poll_path 四项契约参数
- 【新增】前端设置页 / 高级参数：已装配契约参数可编辑展示
- 【修复】后端连通测试 / 路由：_TESTERS 登记 aliyun-maas-video，避免测试误走 OpenAI 文本路径
- 【优化】后端预设目录 / 可见性：阿里云预设补 modality 与 mainstream，快捷预设芯片在视频模态下显示
- 【优化】系统版本 / 版本更新：系统版本升至 V4.73

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：仅新增协议选项、扩展 generic-video 的 extra_fields、新增高级参数渲染、补测试路由映射与预设可见性标记；未改动数据模型表结构；旧 generic-video 配置（Pika/Luma/可灵聚合网关等）默认契约路径不变（空参数即走默认），已存 aliyun-maas-video 配置的 provider 字段保持原值、升级后测试/生成均按既有 params 生效。

**验证**
- 后端校验：py_compile 通过；`aliyun-maas-video` 已登记于 _TESTERS 并指向 _test_generic_video；get_all_presets 中该预设 modality=video、mainstream=True、default_params 四项完整；_resolve_protocol('aliyun-maas-video') 正确回退到 generic-video 协议。
- 前端类型检查：npx tsc --noEmit 0 错误；npm run build（tsc && vite build）通过，产出 dist 资源；修复了一处 JSX 字面量花括号导致的 TS1005 解析错误。
- 真实联调：以 provider=aliyun-maas-video + 真实 params 调用 test_llm_connection，请求正确抵达阿里云网关（HTTP 403 AccessDenied「IP access denied」），证明端点/请求体/异步头构造与 V4.71 实测成功调用完全一致；仅余 Key 的 IP 白名单为账户侧配置（部署机公网 IP 需加入白名单）。
- 系统版本与 CHANGELOG / 发布数据一致性由发版校验（prepare_release --check）强制检查；该条目由本次改动文件自动归纳。

## V4.75 系统结构精简与视频链路修复（素材历史并入创意工作台、视频任务号解析纠错、通知时间到分钟）

**发布日期**：2026-11-16 10:07
**变更类型**：优化 / 删除 / 修复
**涉及模块**：前端与菜单、素材历史、创意工作台、视频生成链路、大模型配置、新版通知、发版流程、系统版本
**变更摘要**：按「素材创作平台」整体下线要求，把「素材历史」迁入「创意工作台」二级菜单末位并删除「素材创作」「素材提示词」两个子模块及其独占代码；同时修复视频生成「已配置大模型却出不了片」的根因——阿里云百炼把 task_id 嵌在 output 里，解析器误把顶层 request_id 当任务号轮询，必然轮询不到；并把「新版通知」的更新时间强制为 YYYY-MM-DD HH:MM。

**更新要点**
- 菜单重构：「素材历史」迁移为「创意工作台」的二级菜单并固定放最后一位；「素材创作平台」一级菜单整体移除
- 模块下线：删除「素材创作」「素材提示词」两个子模块及其独占代码（页面、会话中枢、任务浮窗、临时面板、任务矩阵），其余功能保持完整
- 视频修复（关键）：`_video_find_task_id` 优先解析 output/data 内的 task_id，不再把 request_id 误当任务号——此前会导致任务提交成功却轮询 6 分钟后静默回退分镜脚本
- 失败可诊断：视频调用失败时回传 HTTP 状态与服务端原文；区分「任务已受理但轮询超时」与「接口未返回任务号」，不再只有一句笼统回退提示
- 新增「诊断视频配置」：视频工作区一键自检当前生效的视频配置（用途 / 启停 / 契约参数是否齐备 / 连通状态），直接给出可行动的修复建议
- 测试 500 修复：`ModelTestIn` 补齐 params 字段，此前读取 req.params 抛 AttributeError，导致「保存并测试」必然失败
- 通知时间规范：「发布日期」支持并强制 `YYYY-MM-DD HH:MM`，发版脚本自动补时分，历史条目统一补齐，页面显示「更新于 …」
- 轮询提效：声明了 poll_path 的厂商只轮询该路径，避免每轮额外打 5 个必然 404 的候选地址触发限流
- 代理超时对齐：nginx `proxy_read_timeout` 300s → 660s，覆盖后端最长 6 分钟取片窗口，避免网关先 504 被误读为「生成失败」

**本次优化与更改的功能 / 模块**
- 【优化】前端与菜单 / 导航：素材历史移入创意工作台末位，素材创作平台一级菜单移除
- 【删除】前端与菜单 / 素材创作：删除 MaterialCreation、MediaAdStudio、AutoCreationPanel、creationSession、CreationTaskDock、taskMatrix
- 【删除】前端与菜单 / 素材提示词：删除 MaterialPromptLibrary 页面
- 【优化】素材历史 / 复用入口：移除已无落点的「复用分析继续创作」，保留查阅、放大、下载、批量删除
- 【修复】视频生成链路 / 任务解析：task_id 优先取 output.task_id，request_id 降为兜底
- 【优化】视频生成链路 / 错误可见性：回传 HTTP 状态与服务端原文，区分轮询超时与无任务号
- 【新增】视频生成链路 / 自检：新增 GET /api/cw-video/diagnose 与工作区「诊断视频配置」
- 【修复】大模型配置 / 连通测试：ModelTestIn 补 params，修复测试接口 500
- 【优化】新版通知 / 时间格式：发布日期强制 YYYY-MM-DD HH:MM，运行时归一化并显示「更新于」
- 【优化】发版流程 / 校验：--sync 自动补时分，--check 拦截只有日期的发布日期
- 【优化】部署 / 反向代理：nginx proxy_read_timeout 300s → 660s，覆盖视频长轮询窗口
- 【优化】系统版本 / 版本更新：系统版本升至 V4.75

**影响范围**
- 前端 / 后端 / 数据 / 兼容性：导航与路由移除 creation / matprompts 两个 tab，旧地址 #/creation、#/matprompts 会回落到创意工作台；素材历史数据、后端历史/资产接口与既有归档完全保留，不受模块下线影响。视频链路仅调整任务号解析与错误文案，请求契约不变，已配置的阿里云 / 可灵 / 通用网关配置无需改动。通知时间格式对历史条目做统一补齐，不改动任何版本内容。
- 部署：前端 dist 需随宿主 `docker compose up -d --build` 重建；后端 release_notes_data.py 已随 --sync 重建。

**验证**
- 后端校验：py_compile 通过；`_video_find_task_id` 单测通过——DashScope 响应解析为 TASK-999（此前误取 REQ-123）、OpenAI 形态取 id、仅 request_id 时兜底。
- 端到端验证：以本地假服务复刻阿里云契约（异步头 + {model,input,parameters} 提交体 + /api/v1/tasks 轮询 + 预签名取片），ModelVideo 全链路返回 provider=model 且落盘文件非空，output_aspect=9:16。
- 前端类型检查：npx tsc --noEmit 0 错误；npm run build 通过。
- 发版校验：prepare_release --sync 自动补齐时分并重建发布数据，--check 通过（系统版本 == CHANGELOG 最新 == 发布数据最新）。

## V4.76 视频出片异步化：提交即返回任务号 + 轮询取结果，根治反向代理 504 超时

**发布日期**：2026-11-16 10:47
**变更类型**：修复 / 优化
**涉及模块**：创意工作台、视频生成链路、前端 API 客户端、部署与反向代理、系统版本
**变更摘要**：视频出片要等模型 1–6 分钟，此前占着一个 HTTP 请求不返回，宿主 nginx（Ubuntu 1.24，默认 proxy_read_timeout 60s）先回 504，页面只显示「Gateway Time-out」而任务其实还在厂商侧跑。改为「提交即返回 job_id + 前端每 2.5s 轮询状态」后，出片时长与任何代理超时彻底解耦，同时页面显示已等待秒数与阶段，任务失败也能拿到真实原因。

**更新要点**
- 新增异步出片接口：POST /api/cw-video/generate-jobs 立即返回 job_id（实测 0ms），GET /api/cw-video/generate-jobs/{id} 轮询状态与结果
- 出片主流程抽取为同步/异步共用的 _cw_video_generate_impl，两条路径结果结构完全一致，不存在两套逻辑漂移
- 后台任务自建数据库会话（请求会话在接口返回即关闭），不占用连接、不产生写锁
- 任务注册表带 TTL 与上限（3 小时 / 60 条），过期自动清理，长时间运行不会堆积成片结果
- 前端统一改走异步：api.cwVideoGenerateAsync 内部完成「提交 → 轮询 → 归一化结果」，连续 3 次轮询失败才放弃，避免网关抖动误判失败
- 进度可见：生成区显示「已等待 N 秒 · 阶段」，不再是一句静态「生成中」，用户能判断任务确实在跑
- 超时兜底：12 分钟未完成会返回任务号并提示到厂商控制台取片，不再笼统报「生成失败」
- 同步接口 /api/cw-video/generate 保留兼容（脚本/调试用），文档明确其需要反代 ≥660s
- 部署文档补充「长任务与反代超时」对照表：宿主 nginx 60s、Cloudflare 100s、容器内 nginx 660s 的边界与处理方式

**本次优化与更改的功能 / 模块**
- 【新增】视频生成链路 / 异步任务：/cw-video/generate-jobs 与 /cw-video/generate-jobs/{job_id}
- 【修复】视频生成链路 / 504 超时：出片不再占用长连接，任意代理超时下均可完成
- 【优化】视频生成链路 / 结构：同步与异步共用同一实现，结果字段一致
- 【优化】视频生成链路 / 进度：展示已等待秒数与阶段，失败回传真实原因
- 【优化】前端 API 客户端：新增 cwVideoGenerateAsync / cwVideoGenerateJob / cwVideoJob
- 【优化】创意工作台 / 视频区：生成与微调重生成均走异步轮询
- 【优化】创意工作台 / 批量创作：视频节点进度文案显示已等待时长
- 【优化】部署 / 反向代理：DEPLOY.md 增补长任务超时说明与宿主 nginx 配置示例
- 【优化】系统版本 / 版本更新：系统版本升至 V4.76

**影响范围**
- 后端：新增两个接口与内存任务表，原有同步接口签名与返回结构不变；出片请求契约、厂商参数（endpoint / body_shape / poll_path / async_header）完全不变，既有模型配置无需改动。
- 前端：视频生成改用异步轮询，页面交互与结果展示不变；dist 需随宿主重建。
- 部署：单进程 uvicorn 下任务表在内存中；若将来改为多 worker 或多副本，需将任务表迁移到数据库/Redis（当前部署形态不受影响）。

**验证**
- 端到端：以本地假服务复刻阿里云契约（X-DashScope-Async + {model,input,parameters} + /api/v1/tasks 轮询 + 预签名取片），提交耗时 0ms，9 秒后任务 done，provider=model、output_aspect=9:16、成片落盘非空。
- 失败路径：注入 error 任务，轮询能取回原始失败原因（HTTP 403 原文），不再被吞。
- 编译与类型：py_compile 通过；npx tsc --noEmit 0 错误；npm run build 通过。
- 发版校验：prepare_release --sync 重建发布数据并补时分，--check 通过。

## V4.77 素材创作任务常驻：切页面不中断，任意页面可查进度

**发布日期**：2026-11-16 11:06
**变更类型**：新增 / 优化
**涉及模块**：创意工作台、全局任务栏、导航与路由、前端状态管理、系统版本
**变更摘要**：此前创意工作台一旦切到其他菜单就被卸载，正在跑的素材生成任务连同进度一起丢失，回来只能从头再来。现在工作台改为常驻挂载（切走只隐藏不卸载），生成过程与结果原样保留；同时新增全局「素材创作任务」浮窗，在其他任何页面都能看到已等待时长、百分比、图片/视频分阶段进度，并可一键回到工作台查看结果。

**更新要点**
- 工作台常驻挂载：切到「素材历史 / 全球创意分析 / 系统设置」等页面时组件不卸载，图片任务轮询与视频出片轮询继续运行，回到本页进度与已生成素材原样还在
- 新增全局任务浮窗：右下角常驻卡片，展示任务状态（进行中 / 已完成 / 失败 / 已中断）、产品与投放平台、进度条、百分比、当前动作文案
- 分阶段进度：图片阶段显示「已生成数/任务总数」与失败数，视频阶段显示「出片 / 已出片」，一眼看出卡在哪一步
- 实时计时：进行中每秒刷新已用时长，避免「是不是卡死了」的误判
- 一键返回：点「查看任务」直接回到创意工作台（URL 同步），回到的是原来那条任务，不会重新开始
- 尊重用户操作：手动关闭浮窗后，同一任务的后续进度不再自动弹出；只有点击「开始生成」进入新一轮任务才会重新出现
- 刷新语义诚实：页面刷新/关闭后前端流程已不存在，浮窗标记为「已中断」并保留最后一次进度，不假装还在跑
- 顺手修复导航分组重复 key：两个分组此前共用 `system` 键，导致折叠状态互相串联（点一个另一个也跟着收起）
- 调试入口仅在开发环境暴露（生产构建已剔除），便于自动化验证任务栏行为

**本次优化与更改的功能 / 模块**
- 【新增】创意工作台 / 任务常驻：全局任务状态存储（cwTask）与订阅机制
- 【新增】全局任务栏 / 浮窗：CwTaskDock，支持展开/收起/关闭与一键返回工作台
- 【优化】创意工作台 / 挂载方式：切页只隐藏不卸载，生成请求与结果不丢失
- 【优化】创意工作台 / 进度同步：批量生成的实时进度、阶段、产物数量写入常驻状态
- 【优化】导航 / 菜单分组：修复重复 key，分组折叠不再互相联动
- 【优化】系统版本 / 版本更新：系统版本升至 V4.77

**影响范围**
- 前端：新增两个模块（cwTask 状态层、CwTaskDock 浮窗），其余为工作台与 App 的挂载/接线调整；后端接口与数据无改动。
- 交互变化：切换菜单不再重置创意工作台，历史输入与已生成结果会保留，需要清空请用工作台内的「重置」。
- 部署：前端 dist 需随宿主 `docker compose up -d --build` 重建。

**验证**
- 无头浏览器实测（真实登录态 + 真实页面）：切到「素材历史」后工作台仍在 DOM 且为隐藏态，浮窗按 60% 进度正确展示；点「查看任务」回到 `#/workbench`，DOM 标记验证未重新挂载（原状态保留）。
- 状态链路：运行中显示「进行中 / 已用 N 秒」并逐秒递增，进度从 25% → 70% 跟随；完成态显示「已完成 / 查看结果」；关闭后浮窗消失，同一任务后续刷新不再弹出，新一轮生成重新出现。
- 刷新语义：预置 running 快照后重新加载，浮窗显示「已中断」并保留进度与阶段（阶段标记为停止而非失败）。
- 质量：npx tsc --noEmit 0 错误；npm run build 通过；生产构建中确认调试钩子 `__cwTask` 已被剔除；上述用例控制台无报错。

## V4.78 视频模型路由纠偏：文本模型不再冒充视频模型（分镜模型 / 出片模型分栏标注）

**发布日期**：2026-11-16 11:18
**变更类型**：修复 / 优化 / 新增
**涉及模块**：创意工作台（视频规划与出片）、大模型配置路由、视频链路诊断、数据模型（视频响应 schema）、发版流程（版本号与通知同步）、系统版本
**变更摘要**：用户在「大模型配置」里配好的是「阿里千问视频模型」，但创意工作台的视频面板却显示成 deepseek。经排查这不是模型配置没生效，而是两处语义被混为一谈：分镜规划走的是**文本模型**（analysis 用途），其调用快照被写进同一个 `model_info` 并当作「视频模型」展示；同时视频用途的候选只按「用途标签」筛选、不校验模态，一旦文本配置的用途里残留了 video，出片就会拿 deepseek 去打 `/video/generations` 并静默回退分镜。本次把「分镜文案模型」与「出片视频模型」彻底分栏：接口分别回传、页面分别标注，并在选型层加模态校验，文本模型一律不得接管出片。

**更新要点**
- 模型快照拆分：分镜规划接口新增 `video_model_info`（真实出片模型）与 `video_model_ready`，`model_info` 只表示本次分镜策划调用的文本模型（role=analysis），二者不再互相顶替
- 页面双徽标：视频面板同时显示「出片模型 · wan3.0-video」与「分镜模型（文本）· deepseek-chat」，未配视频模型时明确标注「出片模型 · 未配置（回退分镜）」，不再拿文本模型顶替
- 进面板即自检：打开视频区就静默读取当前生效的出片模型，无需先点「诊断」即可确认系统到底会调用谁
- 选型层模态校验：`_pick_config(video)` 新增四路识别（视频协议 / 视频厂商 key / 厂商契约参数 / 模型名特征），文本模型即使被误勾「视频」也不会被选中，避免把文本端点当视频端点调用
- 跳过原因可见：诊断接口新增 `candidates`（可用候选，标注「← 本次出片将使用」）与 `skipped`（被跳过项及原因），并明确提示「某配置用途勾了视频但它是文本模型，已自动跳过」
- 失败提示更诚实：出片回退分镜时，说明是「压根没配视频模型」「配了但被停用/缺 Key」还是「配的其实是文本模型」，不再只有一句「未配置视频模型」
- 多候选说明：同用途存在多条可用视频配置时，页面说明系统按「连通测试通过优先 → id 更大优先」选中了哪条、未选中的有哪条
- 顺手修正展示反向混淆：工作台批量出片结果此前把视频模型写回 `modelInfo`（文本字段），现改为写入独立的视频模型字段

**本次优化与更改的功能 / 模块**
- 【修复】创意工作台 / 视频规划：分镜文本模型与出片视频模型的快照分离，视频面板不再显示文本模型
- 【修复】大模型路由 / 视频用途：新增模态校验，文本模型不得接管视频出片
- 【新增】视频链路诊断 / 候选清单：列出可用候选与被跳过配置及原因
- 【优化】视频面板 / 模型徽标：出片模型与分镜模型分栏展示，未配置时如实标注回退分镜
- 【优化】出片失败提示：按「未配置 / 未启用 / 配置为文本模型」分类给出可行动建议
- 【优化】系统版本 / 版本更新：系统版本升至 V4.78

**影响范围**
- 后端：`providers.py` 新增模态识别与路由剖析（`is_video_capable` / `video_route_report`），`_pick_config` 对 video 用途加过滤；`routers.py` 分镜接口新增两个字段、诊断接口扩展、出片失败说明细化；`schemas.py` 扩展 `CWVideoPlanResult`。均为新增字段，旧调用方不受影响。
- 前端：`VideoStudio` 双徽标与诊断清单，`CreativeWorkbench` 状态切片新增 `videoModel`。
- 行为变化（重要）：若某条**文本模型**配置的用途里勾了「视频」，升级后它不再参与出片（此前会尝试调用并失败回退）。需要真正出片请新增一条「文生视频」协议配置；不再需要可把该文本配置的「视频」用途取消。
- 部署：需 `docker compose up -d --build` 重建前后端。

**验证**
- 路由单测（临时库三配置：deepseek 文本[用途含 video] / 千问文本 / 阿里千问视频模型）：`_pick_config(video)` 选中 `wan3.0-video`，`deepseek-chat` 出现在 skipped；仅保留文本配置时返回 `None`（回退分镜）且跳过原因为「不是视频协议或视频模型」；9 组供应商/模型模态识别全部符合预期。
- 接口实测（登录态真实请求）：`GET /api/cw-video/diagnose` 返回 `config_id=2 / model=wan3.0-video`、`candidates` 标注「本次出片将使用」、`skipped` 为空；`POST /api/cw-video/plan` 返回 `model_info=deepseek/deepseek-chat(role=analysis)` 与 `video_model_info=model/wan3.0-video(role=video)`、`video_model_ready=true` —— 正是本次修复前被混为一个字段、显示成「视频模型是 deepseek」的场景。
- 诊断链路：预置无效 Key 的视频配置时，诊断如实回传 401 `InvalidApiKey` 原文并给出白名单/Key 提示。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 补充：出片模型徽标只在「诊断成功」或「接口已回传视频模型」时展示；诊断请求失败（未授权 / 网络异常）不再显示「未配置（回退分镜）」，避免误报。

## V4.95 创意文案展示区按媒体平台定义标题并对齐后台文案面板样式

**发布日期**：2026-11-18 16:57
**变更类型**：新增 / 优化 / 修复
**涉及模块**：素材创作平台 / 创意工作台（文案）、平台文案规格库、前端展示、发版流程、系统版本
**变更摘要**：按用户提供的 Meta 广告后台截图优化创意文案展示区。此前文案字段用紧凑的「标签 + 值」两列排版、字段名沿用内部术语（Meta 显示「主文案 / 标题」），且字数统计因以 label 为 key 查找而从未显示。本版把字段名改为按媒体平台定义——Meta 对齐后台原文案面板的「正文 / 广告标题 / 描述 / CTA 按钮」，其他平台保留各自术语；展示改为截图样式的纵向卡片：字段标题 + ⓘ 说明图标 + 独立浅灰描边圆角输入框，字号与留白放大；字段严格按平台 schema 顺序渲染，字数统计改为按字段 key 精确匹配（兼容旧数据按 label），超限标红并写入信息图标提示。界面布局、菜单与工作流不变。
**更新要点**
- 【字段名按平台定义】`backend/media_ad.py` 的 Meta 文案 schema label 改为「正文 / 广告标题 / 描述 / CTA 按钮」；key、字数上限、count 全部不变，不影响生成与校验规则。Google 仍为「RSA 标题 / RSA 描述」，其余平台维持原术语。
- 【截图样式展示】新增前端 `CopyFieldCards` 组件：每个字段一张卡片（标题 + ⓘ + 独立描边输入框），纵向排列、间距 26px、标题 17px 加粗、输入区 16px 字号；文案工作区与图片工作区内的「广告文案」共用同一组件，样式一致。
- 【顺序与兼容】字段按 `schema` 定义顺序展示（Meta 依次 正文 → 广告标题 → 描述 → CTA），schema 之外的历史字段兜底追加；信息图标 title 显示平台名、字数上限与当前字数。
- 【字数修复】`_char_table()` 每行增加 `key` 字段，前端按 key 精确匹配字数并兼容旧数据按 label 匹配，修复 V4.92 起字数徽标从未显示的问题；多值字段（如 Meta 广告标题 3 条）分别计数、任一超限即标红。
**本次优化与更改的功能 / 模块**
- 【优化】创意文案工作区与图片区文案展示：字段名按媒体平台定义、样式对齐 Meta 后台截图（标题 + ⓘ + 独立输入框）。
- 【修复】文案字数统计不显示：字数表改带字段 key，前端按 key 匹配，兼容历史数据。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.95。
**影响范围**
- 后端修改：`backend/media_ad.py`（Meta 字段 label 对齐后台术语；`_char_table()` 每行带 key）。
- 前端修改：`frontend/src/pages/CreativeWorkbench.tsx`（新增 `CopyFieldCards`、替换两处字段渲染）、`frontend/src/styles.css`（卡片样式）。菜单、布局、字段结构与工作流不变。
- 数据：无表结构变更；旧文案数据无 key 时按 label 回退匹配，展示与字数不受影响。
- 行为变化：仅展示层与字段名显示变化；生成、平台规格校验、复制 / 下载逻辑保持不变。
**验证**
- 新增测试：`tests/test_copy_display_v495.py` **5/5 通过**（Meta 字段 label 对齐后台、key/limit 不变、其他平台术语独立、字数表带 key 且多值正确、前端按 schema 顺序渲染并保留图标与字数）。
- 全量回归：`tests/run_all.py` **255 项，失败 0 / 错误 0 / 跳过 2**（原 250 + 新增 5）。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过（47 模块，CSS 113.82 kB / JS 291.20 kB）。
- 发版校验：`python3 scripts/prepare_release.py --check` 通过，系统版本 / CHANGELOG / 发布数据均为 V4.95。

## V4.94 三道防线收官——播放层品牌字样叠加与成片视觉复核门（阶段二 / 三）

**发布日期**：2026-11-18 15:02
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台 / 创意工作台（视频）、品牌黄金词典、成片交付门、前端播放层、发版流程、系统版本
**变更摘要**：完成 V4.93 提出的三道防线剩余两道。阶段二把品牌名 / CTA 从"让视频模型画字"改为播放层 DOM 逐字叠加，叠加文案只来自已确认黄金词典，原片保持零文字、下载不带字；阶段三在成片交付前抽首 / 中 / 尾帧，调用**真实**视觉模型识别画面文字并与黄金词典 / 零文字策略比对，发现错字、错拼品牌名或词典外文字即判 needs_attention + TEXT_VISION_MISMATCH，原片保留可下载核对。视觉模型未配置或调用失败时明确标 unavailable（未复核），绝不冒充已通过，也不因工具缺失误伤成片。至此，源头词典（阶段一）+ 播放层叠加（阶段二）+ 成片视觉复核（阶段三）形成闭环，不再依赖视频模型正确书写品牌字样。
**更新要点**
- 阶段二：`brand_lexicon.build_text_overlay()` 从已确认 brand / CTA 生成播放层配置，拒绝 plan 自声明与 facts 整句；配置随出片任务冻结、随成片结果下发，前端新增轻量 `VideoTextOverlay.tsx`，在视频卡片上逐字叠加品牌名 / CTA，可一键隐藏；下载的原片仍零文字。
- 阶段三：新增 `backend/video_vision_audit.py`：`extract_frames()` 用 imageio-ffmpeg 的 ffmpeg 抽帧（无 cv2 / numpy 重依赖）；`recognize_frames()` 只走**真实** OpenAI 兼容视觉接口，绝不经过 MockLLM / FallbackLLM，失败即 unavailable；`audit_video_vision()` 按零文字 / 批准清单比对，任何画面文字都形成 violation，品牌近似错拼单独标注正确拼写。
- 交付门：worker 在落盘校验后执行视觉复核；违规时任务标 needs_attention + `TEXT_VISION_MISMATCH`、资产标 noncompliant，给出"检查拼写后重新生成"的唯一动作；时长 / 规格门保持原有结论，三类门的失败原因互不覆盖。
- 诚实降级：无视觉配置、非 OpenAI 兼容协议、抽帧失败、模型返回不可解析结果，一律返回 unavailable / skipped 并在结果与界面标注"未做画面文字复核"，不误判成片、不冒充通过。
- 前端最小改动：仅在视频卡片增加叠加层与两个状态徽标，布局、菜单、字段与工作流不变；`options.vision_audit=false` 可关闭复核（默认开启）。
**本次优化与更改的功能 / 模块**
- 【新增】播放层文字叠加配置与前端 DOM 叠加组件，品牌字样不再由视频模型绘制。
- 【新增】成片抽帧 + 真实视觉模型 OCR + 黄金词典比对的交付门模块。
- 【新增】错误码 TEXT_VISION_MISMATCH 与"画面文字未通过 / 未做画面文字复核"状态展示。
- 【优化】V4.93 阶段一提示词与零文字策略原样保留；视觉复核作为最后兜底，不改动原片。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.94。
**影响范围**
- 后端修改：新增 `backend/video_vision_audit.py`；修改 `backend/brand_lexicon.py`（build_text_overlay）、`backend/routers.py`（规划 / 出片 meta 冻结叠加与复核配置、状态标签）、`backend/creative_tasks.py`（worker 交付门接入、结果 / 任务视图字段、资产判定）。
- 前端修改：新增 `frontend/src/VideoTextOverlay.tsx`；修改 `VideoStudio.tsx`（视频卡片叠加与徽标）、`CreativeWorkbench.tsx`（任务结果透传）、`styles.css`（叠加层与徽标样式）。菜单与布局不变。
- 数据：无表结构变更；叠加配置与视觉复核结论写入既有 result_json / 任务视图，随任务可追溯。
- 行为变化：成片画面被真实视觉模型识别出文字时不再标 succeeded；无视觉能力时仍按原时长 / 规格结论交付，但明确标注未复核。真实付费出片、真实模型 OCR 抽检、品牌方确认属外部验收，不能用模拟测试替代。
**验证**
- 新增测试：`tests/test_video_overlay_and_vision_v494.py` **11/11 通过**（叠加只取词典、无品牌不叠加、抽帧采样去重、真实生成的测试片抽帧成功、无配置 unavailable、JSON 容错、零文字策略拦截、词典原文通过、错拼拒绝、抽帧失败不冒充通过、前后端接入断言）。
- 全量回归：`tests/run_all.py` **250 项，失败 0 / 错误 0 / 跳过 2**（原 239 + 新增 11）。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过（47 模块，产物 JS 290.86 kB / CSS 112.52 kB）。
- 发版校验：`python3 scripts/prepare_release.py --check` 通过，系统版本 / CHANGELOG / 发布数据均为 V4.94。
- 未验证：真实付费出片、真实视觉模型对线上成片的 OCR 抽检、品牌方书面确认均未执行，仍为外部验收项。

## V4.93 品牌黄金词典——视频上屏文字唯一事实源，杜绝品牌名 / 单词错拼（阶段一）

**发布日期**：2026-11-18 14:45
**变更类型**：新增 / 优化 / 修复
**涉及模块**：素材创作平台 / 创意工作台（视频）、提示词契约层、视频文字审查、发版流程、系统版本
**变更摘要**：针对成片中品牌名称错误、单词拼错、文字错误仍然突出的问题，实施「三道防线」方案的阶段一——建立品牌 / 文案黄金词典作为上屏文字的唯一事实源，把视频出片固化为零文字策略（品牌字样交给播放层叠加），并把批准清单从落地页 facts / 卖点整句收紧为只认黄金词典。根因是 V4.90 的批准清单把 facts / sellingPoints 整句也当作可上屏文字，品牌名 / 产品名就在其中，模型读到后试图「画」出来，必然出现缺笔画、近似字、错拼；且被校验对象（plan.approved_texts）可以自我批准，错拼品牌名会绕过白名单。本版从源头与提交前两处堵住：品牌名 / 单词必须逐字来自已确认词典，近似错拼自动纠正，词典外上屏文字阻断出片、不产生厂商费用。
**更新要点**
- 新增 `backend/brand_lexicon.py`：纯函数黄金词典模块。`build_lexicon()` 只从已确认来源（用户 / 落地页 analysis 的 brand / product / CTA / brief.cta）建立词典，facts / 卖点整句一律不进；**明确拒绝采纳 plan.approved_texts / onscreen_texts**，避免被校验对象自我认证。`enforce_onscreen()` 逐字比对，支持大小写不敏感的错拼识别（Novax → NovaX）；`render_lexicon_block()` 编译进出片提示词的强约束块。
- `video_text_guard.py` 收紧批准清单：拆出 `_repair_corpus()`（仅用于截断补全，保留 V4.90 能力），`_approved_texts()` 在传入词典时只返回词典 entries，不再从 facts / sellingPoints 兜底升级为上屏批准文字；新增 `lexicon_enforced` 报告字段。
- 品牌错拼检测与自动纠正：对「打算上屏」的文字追加 `brand_spelling_mismatch` 检查（大小写 miss / 近似 miss），可修复项直接改成词典正确拼写；修复循环改为同字段优先处理可修复项，避免被同字段「未批准」不可修复项抢先处理导致本可自动纠正的错别字被阻断。
- 接入两处链路：`/cw-video/plan`（规划后立即建词典、过审查、词典快照写入 plan）与 `_cw_video_request_build`（出片前以提交时的 plan/analysis 重建词典，不信任前端缓存）；提示词顺序为「提示词契约 → 黄金词典块 → 文字审查块」，把禁绘品牌字样的强约束放在尾部；词典快照随任务 meta 落库可追溯。
**本次优化与更改的功能 / 模块**
- 【新增】品牌 / 文案黄金词典模块与结构化快照，品牌名 / 产品名 / CTA 唯一事实源。
- 【新增】品牌名大小写 / 近似错拼识别与自动纠正（`brand_spelling_mismatch`）。
- 【优化】批准清单收紧：facts / 卖点整句不再自动成为可上屏批准文字；plan 自声明不得自我批准。
- 【优化】视频出片提示词注入黄金词典强约束：禁止绘制品牌名 / 英文单词 / Logo 字样 / 水印 / 端卡。
- 【修复】同字段多问题时优先处理可修复项，品牌错别字可被自动改正而非直接阻断，不再被同字段其他问题抢先处理后放行。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.93。
**影响范围**
- 后端修改：新增 `backend/brand_lexicon.py`；修改 `backend/video_text_guard.py`（批准清单收紧、错拼检测、修复排序、词典参数向后兼容）、`backend/routers.py`（规划与出片两处接入词典、提示词注入、meta 快照）。
- 前端零改动：界面、菜单、布局、字段、按钮、工作流保持不变。
- 数据：无表结构变更；词典随分析即时编译，快照写入 plan 与任务 meta 便于追溯。
- 行为变化（重要）：`approved_only` 模式下，任何不在黄金词典的上屏文字（含错拼品牌名）会被阻断或纠正；默认 `none` 零文字策略下提示词明确禁止绘制品牌字样。V4.90 既有能力（截断补全、乱码阻断、效果化例外、深拷贝不污染）保持不变，未传词典时接口向后兼容。
- 边界：阶段一只覆盖源头词典 + 零文字 + 提交前严格白名单；**播放层文字叠加（用户确认方案）与成片 OCR 复核（云端视觉识图）为后续阶段**，本版未实现。真实付费出片与成片抽检仍属外部验收，不能用模拟测试替代。
**验证**
- 新增测试：`tests/test_brand_lexicon_v493.py` **8/8 通过**（词典只取已确认源、plan 不得自我认证、大小写错拼识别、错拼自动纠正、词典外上屏阻断、截断补全保留、词典块编译、router 两处接入）。
- 全量回归：`tests/run_all.py` **239 项，失败 0 / 错误 0 / 跳过 2**（原 231 + 新增 8）。
- 端到端实测：品牌错拼 `Novax` 自动修正为 `NovaX`（done=1 / 0 阻断 / generation_blocked=False）；词典外文字在 `approved_only` 下判 needs_revision 并阻断；V4.90 专项 10/10 不回退。
- 发版校验：`python3 scripts/prepare_release.py --check` 通过，系统版本 / CHANGELOG / 发布数据均为 V4.93。
- 未验证：真实付费出片、成片 OCR 抽检、品牌方确认未执行；阶段二 / 三（播放层叠加、云端视觉复核）未实现。

## V4.92 创意文案一等化——素材类型多选、按平台规格生成、独立文案工作区

**发布日期**：2026-11-18 11:54
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台 / 创意工作台（文案、图片、视频）、前端任务模块、发版流程、系统版本
**变更摘要**：在创意工作台新增「创意文案」创作环节，与图片、视频并列为一等素材类型。素材类型由单选（图片 / 视频 / 图片和视频）改为多选下拉（文案 / 图片 / 视频），可任意组合（如「图片 + 文案」「文案 + 视频」），按用户选择生成对应内容。点击「确认并批量生成」后，先依据大模型 + 落地页证据生成各平台文案，再生成所选图片 / 视频；文案按各媒体平台专属 schema（字数上限、字段结构）生成并经证据门校验，输出即符合平台文案规则。新增独立「创意文案工作区」，支持查阅、一键复制与下载。
**更新要点**
- 素材类型多选下拉：新增 `materialTypes` 多选状态与自定义下拉组件（勾选 文案 / 图片 / 视频，至少保留一项），逐处重写规划显隐、生成范围、按钮文案与禁用条件、任务进度阶段；默认仍为图片 + 视频，用户主动勾选才生成文案。
- 文案生成解耦：抽出 `buildCopies()` 按平台调用 `api.mediaCopy`（大模型 + 证据门），移除旧「纯图片模式跳过文案」的耦合；新增独立 `generateCopy()` 在批量生成阶段先行执行并写入文案工作区，结果复用给图片叠加，避免同批重复调用文案模型。
- 按平台规格生成：后端 `generate_media_copy` 已按平台选择差异化 schema（Meta primary_text/headline/description/cta、Google RSA headline/description、Unity body 等），每个字段带字数上限，`_validate` 逐字段校验、`audit_copy_fields` 证据门保证数字 / 承诺可追溯。前端完整保留并展示 schema、`char_table`（逐字段字数 vs 上限）、`validation` 与 `ad_product` 细分。
- 独立文案工作区：新增与图片 / 视频并列的文案工作区，逐平台展示文案字段、平台规格合规徽标（✓ 符合 / ⚠ 未完全符合）、ad_product 细分、逐字段字数与超限标红；提供单平台与全部的一键复制（剪贴板 API + 非安全上下文回退）、单平台 TXT 与全部 JSON 下载。
- 任务模块适配：批次 `material_types` 纳入 `copy`；任务抽屉 `KIND_LABEL` 增加「文案」；常驻任务 `kind` 扩展 `copy` / `mixed`，进度阶段增加创意文案；成功判定纳入「任一已选类型有真实产出」。
**本次优化与更改的功能 / 模块**
- 【新增】创意文案作为一等素材类型，与图片 / 视频可自由组合生成。
- 【新增】素材类型多选下拉组件，逐一勾选、即时反馈所选组合。
- 【新增】独立创意文案工作区：查阅、一键复制、单平台 / 全部下载。
- 【优化】文案按各媒体平台规格与规则生成并显式展示合规状态与字数，输出即可投放。
- 【优化】文案生成解耦并复用，避免同一批次重复调用文案模型。
- 【优化】任务模块识别文案类型，进度与产物归类清晰。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.92。
**影响范围**
- 前端修改：`CreativeWorkbench.tsx`（多选下拉、文案生成解耦、文案工作区、复制、成功判定、全部 `materialType` 消费点）、`cwTask.ts`、`CreativeTasksDrawer.tsx`、`styles.css`。
- 后端无逻辑改动：复用现有 `generate_media_copy` / `api.mediaCopy` / 平台 schema / 证据门，仅升版本号。
- 界面：输入框区域「素材类型」由单选下拉改为多选下拉；规划区新增「创意文案规划」说明块；结果区在图片 / 视频工作区之外新增独立「创意文案工作区」。图片 / 视频的布局、卡片、按钮与工作流保持不变。
- 数据：无表结构变更；批次 `material_types` 新增可选 `copy` 值；文案以既有 `copiesByPlatform` 结构承载，新增 `char_table` / `ad_product` 展示字段。
- 行为变化（重要）：勾选文案后，「确认并批量生成」会新增一次逐平台文案生成（真实模型调用）；纯图片叠加模式不再跳过文案生成；未勾选文案时，行为与旧版一致（文案仍作为图片叠加附属在内嵌区展示）。
- 边界：文案的平台规格校验来自后端 schema / `_validate`，属规则层校验；真实投放平台的最终审核、品牌方确认与真实付费生成仍需另行执行。
**验证**
- 新增测试：`tests/test_creative_copy_v492.py` **8/8 通过**（后端按平台差异化 schema 与字数上限、文案入口 async 且接证据门、前端多选下拉 / 文案工作区 / 剪贴板 / 平台规格徽标 / 文案解耦 / 任务模块 copy 类型 / api.mediaCopy）。
- 全量回归：`tests/run_all.py` **231 项，失败 0 / 错误 0 / 跳过 2**（原 223 + 新增 8）。
- 前端类型检查：`npx tsc --noEmit` 0 错误；前端构建：`npm run build` 通过（46 模块）。
- 平台规格实测：Meta 4 字段（primary_text/headline/description/cta）、Google RSA/UAC 2 字段（headline/description）、Unity/TikTok 3 字段（headline/body/cta），每字段均有字数上限。
- 发版校验：`python3 scripts/prepare_release.py --check` 通过，系统版本 / CHANGELOG / 发布数据均为 V4.92。
- 未验证：真实付费文案 / 图片 / 视频生成、真实投放平台审核与品牌方确认未执行，模拟 / 源码契约测试不替代真实结果。

## V4.91 图片内容体检门——拦截纯色 / 无画面素材，不再交付只有颜色的图片

**发布日期**：2026-11-18 09:39
**变更类型**：新增 / 修复 / 优化
**涉及模块**：素材创作平台 / 创意工作台（图片）、图片渲染与归档链路、发版流程、系统版本
**变更摘要**：修复创意工作台偶发产出「纯颜色、无背景、无画面」图片的问题。根因是当文生图模型未配置、超时或返回空时，图片底图回退到本地品牌渐变模板（`_gradient`），而纯图片模式又不叠加任何文字 / Logo / 商品合成，最终产出一张只有渐变的纯色图；该图过去仍以 `status=fallback` 计入 images 并被归档展示。本版在图片落库与返回前新增一道内容体检门，用颜色梯度 / 离散度 / 色数三项指标识别纯色与无画面图，一律拦截为 `needs_attention`，不进入合格素材清单、不导出、不展示。
**更新要点**
- 新增 `backend/image_content_guard.py`：纯函数、只依赖 Pillow 的体检模块，不调模型、不碰数据库、不写文件。把图缩到 64x64 计算相邻像素梯度 `grad`、RGB 标准差均值 `std_mean`、量化色数 `uniq`；当 `grad<1.2 且 std_mean<20 且 uniq<90` 三条件同时满足时判为无画面（blank）。三条件同时满足的设计用于避免误杀「大面积纯色背景但有主体 / 文字」的真实素材。
- 阈值经多类样本实测校准：纯色 `grad=0`、品牌渐变兜底 `grad=0.48`、浅渐变 `grad=0.3`、近纯色微噪 `grad=0.07` 均判为拦截；白底产品 `grad=3.08`、真实场景 `grad=5.9`、纯色+大字 `grad=17.2` 均放行。
- 接入 `generate_media_images` 的 `_render_one`：渲染成功后对成品 PNG 做一次只读体检（不重试、不重发已计费的模型调用）。纯色图转为 `needs_attention` 进入 skipped，附 `content_check` 报告（指标、阈值、原因）；合格图附加 `content_check` 快照随资产归档。
- 汇总与提示：新增 `blank_rejected_count` 统计与 note 文案，明确告知用户有多少张因纯色被拦截，并提示检查文生图是否正常返回实景底图；整批若全部被拦截则 `status=failed`、`count=0`，不再出现「看似成功」的纯色素材。
- 容错：体检模块自身异常、文件缺失或损坏时一律 fail-open（放行并在 reason 注明），绝不因体检 bug 阻断正常出图。
**本次优化与更改的功能 / 模块**
- 【新增】图片内容体检门与结构化报告，覆盖 AI 返回纯色图与本地渐变兜底两条产生路径。
- 【修复】无文生图底图时的纯色渐变图不再作为合格素材交付 / 归档 / 导出。
- 【优化】纯色拦截独立计数与中文提示，便于用户定位「图片为何变少」并修正模型配置。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.91。
**影响范围**
- 后端修改：`image_content_guard.py`（新增）、`media_ad.py`、`version.py`；新增测试 `tests/test_image_content_guard_v491.py`。
- 前端无改动；菜单、布局、按钮、表单、字段、创作步骤与请求参数均不变。
- 数据：无表结构变更；只在 skipped / images 的 JSON 中增加 `content_check` 字段，`image_model` 增加 `blank_rejected_count` 计数。
- 行为变化（重要）：纯色 / 无画面图将不再出现在素材库与导出包中；未配置文生图模型时，纯图片模式会因无实景底图而返回失败 + 明确原因（而非一张渐变纯色图）。叠加模式若底图为纯色同样被拦截；有真实内容的底图不受影响。
- 边界：本版是成品图内容体检，不能替代真实模型出片质量判断与品牌审核；真实付费出片、成片抽检与投放效果验证仍需另行执行。
**验证**
- 新增测试：`tests/test_image_content_guard_v491.py` **6/6 通过**（纯色 / 渐变 / 微噪拦截、真实内容不误杀、异常 fail-open、端到端拦截与放行）。
- 全量回归：`tests/run_all.py` **223 项，失败 0 / 错误 0 / 跳过 2**（原 217 + 新增 6）。
- 语法检查：`image_content_guard.py`、`media_ad.py` 均通过 `py_compile`。
- 端到端验证：无模型走渐变兜底时 `status=failed / count=0 / blank_rejected_count=1` 且原因为纯色；有内容底图时 `status=ok / count=1 / ai_background=True`，不误杀。
- 发版校验：`python3 scripts/prepare_release.py --check` 通过，系统版本 / CHANGELOG / 发布数据均为 V4.91。
- 未验证：真实付费出片、成片抽检与品牌审核未执行，模拟 / 纯函数测试不替代真实结果。

## V4.90 视频文字预检门——提交前审查、纠正并阻断错误文字

**发布日期**：2026-11-17 16:58
**变更类型**：新增 / 优化
**涉及模块**：后端接口、素材创作平台 / 创意工作台（视频）、提示词契约层、发版流程、系统版本
**变更摘要**：针对视频生成时画面里可能出现错误文字、不完整文字、乱码或看不清文字的问题，新增独立的视频文字审查层。审查覆盖分镜字幕、CTA、钩子、VO、画面描述中的引号文字和补充要求中的引号文字；在提交厂商前完成文本形态校验、批准文案白名单校验、保守纠正与不可修复阻断。默认仍沿用 V4.88 的严格无字策略；只有显式 `text_policy=approved_only` + `approved_texts` 时才允许批准文字逐字出现，效果化处理仅放宽可读性，不放宽正确性、完整性和批准清单要求。
**更新要点**
- 新增 `backend/video_text_guard.py`：纯函数审查模块，不改界面、不调模型、不碰数据库。可识别截断符号、乱码 / 控制字符、重复标点、括号引号不成对、超长不可读文案，以及不在批准清单中的上屏文字。
- 保守纠正：对可确定错误自动修正——去零宽字符 / 合并空白、按批准文案补全半截句、折叠重复标点、去掉不成对尾标点、按批准清单纠偏近似文字；同一字段只按最高优先级问题修正一次，避免多次修正互相覆盖。修正使用深拷贝，不污染原始分镜。
- 不可修复则阻断：乱码、无批准来源、超长不可读文字等修不掉的问题写入 `text_guard` 报告并标记 `generation_blocked`；异步提交返回 422，同步链路返回 `TEXT_GUARD_BLOCKED`，均不调用视频厂商、不产生费用。
- 接入 `/cw-video/plan` 与 `/cw-video/generate-jobs`：规划阶段修正后重跑证据审计，出片构建阶段再次审查，防止前端绕过规划接口直接提交问题文案。审查报告写入分镜、任务 meta 与提示词，可追溯字段、原因、修正次数和批准清单。
- 提示词契约增强：`build_prompt_contract()` 增加 `text_policy` / `approved_texts` 支持；默认渲染严格无字契约，`approved_only` 渲染受控文字例外，明确只有清单内文字可逐字出现、不得改写缩略或截断。
- 英文规划系统提示词同步补充文字纪律：hook / cta / text / vo 必须完整可读；需要上屏文字必须在 `approved_texts` 中逐字列出并标记 `text_effect` 或 `motion_graphics`。
**本次优化与更改的功能 / 模块**
- 【新增】视频文字 / 文案预检模块与结构化审查报告，覆盖可能进入画面的全部文字来源。
- 【新增】批准文案白名单与受控文字例外，默认无字策略保持不变。
- 【优化】可确定错误自动纠正，乱码 / 无来源 / 不可读等硬问题在付费前阻断。
- 【优化】文字审查报告随分镜、任务 meta 和出片提示词落库，便于定位问题字段与修正过程。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.90。
**影响范围**
- 后端修改：`video_text_guard.py`（新增）、`routers.py`、`schemas.py`、`prompt_contract.py`、`version.py`；新增测试 `tests/test_video_text_guard_v490.py`。
- 前端无改动；菜单、布局、按钮、表单、字段、创作步骤与请求参数均不变。现有 `text` / `cta` / `vo` 字段继续保留为策划与 VO 用途。
- 数据：无表结构变更；只在既有 plan / meta_json 中增加 `text_guard` / `text_repair_count` / `text_guard_status` 等 JSON 字段。
- 行为变化（重要）：带截断、乱码、不可读或未批准上屏文字的分镜将在提交出片前被修正或拦截；默认仍不出上屏文字。`approved_only` 是后端 / JSON 级能力，不新增前端开关。
- 边界：本版是提示词与文案形态预检，不能替代真实模型成片抽检；品牌方审核、OCR 成片复核与真实投放效果验证仍需另行执行。
**验证**
- 新增测试：`tests/test_video_text_guard_v490.py` **10/10 通过**（截断补全、乱码阻断、超长与效果化例外、批准清单、引号文字、深拷贝、提示词渲染、契约例外）。
- 全量回归：`tests/run_all.py` **217 项，失败 0 / 错误 0 / 跳过 2**（原 207 + 新增 10）。
- 语法检查：`video_text_guard.py`、`prompt_contract.py`、`routers.py`、`schemas.py` 均通过 `py_compile`。
- 发版校验：`python3 scripts/prepare_release.py --check` 通过，系统版本 / CHANGELOG / 发布数据均为 V4.90。
- 未验证：真实付费出片、成片 OCR 抽检、品牌审核与投放效果验证均未执行，模拟 / 纯函数测试不替代真实结果。

## V4.89 最小界面提示校准——让界面说明与无字满版出片行为一致

**发布日期**：2026-11-17 16:52
**变更类型**：优化
**涉及模块**：素材创作平台 / 创意工作台（图片、视频）、前端提示文案、发版流程、系统版本
**变更摘要**：承接 V4.88 的提示词契约增强，对创意工作台中 4 处容易与实际出片行为产生歧义的界面文案做最小校准。纯图片模式现在明确说明“无字、无按钮、无 Logo、满版真实场景且无预留空白”；图片+文字与图片+文字+按钮模式说明保留文案区并叠加文字/按钮；品牌 Logo 注入说明区分“图片叠加模式合成 Logo”与“视频仅作品牌主体参考”；视频规划提示与分镜标签明确字幕稿 / CTA 仅用于策划和旁白，不绘制进画面。本版不新增组件、不改布局、不改按钮位置、不改字段、不改工作流、不改 API。
**更新要点**
- `CreativeWorkbench.tsx` 的「素材图片选择」提示按当前 `overlayMode` 显示准确说明，避免纯图片模式仍让用户以为会预留文案区。
- `CreativeWorkbench.tsx` 的 Logo 注入说明改为：图片叠加模式会合成 Logo；视频仅作品牌主体参考，不叠加 Logo 图层。
- `VideoStudio.tsx` 的视频规划总提示补充：字幕稿 / CTA 仅用于策划与旁白，不绘制进画面。
- `VideoStudio.tsx` 的分镜字段标签由「字幕」改为「字幕稿」，避免被理解为成片上屏字幕。
**本次优化与更改的功能 / 模块**
- 【优化】纯图片 / 文字叠加 / 文字按钮三种模式的界面说明与实际生成行为保持一致。
- 【优化】品牌 Logo 注入说明区分图片与视频，避免用户误以为视频会叠加 Logo 图层。
- 【优化】视频分镜的字幕字段语义明确为策划稿，降低与 V4.88 无字出片策略的理解冲突。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.89。
**影响范围**
- 前端仅修改：`frontend/src/pages/CreativeWorkbench.tsx`、`frontend/src/pages/VideoStudio.tsx`，且只改 JSX 文案与一个动态提示表达式。
- 无新增组件、无新增表单、无新增菜单、无 CSS 改动、无状态字段改动；布局、按钮位置、交互步骤与 API 请求保持不变。
- 后端、数据库、任务状态、提示词契约、素材标准库与交付判定均未改动；不改变已生成素材，也不追溯修改历史任务。
- 本版属于界面说明校准，不改变 V4.88 已建立的真实出片、品牌审核与投放效果验证边界。
**验证**
- 前端类型检查：`npx tsc --noEmit` 0 错误。
- 前端构建：`npm run build` 通过，46 个模块转换完成。
- 全量回归：`tests/run_all.py` **207 项，失败 0 / 错误 0 / 跳过 2**。
- 发版校验：`python3 scripts/prepare_release.py --check` 通过，系统版本 / CHANGELOG / 发布数据均为 V4.89。
- 改动范围复核：仅 2 个前端页面文件的用户可见文案发生变化，无组件、布局、API 或数据变更。

## V4.88 提示词契约接入——文档级无字满版规则进入生成链路，界面与流程保持不变

**发布日期**：2026-11-17 16:40
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台 / 创意工作台（图片、视频）、提示词契约层、媒体素材规格标准库、后端生成与任务元数据、回归测试、发版流程、系统版本
**变更摘要**：依据《全球主流媒体图片与视频推广提示词体系及品牌级验收规范》1.0，在不改变现有界面布局、菜单和创作步骤的前提下，把文档的结构化字段、行业/人群/素材类型词表、GLOBAL-VISUAL-1 无字满版约束和图片/视频主模板接入后端提示词编译。纯图片模式与所有视频出片提示词现在使用同一份 PromptContract：删除旧模板中的“为文案留白”指令，视频分镜的字幕/CTA/Logo 字段只保留在分镜 JSON 供节奏与 VO 策划，不再绘制进画面；图片任务矩阵与提示词同时读取素材标准库，未登记尺寸明确标注为“标准库未登记 / 待确认”，不冒充官方硬规则。
**更新要点**
- 新增 `backend/prompt_contract.py`：维护 I00–I12 / A00–A10 / T01–T10 内部映射、`GLOBAL-VISUAL-1`、图片无字主模板、视频无字主模板、负向约束与结构化 PromptContract；`prompt_id` 由媒体、分类、产品事实、证据与版位确定性生成，便于追溯。
- 图片链路 `media_ad.py`：纯图片模式主动剔除旧模板中的 negative space / copy space 指令，再追加无字满版契约；叠加文字/按钮模式保留旧排版行为，只追加“不伪造 UI、不用蒙版遮缺陷、不篡改商品”底线。提示词契约随图片资产 meta 落库。
- `image_capabilities.composition_goal()`：新增 `overlay_mode` 分支。纯图片输出 full-bleed 构图目标；叠加模式保留原有主体保护 + 文案区策略。
- `media_spec_library.py`：补齐 `image_targets()` / `image_target_for_size()`，与 `video_target()` 对称；图片生成优先使用标准库尺寸作兜底，并按实际尺寸标注核验级别 A/B/C 或“标准库未登记”，不改变用户已选尺寸。
- 视频链路 `routers.py`：`_cw_video_request_build()` 注入视频契约块；出片提示词不再拼接 `shot.text`，品牌 Logo 只作主体一致性参考，不生成图形 Logo / 文字端卡；契约快照写入 `meta`，随任务持久化。
- 分镜系统提示词补充说明：text / cta 字段仍按原 JSON 结构输出，但仅用于内部节奏、VO 与策划追溯，避免前端字段与出片行为相互矛盾。
- 新增 `tests/test_prompt_contract_v488.py` 7 项：词表映射、契约快照、纯图片无字、叠加模式兼容、构图目标分支、视频字幕隔离、图片标准库共享。
**本次优化与更改的功能 / 模块**
- 【新增】文档提示词契约层与 I/A/T 内部映射，不新增用户下拉或表单。
- 【新增】图片任务矩阵与提示词共用素材标准库，未登记规则明确降级标注。
- 【新增】纯图片与视频出片共用无字满版视觉契约，提示词不再一边要求留白一边要求满版。
- 【优化】视频字幕 / CTA / Logo 字段语义收敛为策划与 VO 参考，保留分镜 JSON 与界面展示不变。
- 【优化】提示词契约随资产 / 任务元数据落库，形成可追溯的 prompt_id 与版本快照。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.88。
**影响范围**
- 后端新增：`prompt_contract.py`；修改：`media_ad.py`、`image_capabilities.py`、`media_spec_library.py`、`routers.py`、`version.py`。
- 前端：无改动；菜单、布局、按钮、创作步骤与提示词管理页均保持原样。
- 数据：无表结构变更；只在 `GenerationJob.request_json` / `CreativeAsset.meta_json` 的既有 JSON 中增加契约快照字段。
- 行为变化（重要）：默认“纯图片”不再接收“预留文案区”类提示词；视频成片提示词不再把分镜字幕绘制进画面。文字 / 按钮叠加模式仍保留旧行为，只是底图生成不再自行发明文字或假 UI。
- 边界：文档中的 90 分评分、90% 画面覆盖、主体包围框 35%–70% 等属于内部制作建议，本版未做自动硬门；图片标准库未登记的尺寸不阻断生成，只标注待确认。
- 纪律：本版是提示词与规格联动优化，不宣称已通过真实模型出片评测、品牌方审核或投放效果验证。
**验证**
- 新增测试：`tests/test_prompt_contract_v488.py` **7/7 通过**（词表映射、契约字段、纯图片无字、叠加模式保留、构图分支、视频字幕隔离、图片标准库共享）。
- 全量回归：`tests/run_all.py` **207 项，失败 0 / 错误 0 / 跳过 2**（原 200 + 新增 7）。
- 语法检查：`prompt_contract.py`、`media_spec_library.py`、`media_ad.py`、`image_capabilities.py`、`routers.py` 均通过 `py_compile`。
- 边界检查：纯图片提示词不再包含 `negative space` / `keep generous clean`；叠加模式仍保留图内文案策略；`image_target_for_size("Meta","999x999")` 返回 None，不伪造核验规则。
- 未验证：真实付费出片、品牌审核与投放效果验证仍需在部署机 / 真实账户单独执行，本次模拟测试不替代真实生成结果。
- 待确认：本版只改变提示词编译与元数据标注，不改变交付状态判定；后续如需把 OCR / 商品外观比对升级为硬门，应先建立固定样本与人工校准阈值。

## V4.87 落地页分析 502 修复——抓取加约束不拖垮服务，网关错误页转成可读提示

**发布日期**：2026-11-17 14:20
**变更类型**：修复 / 新增 / 优化
**涉及模块**：素材创作平台 / 创意工作台（落地页分析）、后端抓取与证据链、前端 API 错误处理（系统设置相关接口共用层）、部署文档（DEPLOY.md）、发版流程、系统版本
**变更摘要**：修复「创意工作台分析网址落地页报 502 Bad Gateway」的问题。经排查，502 是宿主 nginx（`nginx/1.31.5`，非容器内 `nginx:alpine`）返回，说明网关没能从后端拿到有效响应。根因有两层：一、后端 `fetch_page` 抓取任意网址时 `r.text` 无大小上限、无内容类型判断、解析在事件循环里同步执行——遇到大文件直链或图片/PDF/视频链接会把单 uvicorn worker 的内存吃满或长时间阻塞，进程重启 / 连接被重置后 nginx 就返回 502；二、前端把 nginx 的原始 HTML 错误页（含 padding 注释）整段塞进提示，用户看到一大坨乱码，无法判断原因。本次对抓取加响应体上限（8MB）、文本型 content-type 白名单、分层超时、流式读取、scheme 白名单，并把 CPU 密集的解析 / 证据包构造 / 提示词拼装移出事件循环；前端将网关 HTML 错误页转成按状态码分类的中文诊断提示。同时在 DEPLOY.md 补充 502/504 的分层排查表与宿主反代建议配置。
**更新要点**
- `services.fetch_page`：新增 `MAX_FETCH_BYTES=8MB` / `MAX_REDIRECTS=5` / 分层 `httpx.Timeout`（connect 5s、read 12s、write 5s、pool 5s）；流式读取 `aiter_bytes` 超限即停；只接受 `text/html` 等文本型 content-type，图片/PDF/视频等非网页内容直接判 `unsupported_content_type`；新增 `unsupported_scheme`（仅 http/https）。失败原因可按 `fetch_quality` 分类。
- CPU 密集操作移出事件循环：`parse_page_meta` + 正则清洗 → `asyncio.to_thread(_parse_fetched_html)`；`build_evidence_pack` → `asyncio.to_thread`；`build_landing_prompt` 提示词拼装 → `evidence_prompt_part_async`。大页面解析不再卡住整个 worker。
- `fetch_product`：只有 `ok` / `thin_content` 两种质量送模型；`too_large` / `unsupported_content_type` / `unsupported_scheme` / `fetch_failed` 一律判失败，交给路由给明确的 422 提示（不再把半截内容或二进制乱码当产品事实）。
- 路由 `/cw/analyze`：按 `fetch_quality` 给出可操作的中文提示（超 8MB / 非网页内容 / 仅支持 http），不再笼统说"链接不可达"。
- 前端 `api.ts` / `req()`：识别 nginx / Cloudflare 的 HTML 错误页（`<html>` 或 `<title>` 含 502/503/504），转成「服务暂时不可用（502 · 网关）：网关无法连接后端服务，请稍后重试」这类可读提示；JSON 错误与业务校验错误的处理保持不变。
- 【合并远端】视频任务重启恢复不再误杀：`job_service.recover_interrupted()` 只回收 `kind=images` 的中断任务，视频任务交由 `creative_tasks` 持久化 worker 按供应商任务号续查（重启不再误标 failed、不重复提交收费）；`creative_tasks.retry(repoll)` 记录 `request_json.repoll_at`，业务期限从重查时刻起算，历史任务续查不再被误判 POLL_TIMEOUT。对应测试 `test_d4_d5_d6` 更新为 images kind 并新增视频不误杀断言。
- `DEPLOY.md` 新增 6.2 节：502/504 按网关版本与状态码的排查表、宿主 nginx 建议配置（`proxy_read_timeout 180s`、`proxy_buffering off`），并明确容器内 nginx 已设 660s、无需修改，报错页带版本号说明是宿主 nginx 在拦。
**本次优化与更改的功能 / 模块**
- 【修复】落地页分析抓取无上限导致的 worker 被拖垮 / OOM → 网关 502：加体大小上限、内容类型白名单、流式读取、分层超时。
- 【修复】CPU 密集解析阻塞异步事件循环：解析 / 证据包 / 提示词拼装移入线程池。
- 【优化】网关 HTML 错误页前端可读化，失败原因按状态码分类。
- 【优化】失败抓取给出分类提示（过大 / 非网页 / scheme 不支持），便于用户自助修正输入。
- 【新增】`tests/test_fetch_robustness.py` 7/7（正常解析、二进制拒绝、超限截断、跳转、scheme 拦截、fetch_product 阻断、上限合理性）。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.87。
**影响范围**
- 后端：`services.py`（fetch_page 重写 + 线程解析）、`fetchers.py`（线程证据包 + 质量判定 + async 提示词）、`routers.py`（import + await + 422 分类提示）。
- 前端：`api.ts`（req 的 HTML 错误页识别）；不改页面布局、按钮或导航。
- 文档：`DEPLOY.md`（6.2 排查节）。
- 数据：无表结构变更。
- 行为变化（重要）：抓取正文上限 8MB、单页读超时 12s、仅文本型内容可分析；此前能"分析"的图片/PDF/超大文件链接现在会给明确的失败提示（这些本就不是落地页）。正常落地页（HTML、正文 <8MB）行为不变。
- 边界：本修复针对后端健壮性与错误可读性；宿主 nginx 的 `proxy_read_timeout` 属部署配置，代码无法修改，需按 DEPLOY.md 6.2 由运维调整——即便如此，V4.87 后分析链路本身已显著缩短（抓取最长约 26s + 推理 90s）。
- 纪律边界：502 可能与目标网站自身不可用或部署环境资源有关；本轮无法访问用户生产环境日志确认具体一次 502 的根因，修复基于代码级确定性风险与报错页特征推断。
**验证**
- 新增测试：`tests/test_fetch_robustness.py` **7/7 通过**；既有 `tests/test_cw.py`（落地页分析主链路）全绿。
- 回归未退化：`tests/run_all.py` **199 项，失败 0 / 错误 0 / 跳过 2**（原 192 + 新增 7）。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 冒烟：`file://` scheme 被拦、不可达地址正确分类为 `fetch_failed`，均不抛异常到路由层。
- 四种状态：代码已实现 ✅、模拟测试通过 ✅、真实生产环境 502 复现验证 ❌、真实付费出片 ❌；本轮无可访问的生产日志，未在用户部署机上复现确认。
- 待确认：若用户生产机在 V4.87 后仍对正常落地页报 502，请按 `docker compose logs --tail=200 backend` 查是否有 OOM / 异常堆栈，并按 DEPLOY.md 6.2 调整宿主反代；前端提示会显示具体状态码便于判断。

## V4.86 日志模块补齐登出记录与真实统计——登录/登出均有账号、IP、时间，标题不再随搜索乱跳

**发布日期**：2026-11-17 12:00
**变更类型**：修复 / 新增
**涉及模块**：素材创作平台 / 系统设置（日志模块）、账号认证（登录/登出）、后端接口与数据模型、数据库迁移、前端与菜单、发版流程、系统版本（注：本次仅改动 routers.py 的认证与日志路由，未涉及大模型配置功能）
**变更摘要**：优化「系统设置 → 日志」模块。一、把**用户登出**作为正式日志记录：新增 `POST /api/auth/logout`，前端退出时先调用服务端（此时 token 仍在，可解析当前用户），把 username、来源 IP、时间写入登录/登出日志；写库失败不阻断本地退出。二、**修复日志统计问题**：此前日志页标题的「N 条」用的是前端已加载且被搜索过滤后的数组长度，切换 limit、输入关键词都会让总数随意变化，还可能把 1000 条上限误当总数。新增 `GET /api/log-stats` 返回全表真实口径（审计总数、账号事件总数、登录/登出次数、成功/失败次数），标题改用它，并把「当前筛选显示 X 条」与总数分开标注；不再用已加载列表冒充总数。三、登录/登出日志新增事件类型区分与筛选，搜索支持「登录 / 登出」。
**更新要点**
- `LoginLog` 新增 `action` 字段（login / logout），由 `migrations.ensure_schema` 自动补列，默认 `login`，历史数据语义不变。
- `_log_login()` 支持 `action` 参数；登录写 `action=login`，登出写 `action=logout`；两类都记 username / IP（X-Forwarded-For 优先）/ 时间 / user-agent，异常不阻断主流程。
- 新增 `POST /api/auth/logout`：需鉴权，无法确认用户时 401；仅记录会话终止事件，不尝试使 JWT 失效（JWT 无服务端状态）。
- 新增 `GET /api/log-stats`：仅管理员可见，返回 `{audit_total, login_total, login_success, login_fail, login_count, logout_count}`，与列表 limit / 前端搜索完全无关。
- `GET /api/login-logs` 新增 `action` 过滤（login / logout）并返回 action 字段，兼容旧数据缺省。
- 前端 `api.logout()` / `api.logStats()` / `LoginLog.action` / `LogStats` 接入；登出先发请求再清 token，失败静默；新增登出/统计单元测试 7 项。
- 日志页标题改为后端真实总数，并在被筛选时另显示「当前筛选显示 X 条」；登录日志表新增事件类型列显（登录成功 / 登录失败 / 登出）与「全部事件 / 仅登录 / 仅登出」筛选。
**本次优化与更改的功能 / 模块**
- 【修复】日志统计口径：标题总数不再受 limit 与搜索影响，改由 `/api/log-stats` 全表统计提供。
- 【新增】登出审计：登录与登出均形成可追溯记录，含账号名称、IP 地址、时间。
- 【新增】登录/登出事件类型筛选与中英文搜索；保留原有审计/登录双页签与布局。
- 【新增】`tests/test_logout_and_stats.py` 7/7（登出落库、鉴权、action 过滤、统计全表口径、失败计数、管理员门禁）。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.86。
**影响范围**
- 后端：`models.py`（LoginLog.action）、`routers.py`（登出接口、action 过滤、log-stats）、`migrations.py`（自动迁移，无需手动改库）。
- 前端：`api.ts`（类型与方法）、`App.tsx`（登出调用）、`pages/Logs.tsx`（统计口径与事件类型展示）；未改导航与页面布局，仅在筛选区多一个「事件类型」下拉。
- 数据：`login_logs` 新增 `action` 列（默认 `login`），旧记录自动兼容；不删列、不改既有语义。
- 行为变化（重要）：退出登录会多一条服务端请求与一条审计记录；日志标题的「共 N 条」现在是全表总数（可能与"最近 100/1000 条"的显示条数不同，页面会明确标注当前显示数）。
- 纪律边界：登出记录是会话终止审计，不代表 JWT 被服务端强制失效；统计为数据库口径，不等于真实去重人数。
**验证**
- 新增测试：`tests/test_logout_and_stats.py` **7/7 通过**；既有 `tests/test_login_logs.py` 5/5 通过。
- 回归未退化：`tests/run_all.py` **192 项，失败 0 / 错误 0 / 跳过 2**（原 185 + 新增 7）。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过（gzip 后 JS 93.82 kB / CSS 19.77 kB）。
- 迁移验证：`ensure_schema` 对旧库自动补 `login_logs.action`，测试环境临时库从零建表与既有测试均通过。
- 四种状态：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌；本轮不涉及付费出片。
- 待确认：生产库首次升级时迁移会自动补列；如部署环境禁用自动迁移，需手动执行 `ALTER TABLE login_logs ADD COLUMN action VARCHAR(16) DEFAULT 'login'`。

## V4.85 视频任务轮询不再带异步头——提交请求头与查询请求头彻底分离

**发布日期**：2026-11-17 11:40
**变更类型**：修复 / 新增
**涉及模块**：素材创作平台 / 创意工作台（视频生成与任务拉取）、大模型配置 / 视频供应商协议层（ModelVideo）、创作任务后台 worker、发版流程、系统版本
**变更摘要**：修复「提交视频生成后，拉取任务（轮询）时不需要请求头 `X-DashScope-Async`」的问题。此前 `ModelVideo.poll_job()` 直接复用提交时的 `request["headers"]`，而提交头由 `_headers()` 生成并含 `X-DashScope-Async: enable`——该头仅百炼 MaaS「提交」阶段必需（用于触发异步任务），查询任务接口（GET `{base_url}/api/v1/tasks/{task_id}`）携带它会被部分网关判为 400/403，导致长轮询拿不到任务状态。本次把「提交头」与「轮询头」在请求冻结时分叉：提交照旧带异步头，查询头剔除该头；并对 worker 重启后读到的旧任务快照做防御性剔除，保证任何来源的续查都不带异步头。提交行为与异步头的配置开关（`async_header`）完全不变，仅影响查询阶段。
**更新要点**
- `plan_request()` 冻结请求形态时，从提交头派生一份 `poll_headers`（去掉 `X-DashScope-Async`），与 `headers` 一并写入冻结请求；两份字典相互独立。
- `poll_job()` 改用 `poll_headers` 发起 GET；若任务快照缺该字段（worker 重启读旧任务），从 `headers` 现场剔除异步头兜底，不留兼容缺口。
- 提交链路 `submit_job()` 仍用 `headers`（含异步头），`async_header` 开关语义（true/1/yes 才附加）保持不变。
- `KlingVideo` 与连通测试 `_test_generic_video` 不受影响：前者 `_headers()` 从不含该头，后者只提交、不轮询。
**本次优化与更改的功能 / 模块**
- 【修复】`providers.py` / `ModelVideo.plan_request()`：冻结请求新增 `poll_headers`（无异步头），提交头保持原样。
- 【修复】`providers.py` / `ModelVideo.poll_job()`：GET 查询改用轮询头，并对旧快照防御性剔除 `X-DashScope-Async`。
- 【新增】专项验收 `scripts/check_poll_header_v485.py` 9/9（提交含头 / 轮询无头 / 旧快照兜底 / 开关未开时两处都无头）。
- 【优化】系统版本 / 版本更新：系统版本升至 V4.85。
**影响范围**
- 后端：仅 `providers.py` 的 `ModelVideo`（dashscope_maas 与 generic 两族）请求冻结与轮询两处；不改 `submit_job`、`generate`、`_body`、`_headers` 的既有行为。
- 任务数据：`plan_request` 返回的冻结请求新增可选字段 `poll_headers`；旧任务快照无此字段时由 `poll_job` 现场剔除兜底，无需迁移、不影响读取。
- 前端：无改动，无需改界面或按钮。
- 行为变化（重要）：只在视频任务「查询阶段」少带一个请求头；提交、鉴权、成片下载、时长与规格交付门、任务状态机全部不变。
- 纪律边界：本修复针对确定性的请求头语义错误（异步头只用于提交），不引入新配置、不改变厂商协议契约。
**验证**
- 专项验收：`python3 scripts/check_poll_header_v485.py` **9/9 通过**（C1 冻结头分离、C2 真实 POST 含头、C3 真实 GET 无头且拿到 SUCCEEDED、C4 旧快照兜底、C5 开关未开两处都无头）。
- 回归未退化：`check_video_pipeline_p0.py` 19/19、`check_video_p0_api.py` 8/8、`check_video_p1.py` 14/14、`check_creative_tasks.py` 23/23、`check_video_claims.py` 16/16、`check_video_v483.py` 14/14、`check_media_spec_library.py` 31/31；`tests/run_all.py` **185 项，失败 0 / 错误 0 / 跳过 2**。
- 质量：`python3 -m py_compile backend/providers.py` 通过；后端全量回归实际执行通过。
- 界面约束：无前端改动，界面布局、按钮、一级/二级导航均不变。
- 四种状态：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌；本轮未发起付费出片。
- 待确认：真实百炼环境下查询接口对该头的容忍度因 Key/网关而异，本修复按「查询不该带异步头」的确定性语义收紧；如需在白名单部署机补真实付费出片证据，运行 `python3 scripts/verify_real_video_once.py --yes`。

## V4.84 媒体素材规格标准库——展示与生成共用一份官方核验规则，新增「素材标准库」二级菜单

**发布日期**：2026-11-17 11:15
**变更类型**：新增 / 优化
**涉及模块**：素材创作平台 / 媒体素材规格（新建标准库）、创意工作台（视频请求 / 交付复核）、创作任务后台 worker、创意工作台导航（新增二级菜单「素材标准库」）、媒体规范 API、大模型配置（视频请求规格引用）、发版流程、系统版本
**变更摘要**：按《创意工作台状态一致性与主流媒体素材规格诊断实施方案》第五至十四节，联网复核了 Meta、Google、Unity、AppLovin、Mintegral、TikTok、Moloco、Adsterra 八平台的官方帮助文档（2026-11-17）。核验结果与文档逐条对照：Google App 图片 1:1/1.91:1/4:5、Unity 视频 ≤60s+端卡、AppLovin Advertise 9:16≤1GB 与 oRTB 5–30s 分入口、Mintegral icon 512/主图 1200x627/视频 200MB 与旧 API 50MB 冲突、TikTok In-Feed 三比例≤10 分钟、Moloco 普通视频 6–180s 与 Native 6–100s 分规则、Adsterra Native 320x240 原文比例自相矛盾、Meta 官方页仍受限——全部一致。此前图片目录 `media_platforms.py` 只有版位/尺寸、视频链路完全不查规格，展示与生成各写一套数字，无法统一纠错。本次新建唯一标准库，让展示与生成都引用同一份带来源、核验日期与 A/B/C 分级的规则，并新增「素材标准库」二级菜单供查阅核对。
**更新要点**
- 新建 `backend/media_spec_library.py`：44 条逐广告产品规则，覆盖 8 平台图片与视频；每条带 `verification`（A 官方已核验 / B 内部制作基准 / C 受限待确认）、`source_url`、`verified_on`，未知项一律 None，不编造最大值
- 联网核验纪律：A 级必须带官方来源与核验日期（Google/Unity/AppLovin/Mintegral/TikTok/Moloco/Adsterra 官方页）；Meta 受限保持 B 级、Adsterra 视频能力与 Mintegral 旧 API 容量保持 C 级，不冒充官方硬规则
- 生成前冻结：`_cw_video_request_build` 调用 `video_target()` 解析目标比例/尺寸/时长区间/伴随素材/核验状态，写入请求 `meta.spec_ref` 随任务落库，同步与后台链路共用
- 交付时复核：即时链路与持久 worker 都用 `validate_video_delivery()` 按冻结 spec 与实测值复核；仅 A 级越界升级为 `SPEC_MISMATCH` / `needs_attention`，B/C 级只提示不改结论，避免把内部基准当硬规则
- 图片目录对账：`reconcile_image_catalog()` 以标准库为准找出展示目录缺失尺寸，防止只改一侧造成漂移
- 新增 `GET /api/media-spec-library`：标准库快照端点（需鉴权），供菜单页与导出统一查询
- 新增二级菜单「素材标准库」（创意工作台分组，编辑角色可见）：只读查阅页，支持平台/图片视频/核验级别筛选与搜索，展示尺寸、比例、格式、大小、时长、伴随素材、来源链接与核验日期；不改任何现有页面布局或按钮
**本次优化与更改的功能 / 模块**
- 【新增】`media_spec_library.py` 媒体素材规格标准库（单一事实来源，44 条规则 / 8 平台 / A-B-C 分级）
- 【新增】`video_target()` / `validate_video_delivery()` / `reconcile_image_catalog()` / `library_payload()` 标准库查询与联动 API
- 【新增】`GET /api/media-spec-library` 与前端 `api.mediaSpecLibrary()`
- 【新增】创意工作台二级菜单「素材标准库」与只读页面 `SpecLibrary.tsx`
- 【优化】视频生成请求与结果新增 `spec_ref` / `spec_check` 字段（向后兼容，旧任务缺省值不影响读取）
- 【优化】新增交付错误码 `SPEC_MISMATCH` 与阶段标签「规格未达标」，原片保留可下载
- 【优化】专项验收 `scripts/check_media_spec_library.py` 31/31、接口测试 `tests/test_media_spec_library.py` 4/4
- 【优化】系统版本 / 版本更新：系统版本升至 V4.84
**影响范围**
- 后端：新增 `media_spec_library.py`；`routers.py`（新端点 + 视频请求冻结 spec + 交付复核 + schema 字段）、`creative_tasks.py`（worker 交付复核 + spec 落库 + 视图字段）、`schemas.py`（结果新增可选字段）。
- 前端：新增 `pages/SpecLibrary.tsx`；`App.tsx`（Tab / 菜单 / 权限 / 挂载）、`api.ts`（新端点方法）、`useCreativeTasks.ts`、`CreativeTasksDrawer.tsx`、`styles.css`（均新增可选字段，不改布局）。
- 数据：不新增表、不改列；`meta_json` / `result_json` 新增 `spec_ref` / `spec_check` 可选字段，旧任务读取缺省兼容。
- 行为变化（重要）：选 Moloco 出 5s 竖片这类「官方规格越界」现在会在结果里明确标规格不符（原片仍保留）；Meta 等 B/C 级规则只作提示，不会误判成不合格。
- 纪律边界：标准库是代码级规则库，非规格管理界面；未知/受限字段留空标注，不自动判定合规；技术规格通过不等于广告审核通过或转化提升。
**验证**
- 标准库专项：`python3 scripts/check_media_spec_library.py` **31/31 通过**（结构与 A/B/C 纪律、逐平台与文档一致、video_target 三态、交付复核、目录对账、生成链路引用点）。
- 接口测试：`tests/test_media_spec_library.py` **4/4 通过**（鉴权、库结构、A 级必带来源、生成与展示同源）。
- 回归未退化：`check_video_v483.py` 14/14、`check_video_pipeline_p0.py` 19/19、`check_video_p0_api.py` 8/8、`check_video_p1.py` 14/14、`check_creative_tasks.py` 23/23、`check_video_claims.py` 16/16；`tests/run_all.py` **185 项，失败 0 / 错误 0 / 跳过 2**。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 界面约束：新增一个二级菜单「素材标准库」及其只读页面；未改任何其他页面布局、按钮或一级导航。
- 四种状态：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌；本轮未发起付费出片，也未做各平台实际上传审核。
- 待确认：Meta 官方 Ads Guide 访问受限，需后续取得可核验当前参数后把相关条目升级为 A；Adsterra 原生 320x240 比例冲突与视频入口能力、Mintegral 200MB/50MB 按入口的适用边界，正式投放前须按账户实际广告产品复核。

## V4.83 状态一致性与交付时长门——同批次始终一份状态，5 秒原片不再冒充 15 秒成片

**发布日期**：2026-11-17 10:55
**变更类型**：修复 / 优化 / 新增
**涉及模块**：素材创作平台（创意工作台：视频工作区 / 分镜微调 / 结果回填 / 交付导出）、创作任务与后台 worker、视频模型请求与落盘校验、大模型配置（视频请求时长 / media 输入开关）、任务抽屉与任务浮窗、媒体平台规格目录（差异登记）、发版流程、系统版本
**变更摘要**：按《创意工作台状态一致性与主流媒体素材规格诊断实施方案》逐条自查 V4.82（提交 `f844395`）后确认 C01–C06 全部仍存在：工作区按 `applyingRef` 只回填一次、详情失败被吞成 null 就清空订阅；分镜生成 / 微调走另一条长轮询链路；多视频只取第一个子任务；服务端已 `succeeded` 却保留 `stage=validating`；dashscope_maas 请求根本没传 `duration`，实测 5.04s 与所选 15s 只写警告仍标成功；历史 ZIP 不含批次视频、刷新丢草稿。本次在不改整体布局与按钮位置的前提下，把工作区与抽屉统一到同一份服务端任务快照，把时长偏差升级为交付判定，并让导出包与刷新恢复覆盖批次内成片。
**更新要点**
- 状态单一事实：视频结果按 `batch_id` 持续订阅服务端详情（首次 2.5s、后续 5s），`appliedRef` 只存快照指纹而非「应用过」布尔；失败续查转成功、重试出新 attempt 都会重新回填，详情读取失败只显示「状态暂未同步」并保留追踪
- 当前执行版本：同一 retry 链按 `retry_of / attempts / created_at` 取当前 attempt，批次内多个目标视频全部展示，不再 `find(kind==='video')` 只取最早一个
- 入口统一：原 VideoStudio 的「生成」与「微调并重生成」不再各自调用长轮询接口，改为父级 `onSubmitJob` —— 与批量生成共用同一持久任务提交、草稿、批次、幂等键与错误清理；网络重试复用同一幂等键，换分镜或微调才换键
- 新执行清旧错：提交前清 `videoFail / error / videos / note`，旧红色失败框不会跟到新任务；任务失败时错误与资产均来自本次 job
- 终态一致：`creative_tasks.py` 在成片校验成功时把 `status=succeeded`、`stage=completed`、`finished_at`、资产与结论放进同一事务；`job_to_task` 与兼容接口在终态按 status 取中文标签，杜绝「已完成 · 下载校验中」
- 时长真正下发：`ModelVideo._body` 的 dashscope_maas 请求在 `parameters` 中携带 `duration`，图生视频可按 `media_input=true` 切到官方 `input.media`；`send_duration=false` 为不兼容该字段的厂商保留配置出口
- 交付时长门：新增 `_duration_verdict`，目标值来自冻结任务快照、实测值来自 ffprobe/mvhd；容差默认 ±0.5s（`CW_VIDEO_DURATION_TOLERANCE` 可配）。5.04s/15s → `needs_attention + DURATION_MISMATCH`，原片保留可预览下载并标 `noncompliant`，不计合格成功；探测不到时长标 `unverified`，同样不冒充合格
- 恢复与导出：`draft_id / batch_id` 写入浏览器会话引用（换账号自动清除），刷新后按 ID 续追；历史导出 ZIP 支持 `batch_id` 参数并入批次视频，`交付清单.json` 标明角色、交付状态与实测时长
- 展示细节：任务抽屉和工作区视频卡在原有位置显示实测时长 / 目标时长与「未达标 / 时长未验证」文字标记，不新增页面、抽屉、导航或按钮
**本次优化与更改的功能 / 模块**
- 【修复】C01 一次性回填与详情失败清空订阅（T01/T02/T07）
- 【修复】C02 主路径 / 单独生成 / 微调两条链路分裂，提交不清旧失败（T04/T06）
- 【修复】C03 同批多视频 / 重生成取错 attempt（T05）
- 【修复】C04 成功但阶段仍显示下载校验中（T08）
- 【修复】C05 15 秒未下发、5 秒原片标成功（T09/T10）
- 【修复】C06 导出漏批次视频、刷新丢草稿（T16/T07）
- 【优化】任务浮窗只在视频批次仍运行时保持 running，不再按「结果页且没视频」猜失败
- 【优化】视频请求与响应新增 `requested_duration / measured_duration / delivery_status`，兼容旧字段
- 【优化】导出包新增 `交付清单.json`，不合格原片可追溯但不静默混入可投放成品
- 【优化】新增专项验收脚本 `scripts/check_video_v483.py` 14/14，并把 P0/P1/P2 假成片升级为带真实 mvhd 的 15s MP4
- 【优化】系统版本 / 版本更新：系统版本升至 V4.83
**影响范围**
- 后端：`providers.py`（请求体时长 / media）、`creative_tasks.py`（交付门 / 原子终态 / 快照字段）、`routers.py`（终态标签 / 同步链路共用交付门 / 批次 ZIP 参数）、`schemas.py`、`creation_history.py`。
- 前端：`CreativeWorkbench.tsx`（订阅式回填 / 唯一提交入口 / 会话恢复 / 导出）、`VideoStudio.tsx`（父级提交回调 / 未达标标记）、`useCreativeTasks.ts`、`CreativeTasksDrawer.tsx`、`api.ts`、`styles.css`。
- 数据：不新增表、不改列；资产 `meta_json` 与任务 `result_json` 新增可选字段，旧任务读取时缺省值兼容。历史文件不改写、不慢放、不改元数据冒充 15 秒。
- 行为变化（重要）：请求 15s 而厂商只给 5s 时不再显示「已完成」，而显示「时长未达标」并保留原片；用户需重新生成（新费用）或确认模型支持目标时长。
- 平台规格：本版只完成状态与时长 P0；Meta 视频 4:5、Google Search/RDA/App/PMax/上传横幅拆分、Unity/AppLovin/Mintegral/Moloco/TikTok/Adsterra 的资产角色与容量边界、图片字节预算与伴随资产校验仍按文档 P1/P2 单独推进。`SPEC_VERIFIED_ON` 保持为空，不把内部目录冒充官方核验。
**验证**
- V4.83 专项：`python3 scripts/check_video_v483.py` **14/14 通过**（duration 下发 / 关闭开关 / media 输入 / 时长判定三态 / 5.04s→DURATION_MISMATCH / 终态 stage=completed / 原片 noncompliant / 快照字段 / 不提供无效续查 / 批次不计 done / ZIP 并入视频）。
- 回归未退化：`check_video_pipeline_p0.py` 19/19、`check_video_p0_api.py` 8/8、`check_video_p1.py` 14/14、`check_creative_tasks.py` 23/23、`check_video_claims.py` 16/16；`tests/run_all.py` **181 项，失败 0 / 错误 0 / 跳过 2**。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 界面约束：未新增页面、一级导航、抽屉或按钮；仅新增状态文案与时长 / 未达标文字标记。
- 四种状态：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌；本次未发起付费出片。文档线上证据（a8026eac… 任务 5.04s）仅作问题定位，未被本轮测试改写。
- 待确认：真实供应商是否接受 `parameters.duration` 与 `input.media` 需在白名单部署机执行 `python3 scripts/verify_real_video_once.py --yes` 补齐；不支持时配置 `send_duration=false` 并换用支持目标时长的视频模型。

## V4.82 视频链路补齐 D0 证据门——分镜不再出现无出处的评分与数字承诺

**发布日期**：2026-11-16 17:13
**变更类型**：修复 / 优化 / 新增
**涉及模块**：创意工作台（视频分镜 / 视频出片）、证据与广告承诺、商品素材门、后端接口、前端与菜单、大模型配置（视频错误动作）、系统设置（版本通知）、回归测试、发版流程、系统版本
**变更摘要**：《素材创作平台新版验收与自动化创作改造实施方案》v2.0 的 D0–D6 已在 V4.44–V4.46 落地，但那是针对图片 / 文案链路；V4.67 之后新增的创意工作台视频链路绕过了证据与限定保护：分镜模型只收到「不要编造」的口头约束，兜底模板甚至直接写了虚构评分与用户数，出片提示词只拼接 `sellingPoints`。本次把 D0 的 `[E###]` 证据契约、限定词保护和交付门复用到视频：分镜与出片提示词带同一份证据依据，所有字幕 / 旁白 / 画面文案强制审计，无出处数字与丢失限定在入队前拦截且不产生厂商费用，缺商品主体时如实标草案、图生视频缺图直接拦截。
**更新要点**
- 分镜规划：系统提示词与请求体新增 `evidence_contract`，明确数字 / 评分 / 价格 / 效果 / 试用 / 订阅 / 兼容性承诺必须有原文出处且保留「最多 / 护理模式 / 测试条件 / 计费周期 / 适用范围」限定
- 兜底模板：删除 `★★★★★ 4.8 · 100K+ users` 与「三步完成」等页面未确认的数字承诺，改为中性功能演示文案并标草案
- 分镜审计：`audit_video_plan()` 同时检查「数字能在原文定位」与「限定不丢失」，镜头时间码 `0-3s` / 尺寸 `1080x1920` 不误判为广告承诺
- 保守修复：`repair_video_plan()` 对违规文案做一次确定性降级（换成不含数字的中性表达），修不掉则 `generation_blocked=true`，按钮禁用且提交端返回 422
- 出片提示词：与分镜共享同一证据契约，`prompt_hint` 不能把被删掉的承诺找回来；`claim_status` / `asset_gate` 随分镜与结果归档
- 商品素材门：纯文生视频标 `no_product_asset / draft`，有参考图标 `reference_provided / draft`（未核验官方 SKU / 授权），图生视频无图直接 `asset_missing` 拦截
- 提交前拦截：违规分镜在 `POST /cw-video/generate-jobs` 入队前返回 422，无供应商任务号、无费用；同步出片接口返回 `CLAIM_UNSUPPORTED` / `ASSET_MISSING` 并附证据
- 回归修复：`tests/test_auto_creation.py` 中 3 个用例仍引用 V4.70 已下线的 `creationSession.ts` / `MediaAdStudio.tsx` 等文件，改为指向现行 `api.ts` / `CreativeWorkbench.tsx` 或显式跳过历史会话用例
**本次优化与更改的功能 / 模块**
- 【新增】视频证据服务 `backend/video_claims.py`：证据上下文、分镜审计、保守修复、商品素材门（纯函数，不调用模型）
- 【修复】视频分镜不再出现无出处的评分、用户数、限定丢失的量化承诺（N01 / A06 / A07）
- 【修复】兜底模板不再把虚构数字当「合理默认」
- 【修复】图生视频缺参考图不再静默出片（N03 / A08）
- 【优化】分镜结果新增 `claim_status` / `generation_blocked` / `delivery_grade`，前端对不可提交的分镜禁用生成按钮并说明原因
- 【优化】错误码新增 `CLAIM_UNSUPPORTED` / `ASSET_MISSING`，均属于「未提交厂商、不扣费」的前置拦截
- 【优化】回归测试 `scripts/check_video_claims.py` 16 项 + 既有 `tests/run_all.py` 181 项（0 失败 / 0 错误 / 2 跳过）
- 【优化】系统版本 / 版本更新：系统版本升至 V4.82
**影响范围**
- 后端：新增 `video_claims.py`；`routers.py`（分镜 prompt / 兜底模板 / 审计修复 / 提交拦截 / 结果字段）、`providers.py`（错误动作）、`schemas.py`（分镜结果字段）。
- 前端：`CreativeWorkbench.tsx`（分镜证据 / 素材拦截提示与按钮禁用）、`styles.css`（`.cwb-plan-warn`）。
- 数据：不新增表、不改列；审计结果随分镜 JSON 与任务快照落库，历史视频与任务不改写、不重新收费生成。
- 行为变化（重要）：含无出处数字或丢限定的分镜不能再直接出片；先自动保守修复，修不掉需回到分镜规划修改。图生视频必须带参考图。纯文生视频产出明确标为概念草案，不按可投放商品广告交付。
- 兼容性：`/cw-video/plan` 响应只增字段；已通过审计的历史分镜继续可用；违规历史分镜首次提交会收到 422 与具体原因，修改后可重新提交。
- 安全与成本：所有新增校验都在提交厂商之前，不产生新的模型费用；不执行生产部署、真实付费生成或广告投放。
**验证**
- 视频证据验收：`scripts/check_video_claims.py` **16/16 通过**（证据契约注入、虚构评分 / 用户数拦截、限定丢失拦截、时间码不误判、保守修复、兜底模板去数字、素材门三态、入队前 422、修复后可入队）。
- 全量回归：`python3 tests/run_all.py` **181 项，失败 0 / 错误 0 / 跳过 2**（两个跳过项为 V4.70 已下线前端会话用例，已在测试内注明历史边界）。
- 视频链路未退化：`check_video_pipeline_p0.py` 19/19、`check_video_p1.py` 14/14、`check_video_p0_api.py` 8/8、`check_creative_tasks.py` 23/23。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过。
- 四种状态：代码已实现 ✅、模拟测试通过 ✅、真实模型验证 ❌、真实投放验证 ❌；本次没有执行真实付费出片。

## V4.81 P2+P3：出片任务持久化与「任务」抽屉——等待期间可以继续创作

**发布日期**：2026-11-16 14:50
**变更类型**：修复 / 优化 / 新增
**涉及模块**：创意工作台（视频出片 / 后台任务）、创作批次与子任务、任务抽屉与顶部入口、后端接口、数据模型（批次表与任务执行字段）、大模型配置（视频 Provider 分步执行）、系统设置（后台 worker 启停）、前端与菜单、发版流程、系统版本
**变更摘要**：P0 让失败说清楚、P1 让时长不作假，但视频任务仍活在进程内 `_CW_VIDEO_JOBS` 字典里：刷新靠前端 sessionStorage 续命、服务重启全丢、多进程部署会「查到另一个进程 404」，而且提交后页面必须挂着轮询，1–6 分钟内做不了下一份创作。本次把任务搬进数据库并用租约 + `next_poll_at` 驱动的 worker 分阶段推进（提交 / 查询 / 下载校验），提交即返回；前端顶部新增「＋ 新建创作」和「任务 N」两个入口，右侧 400px 抽屉按批次展示真实阶段与结果，视频在后台跑的同时可以继续开新的创作。

**更新要点**
- 任务持久化：新增 `creative_batches` 轻量批次表；`generation_jobs` 增补 `batch_id / stage / provider_config_id / provider_model / provider_task_id / provider_request_id / next_poll_at / heartbeat_at / lease_until / error_code / error_stage / error_message / error_action / last_provider_status / asset_ids / evidence_json` 16 个执行字段，`migrations.py` 自动补列
- Provider 分步化：`ModelVideo` 拆出 `plan_request()` / `submit_job()` / `poll_job()` / `store_media()`，`generate()` 改为基于它们组合（同步接口行为不变）；供应商任务号在拿到的第一时间就落库，重启后按键续查
- 启动恢复：租约过期的 `running` 任务重新排队；**有任务号的按原号继续查询，绝不重新提交**；提交后未及回写就崩溃的记为 `SUBMIT_UNKNOWN` 待核实，交人工确认，不自动重试避免重复收费
- 提交即返回：`POST /cw-video/generate-jobs` 不再等出片，返回 `job_id + batch_id + status + stage`；页面提交后立即可用，不再被长轮询钉住
- 顶部两个入口：`＋ 新建创作`（只建空白草稿，不动任何已有任务与结果）与 `任务 N`（N = 本人排队 + 进行中批次）；不新增一级导航
- 任务抽屉：右侧 400px，三态筛选（进行中 / 已完成 / 需处理）+ 按产品名或任务号搜索；单行只给决策必需信息（产品名、类型、媒体、真实阶段、已等待、成功数）；阶段用「排队中 / 提交中 / 模型生成中 / 下载校验中」，**不把等待时长换算成百分比**
- 分项重试严格区分：`继续查询`（按原厂商任务号续查，不重复收费）/ `重新下载`（只重下并校验）/ `重新生成`（新建执行 ID + 新费用），按钮文案与 title 各自说明；`停止后续步骤` 明确告知在途任务仍可能完成并计费
- 混合批次：同一次创作的图片与视频作为子任务挂在同一批次下，图片先完成即可在抽屉里预览下载，视频独立继续（A10）
- 幂等与归属：同幂等键同内容复用原任务、异内容返回 409；批次列表/详情/重试/停止全部按 owner 授权，他人一律 404
- 并发与租约：worker 单进程按配置维度限并发（视频 2），超出排队不无限 `create_task`；领取走原子 `UPDATE` 租约，未到期不会被重复消费；运行中任务不参与任何容量/TTL 清理
- 可灵分支同标准：不再「失败静默回退分镜」，下载改为走三层校验并回传实测时长；无鉴权时报 `CONFIG_MISSING` 而不是假装出了分镜
- 其他修复：`req()` 的 headers 合并顺序（调用方传自定义头会把 `Content-Type` / `Authorization` 整块覆盖掉）；`?tasks=1` 可直接打开任务抽屉（可做书签）

**本次优化与更改的功能 / 模块**
- 【新增】后台任务：持久化任务服务 + 租约 worker（`creative_tasks.py`）
- 【新增】任务抽屉：顶部「＋ 新建创作」「任务 N」两个入口，三态筛选 + 搜索 + 分项重试
- 【新增】创作批次：`creative_batches` 表与 `GET/POST /api/creative-tasks`、`/{batch_id}`、`/retry`、`/cancel`
- 【修复】视频任务不再随进程消失：重启后按供应商任务号续查，不重复提交收费任务
- 【修复】提交后页面可继续创作：视频等待不再阻塞输入流程
- 【修复】可灵链路失败不再静默换成「分镜」冒充交付
- 【优化】阶段语义：submitting / provider_pending / downloading / validating 如实展示，不做假进度
- 【优化】接口兼容：`/cw-video/generate-jobs` 与 `/{id}` 保留，内部转发持久化任务，响应结构向后兼容
- 【优化】数据模型：批次表 + 任务执行字段（供应商任务号、租约、错误码与动作、资产引用）
- 【优化】系统版本 / 版本更新：系统版本升至 V4.81

**影响范围**
- 后端：新增 `creative_tasks.py`；`providers.py`（分步执行、`save_video_media`、可灵分支、`video_provider_of_config`）、`routers.py`（任务端点改走持久化、`_cw_video_request_build`、creative-tasks 接口、`POST /creative-tasks`）、`models.py`（`CreativeBatch` + 任务字段）、`schemas.py`（`CWVideoJobOut.batch_id`）、`job_service.py`（`create_job` 支持 `batch_id`）、`main.py`（启动/停止 worker）。
- 前端：新增 `CreativeTasksDrawer.tsx`、`useCreativeTasks.ts`；`api.ts`（`submitVideoJob` / creative-tasks 方法与 headers 修复）、`CreativeWorkbench.tsx`（顶部两入口、批次创建、提交即返回、结果按 batch 回写、新建创作不删任务）、`styles.css`（`.cwb-new-btn` / `.cwb-task-btn` / `.cwb-submitted` / `.ctd*`）。
- 行为变化（重要）：**视频生成按钮点完后不再原地等结果**，页面提示「任务已加入后台」并在抽屉里展示真实阶段；成片出现后自动回写到结果区。旧内存任务（V4.80 之前创建、仍在进行中的）无法自动找回，需等其结束或到厂商控制台按任务号取片。
- 兼容性：`POST/GET /cw-video/generate-jobs` 保留且响应字段只增不改；图片生成接口未改动，仅新增可选 `batch_id`。
- 部署：需 `docker compose up -d --build`；worker 随后端进程启动（日志出现 `[creative-tasks] worker 已启动`），单进程默认即可，多进程部署靠租约防止重复消费。

**验证**
- 持久化验收（本地假供应商，零费用）：`scripts/check_creative_tasks.py` **23/23 通过** —— 提交即返回、阶段推进与任务号落库、成片成功 + 资产落库 + 批次聚合 done、重启恢复按原任务号续查且不重新提交、超期转 `needs_attention` 并可 repoll、租约期内不被重复领取、同配置并发 ≤2、归属隔离（他人列表空 / 详情 404）、混合批次图片先就绪视频独立继续、停止后续步骤。
- P0/P1 未退化：`check_video_pipeline_p0.py` 19/19、`check_video_p1.py` 14/14、`check_video_p0_api.py` 8/8（任务状态相关断言已迁到上面新增用例）。
- HTTP 冒烟（临时库 + 真实鉴权）：建批次 → 提交视频（带 `X-Batch-Id` / `Idempotency-Key`）→ 列表可见该批次 → 无视频配置时报 `CONFIG_MISSING` 且给出唯一动作，批次归入「需处理」。
- 无头浏览器渲染：登录态下工作台渲染出「＋ 新建创作」「任务」；`?tasks=1` 打开抽屉，筛选、搜索框、空态文案、需处理分组的任务行均正常渲染，无运行时报错。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过。

## V4.80 P1：交付时长按实测值、出片文件名唯一化——不再「计划 15s 当 15s 交付」

**发布日期**：2026-11-16 14:33
**变更类型**：修复 / 优化 / 新增
**涉及模块**：创意工作台（视频出片）、视频交付物字段、视频校验、文件命名、大模型配置（视频结果回传字段）、后端接口（视频结果）、数据模型（视频结果时长字段）、前端与菜单（视频卡片时长徽标）、发版流程、系统版本
**变更摘要**：P0 之后成片必须落盘通过校验，但交付物上的时长仍沿用「提示词里写的 15 秒」——厂商按自身模板出 5s/10s 时，界面与导出依然标 15s，用户以为拿到了长片。同时落盘文件名只有「用户 + 秒级时间戳」，同一秒内批量生成或连续重试会互相覆盖，先出的片子被后出的静默顶掉。本次让时长只来自真实文件（读 MP4 `moov/mvhd`，有 ffprobe 时优先 ffprobe），并在与所选时长不符时明确提示；文件名补随机 UUID，扩展名跟随真实容器。

**更新要点**
- 时长实测化：`verify_video_file()` 新增 `duration` / `duration_source`；镜像没装 ffprobe 时零依赖读 `moov/mvhd`（支持 version 0/1 两种头），拿不到就返回 0，**绝不用计划值冒充实测值**
- 交付物字段：`CWVideoAsset` 新增 `duration_source`（`measured` / `planned`），`duration_sec` 改为浮点以保留真实秒数（如 15.04s）
- 不符即提示：实测与所选时长相差 ≥1s 时，result.note 明确写出「实测成片时长 10.0s，与所选 15s 不一致（厂商按自身模板输出）」——不再让 5s 的片子顶着 15s 标签交付
- 计划/实际分开记：分镜 `storyboard.duration_sec` 仍是计划值，新增 `duration_sec_actual` 记实测值，导出与后续核对不会被混用
- 命名唯一化：`_cw_video_filename()` = `cw_video_{用户}_{秒级时间}_{随机8位}`，同秒批量出片/连续重试不再互相覆盖（20 次同秒命名 0 重复）
- 扩展名对齐：新增 `align_video_ext()`，按真实容器（`ftyp` / webm / FLV / ts）修正扩展名，避免厂商回 webm 却存成 `.mp4` 被浏览器按 MIME 拒播
- 界面标注：视频卡片在片段名后显示时长徽标，实测值标「· 实测」，兜底值只显示秒数（悬浮提示区分来源），不新增任何操作步骤

**本次优化与更改的功能 / 模块**
- 【修复】视频交付物：时长改取实测值，来源如实标注
- 【修复】视频命名：同秒并发出片不再互相覆盖
- 【修复】视频扩展名：跟随真实容器，避免浏览器拒播
- 【优化】时长不符：结果文案明确提示差异
- 【优化】数据模型：视频结果新增 `duration_source`、分镜新增 `duration_sec_actual`
- 【优化】系统版本 / 版本更新：系统版本升至 V4.80

**影响范围**
- 后端：`providers.py`（新增 `_mp4_boxes` / `_mp4_duration` / `align_video_ext`，`verify_video_file` 增补时长来源，`download_video` 与 `_save_media` 回传 `duration_source` 并对齐扩展名）、`routers.py`（新增 `_cw_video_filename`、实测时长与来源进入资产、不符提示、`duration_sec_actual`）、`schemas.py`（`CWVideoAsset` 字段）。
- 前端：`VideoStudio.tsx`（视频卡片时长徽标）、`styles.css`（`.vs-video-dur`）。
- 兼容性：`duration_sec` 由 int 变 float，JSON 结构与旧值兼容（15 → 15.0）；`duration_source` 为空表示未知来源，仅做展示用，不参与判定。
- 部署：需 `docker compose up -d --build` 重建前后端。

**验证**
- P1 确定性验收（零费用）：`scripts/check_video_p1.py` **14/14 通过** —— mvhd v0/v1 解析（15.04s / 5.0s）、无 mvhd 不编造时长、无 ffprobe 仍得实测值且来源为 `mvhd`、webm 内容改名为 `.webm`、同秒 20 次命名无重复、实测 10s 不被写成 15s 且带不符提示、分镜计划值与实际值分列、同秒两次出片两个文件都在、无实测值时退回计划值并标 `planned`。
- P0 回归未退化：`scripts/check_video_pipeline_p0.py` 19/19、`scripts/check_video_p0_api.py` 8/8。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过。

## V4.79 P0：视频出片链路「不再假成功」——白名单解析、失败可分类、成片必校验

**发布日期**：2026-11-16 14:29
**变更类型**：修复 / 优化 / 新增
**涉及模块**：创意工作台（视频出片）、视频链路诊断、大模型配置（视频连通测试）、后台任务状态、数据模型（视频结果与任务字段）、发版流程、系统版本
**变更摘要**：此前出片链路的失败会被逐层吞掉——响应解析用「递归找第一个 http 字符串」，把 PENDING 里的输入图当成片；轮询的 `except: continue` 让 401/5xx/非 JSON 静默空转 6 分钟；下载失败直接把外链当结果；实现层永不抛异常，于是后台任务无条件写 `done`，界面显示「完成」却没有视频。本次把这条链路改成「成功必须有可播放的本地产物，失败必须带错误码和唯一动作」：解析按协议族白名单取值，轮询按 HTTP 语义分类退避，下载做三层校验（content-type / 容器 magic bytes + MP4 moov 索引 / ffprobe 可选），任务状态新增 `needs_attention`，并保留脱敏证据链。

**更新要点**
- 解析白名单化：新增 `video_media_of()`，只认厂商文档里出现过的容器与字段（`output.video_url` / `output.video_urls[]` / `output.results[].url` / `data[].url` 等），**不再从 `input` / `parameters` / `request` 回显区取媒体**——修掉「图生视频把上传的商品图落盘成 .mp4」的假成功
- 任务号提取纠偏：`_video_find_task_id()` 对 dashscope 系禁用 `request_id` 兜底（它是请求追踪号，不是任务号）；只有「仅 request_id 无 task_id」时按契约不匹配报错，而不是拿追踪号空轮询 6 分钟
- 轮询分类退避：401/403 → `AUTH_FAILED` 立即停；429/5xx → 记原因并退避；404 → 记录 poll_path 不匹配；非 JSON → 记「网关换成 HTML」；连续失败达上限（默认 6 次）→ `POLL_UNREACHABLE`；超时 → `POLL_TIMEOUT` 并**保留厂商 task_id**（可凭号到控制台取片，不需重复付费）
- 下载三层校验：`download_video()` 先看 HTTP 状态与 content-type（HTML/JSON 直接判失败），再按文件头识别容器（`ftyp` / webm / FLV / ID3），MP4 必须有 `moov` 索引，镜像内有 `ffprobe` 时再核视频轨道与时长；**下载失败绝不回传外链**
- 成功条件收紧：`videos` 非空当且仅当本地文件通过校验；后台任务成功 = `done`，未出片 = 新增的 `needs_attention`（带 error_code），服务端 bug 才是 `error`——不再用 `done + videos=[]` 掩盖失败
- 错误码与唯一动作：10 个 `error_code`（AUTH_FAILED / BAD_REQUEST / RATE_LIMITED / PROVIDER_ERROR / CONTRACT_MISMATCH / PROVIDER_REJECTED / POLL_UNREACHABLE / POLL_TIMEOUT / EMPTY_OUTPUT / DOWNLOAD_FAILED）各自只对应一个可执行动作，页面只展示那一条，不让用户在三四个按钮里猜
- 诊断四态收敛：`/cw-video/diagnose` 新增 `state` / `state_label` / `action`，把「未配置 / 配成文本模型 / 未启用或缺要素 / 协议缺参 / 连通失败 / 就绪」直接结论化，页面顶部只给一句结论 + 一个动作
- 证据链留痕：结果新增 `evidence`（提交状态与脱敏响应摘要、每次轮询的状态与摘要前 3+后 5 条、下载的 content-type/字节/容器/校验结论），并落盘到 `backend/uploads/video_evidence/`，用户报障时可直接核对，不必重现
- 连通测试严格化：`_test_generic_video` 不再「status<400 就算通过」；200 + HTML 判 `non_json_response`，200 但既无任务号也无成片判 `contract_mismatch`——避免「配置显示已连通，实际出不了片」
- 任务归属校验：`GET /cw-video/generate-jobs/{id}` 增加 owner 比对（用 404 而非 403，避免泄露任务存在性）；`sweep` 不再清理运行中的任务，只清已完成且过期者
- 统计修正：工作台批量生成的成功判定改为「真出片才算」（纯图片模式下 `vidOk` 曾恒为 true，图片全失败也会提示「创作完成，视频已生成」）

**本次优化与更改的功能 / 模块**
- 【修复】创意工作台 / 视频出片：解析白名单、下载三层校验、严格成功条件
- 【修复】视频轮询：HTTP 语义分类 + 退避 + 超时保留任务号
- 【修复】后台任务：新增 `needs_attention`，不再用 done 掩盖失败
- 【修复】大模型配置 / 视频连通测试：200 + 非 JSON / 无任务号不再判通过
- 【修复】批量生成：成功判定与提示文案按真实产出计算
- 【新增】证据链：结果回传 + 落盘 `uploads/video_evidence/`
- 【优化】诊断：四态结论 + 唯一动作
- 【优化】任务归属：按 owner 校验读取权限
- 【优化】系统版本 / 版本更新：系统版本升至 V4.79

**影响范围**
- 后端：`providers.py`（新增 `VideoPipelineError` / `video_media_of` / `_video_task_status` / `verify_video_file` / `download_video`，重写 `ModelVideo.generate`）、`routers.py`（失败结果映射、`needs_attention`、诊断四态、证据落盘、owner 校验）、`schemas.py`（结果与任务新增字段）、`llm_catalog.py`（视频连通测试严格化）。
- 前端：`api.ts`（识别 `needs_attention`）、`VideoStudio.tsx`（失败面板：错误码 / 阶段 / 唯一动作 / 任务号 / 可展开证据；诊断四态标题与动作）、`CreativeWorkbench.tsx`（失败信息透传、成功判定修正）、`styles.css`（`.vs-fail*` / `.vs-diag-act`）。
- 行为变化（重要）：**以前显示「完成」但实际回退分镜的出片，升级后会明确显示为「出片失败 + 错误码」**，且分镜仍作为兜底交付物保留。这是有意的——失败要说清楚，才能修得动。
- 兼容性：新增字段均可选，旧调用方不受影响；同步接口 `/cw-video/generate` 保留，失败时也返回 `error_code` 而非抛 500。
- 部署：需 `docker compose up -d --build` 重建前后端。证据目录随 `uploads` 卷持久化（已在 `.gitignore`）。

**验证**
- 确定性验收（本地假供应商，零费用）：`scripts/check_video_pipeline_p0.py` **19/19 通过** —— 含 PENDING 输入图不被当成片、401/500/200+HTML/只有 request_id 的分类、完成无地址、厂商 FAILED、轮询持续 5xx、下载到 HTML、MP4 缺 moov、同步直出、异步成功、连通测试三项严格化。
- 接口层验收（临时库 + 假供应商）：`scripts/check_video_p0_api.py` **8/8 通过** —— 诊断 no_config / text_model / ready 三态、失败结果字段完整且分镜仍在、任务状态为 `needs_attention`、证据落盘含 submit/polls、成功任务 `done` 且产物通过容器校验、他人任务不可读（404）。
- 真实出片：`scripts/verify_real_video_once.py --yes` 在部署机发起 **1 次**付费调用，结果与证据写入 `docs/evidence/v479_real_*.json`（需在 Key 白名单所在主机执行）。
- 质量：`npx tsc --noEmit` 0 错误；`npm run build` 通过。
