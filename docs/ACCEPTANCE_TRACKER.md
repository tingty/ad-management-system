# 素材创作平台新版验收与自动化创作改造追踪表

> 依据：《素材创作平台新版验收与自动化创作改造实施方案》v2.0（2026-11-10）
> 审查基线：`36e2a5cd9a2514e8738886eb36b668f8796e7a84` / V4.43
> 本表只记录**本仓库实际代码状态**；文档的「建议新增契约」在未落地前一律标注为规划，不写成已上线。

## 一、验收结论对齐

文档判定：**工程修复有条件通过；真实产品素材质量与全自动可投放交付尚未通过**。
因此 V4.39–V4.42 追踪表里的「F01–F12 已完成」只代表**工程路径已修**，不等于本轮验收通过。
本表不复用旧追踪表的断言数量作为独立结果，改以 `tests/` 下可运行脚本为准。

| 编号 | 文档判定 | 本仓库落点 | 状态 |
| --- | --- | --- | --- |
| F01 | 部分通过（短句丢限定未阻断） | `claims.py` 限定词保护 | V4.44 |
| F02 | 针对性通过 | `industry_profiles.brand_from_page` | 保持 |
| F03 | 部分通过（概念证据取副标 / 通用动作池） | `claims.py` + `creative_config.py` | V4.44 |
| F04 | 针对性通过 | `creative_config.resolve_creative_config` | 保持 |
| F05 | 部分通过（线上图仍有大字模板） | 素材质量裁决 | V4.46 |
| F06 | 部分通过（默认候选未核验） | `image_capabilities.py` 标记 | V4.46 |
| F07 | 针对性通过 | `taskMatrix.ts` | 保持 |
| F08 | 部分通过（版位尺寸错配） | `media_platforms.validate_task_matrix` | V4.44 |
| F09 | 部分通过（无效证据 ID 不拒绝） | `services._normalize_landing` + `claims.py` | V4.44 |
| F10 | 部分通过（真实调用未复验） | `providers.py` 归因 | V4.46 |
| F11 | 部分通过（取消点/配额未复验） | `batch_workspace.py` | V4.46 |
| F12 | 部分通过（重启后无法重试） | `job_service.py` | V4.44 |

## 二、新增缺口 N01–N06 → 修复映射

| 编号 | 问题 | 修复文件 | 期次 |
| --- | --- | --- | --- |
| N01 | 证据链没有贯穿到广告承诺；`[E###]` 与 `EV_S###` 双命名空间；短句丢限定 | `evidence.py`（统一快照）、`claims.py`（新增）、`services.py`、`media_ad.py` | V4.44 |
| N02 | 关键词 + 哈希动作池代替产品策划 | `industry_profiles.py`（场景策略）、`creative_config.py` | V4.44 |
| N03 | 商品素材缺口未阻止可投放交付 | `creation_planner.py`（产品对象 + `quality_gate`）、`MediaAdStudio.tsx`（草案等级归档） | V4.45（工程路径；逐图质检 D5 未上线） |
| N04 | 版位级规则校验不完整；未知版位被接受；目录缺 Moloco | `media_platforms.py` | V4.44 |
| N05 | 任务重启与幂等边界未闭环 | `job_service.py`、`models.py`、`routers.py` | V4.44 |
| N06 | 无可运行回归目录；源码含固定默认管理员凭据与自愈逻辑 | `tests/`（新增）、`main.py` | V4.44 |

## 三、D0–D6 任务与分期

| 期次 | 文档任务 | 交付范围 | 状态 |
| --- | --- | --- | --- |
| V4.44 | D0 | N01 / N02 / N04 / N05 / N06 修复 + 可运行回归目录 | 已完成（工程修复，非素材/效果验收通过） |
| V4.45 | D1 / D2 / D3 | 产品与资产对象、版本化行业策略、结构化概念、`recommended_visual_summary`、覆盖摘要、草案交付门、默认 auto + 可选 custom + 旧会话迁移 | 已完成（工程路径 + 模拟回归，非素材 / 效果验收通过） |
| V4.46 | D4 / D5 / D6 | 媒体全覆盖计划、PromptBundle、多阶段持久任务、逐图质检与归档、A09–A20 验收记录 | 已完成（工程路径 + 模拟回归，非素材 / 效果验收通过） |

## 四、验收用例（文档 A01–A20）

A01–A08 属 D1–D3 界面与策划路径；A09–A20 属 D4–D6 规则、编排与交付路径。
用例原文见方案文档，本表只登记执行状态；未执行一律写「未验证」，不写「通过」。

| 用例 | 覆盖期次 | 状态 |
| --- | --- | --- |
| A01–A08 | V4.45 | 模拟回归通过（`tests/test_auto_creation.py`）；真实模型 / 真实投放 / 人工视觉核验未验证 |
| A09–A20 | V4.46 | 模拟回归通过（`tests/test_d4_d5_d6.py`，32 项断言）；真实模型 / 真实投放 / 人工视觉核验未验证 |

A01–A08 逐项回归落点：A01 默认 auto 与推荐语（后端契约 + 前端会话）；A02 旧会话迁移 custom 且输入 / 历史不变（前端真实执行）；A03 四类行业主体与场景；A04 多商品页 `needs_input`；A05 价格条款与投放国家不推断；A06 无效 / 不可定位证据阻断并移除量化承诺；A07 硬限定词随概念下发、描述改非量化；A08 缺产品资产仅草案。另附 A10 未知平台拒绝、A13 计划版本失效、A15 草案不计可投放。

## 五、文档明确要求保留的边界

- 继续复用 `GenerationJob` / `CreativeAsset` / 任务矩阵 / `ResolvedCreativeConfig` / 分层渲染 / 逐图结果，
  自动流程只增加策划与编排，不另建独立生成系统。
- 「可定位原文」与「商业真实性已审核」分开：`verified=original_text` 不代表商业真实性背书。
- `SPEC_VERIFIED_ON` 与 `size_verified_on` 为空时不得宣称符合平台官方规范；官方规格需实施方逐项核验。
- 开发报告必须分别写明：代码已实现 / 模拟测试通过 / 真实模型验证 / 真实投放验证，四种状态不得混用。
- 未获授权不执行生产部署、广告投放或无上限真实模型生成。

## 六、验证记录

### V4.44 / D0（2026-11-10）

| 项目 | 实测结果 |
| --- | --- |
| `python3 tests/run_all.py` | 72 项断言全部通过（claims 18 / scene 14 / placement 14 / jobs 8 / security 7 / release-notes 11） |
| 前一期不回退 | V4.42 后端回归 85 项全部通过；测试输入按 N04 修正非法 `square` 版位，测试口令由 `INITIAL_PASSWORD_LESON` 注入临时库 |
| 编译与构建 | `compileall -q backend scripts tests`、`import main` = 4.44.0 / 42 条 API；`tsc --noEmit` 通过；`vite build` 44 模块、265.79 kB JS / 50.82 kB CSS |
| 版本通知锚点 | `APP_VERSION=4.44.0` → `get_release_notes()` 首条 `V4.44`，V4.43 的升版自动同步机制仍生效 |
| 发版闸门 | `prepare_release.py --check` 通过（系统版本 == CHANGELOG 最新版本且含「更新要点」） |
| 真实模型验证 / 真实投放验证 | **均未验证**；供应商 `size_verified_on` 与 `SPEC_VERIFIED_ON` 仍为空 |

### V4.45 / D1–D3（2026-11-10，提交 `a17ccff`）

| 项目 | 实测结果 |
| --- | --- |
| `python3 tests/run_all.py` | 96 项断言全部通过（V4.44 既有 72 项 + 本版 24 项） |
| 前端会话真实执行 | `tests/frontend/auto_creation_session.mjs` 经本地 esbuild 打包 `creationSession.ts` 后由 node 运行，6 组断言通过（默认 auto、旧 v2 迁移 custom、storage key 稳定、模式切换不丢数据、计划版本失效、不隐式收费） |
| 编译与构建 | `compileall -q backend scripts tests`、`import main` = 4.45.0 / 43 条 API；`tsc --noEmit` 通过；`vite build` 45 模块、279.39 kB JS / 57.21 kB CSS |
| 版本通知锚点 | `APP_VERSION=4.45.0` → `get_release_notes()` 首条 `V4.45`、6 条总结式更新要点 |
| 发版闸门 | `prepare_release.py --check` 通过（系统版本 == CHANGELOG 最新版本且含「更新要点」） |
| 交付门 | 全部自动产出 `delivery_grade=draft` / `deliverable=false`；`plan_id` / `plan_version` / 草案等级随 `archive` 快照落库 |
| 真实模型验证 / 真实投放验证 | **均未验证**；`SPEC_VERIFIED_ON` 与供应商 `size_verified_on` 仍为空 |

V4.46 已完成（D4–D6）：媒体全覆盖计划 / PromptBundle（D4）、多阶段持久编排与逐图质检逻辑（D5）、A09–A20 用例与灰度验收（D6）、`CreationPlan` 持久化表与 `GenerationJob` 计划关联列。
转后续期次（仍未验证）：官方媒体规格逐项核验（`SPEC_VERIFIED_ON` / `size_verified_on` 仍为空）、真实模型调用与视觉人工抽检、受控投放实验。
V4.46 的逐图质检只做到「供应商失败纯背景→draft/needs_revision、规则未核验→draft、manifest 聚合 qa」，尚不能替代逐图商品外观比对与 OCR 质检（A15 的完整人工判定）。

### V4.46 / D4–D6（2026-11-10）

| 项目 | 实测结果 |
| --- | --- |
| `python3 tests/run_all.py` | 128 项断言全部通过（V4.45 既有 96 项 + 本版 32 项）；0 失败 0 错误 0 跳过 |
| 前端会话真实执行 | `tests/frontend/auto_creation_session.mjs` 经本地 esbuild 打包 `creationSession.ts` 后由 node 运行（test_23）：6 组断言通过 |
| 编译与构建 | `compileall -q backend scripts tests`、`import main` = 4.46.0 / 56 条 API；`tsc --noEmit` 通过；`vite build` 45 模块、282.87 kB JS / 57.21 kB CSS |
| 版本通知锚点 | `APP_VERSION=4.46.0` → `release_tag()` = `V4.46`；`prepare_release.py --check` 通过 |
| 交付门 | 全部自动产出 `delivery_grade=draft` / `deliverable=false`；`plan_id` / `plan_version` 经 D5 `CreationPlan` 冻结后随任务 `archive` 落库；manifest 聚合覆盖范围与缺失报告 |
| 灰度开关 | `ENABLE_AUTO_CREATION_PLAN = True`（默认开启）；关闭时 5 条 `/api/creation-plans*` 返回 503，回滚不删列 |
| 真实模型验证 / 真实投放验证 | **均未验证**；`SPEC_VERIFIED_ON` 与供应商 `size_verified_on` 仍为空 |

A09–A20 逐项回归落点：A09 软件真实 UI 不烘焙文字/CTA 且保留 Logo（prompt_compiler ASSET_ROLE_RENDER + bundle 可溯源）；A10 未知平台 `create_plan` 抛 `MediaRuleError`；A11 `set_coverage` 只按已选平台；A12 6 平台×3 概念=48 任务拆 2 批、父计划不丢、无轮换伪装；A13 计划版本失效→409（版本冲突）；A14 confirm 费用低于成本上界/0 费拒绝、`over_budget` 显式标出；A15 失败纯背景→draft/needs_revision、规则未核验即便成功也 draft、manifest 聚合 qa；A16 同键不同内容冲突→409、路由 409 映射；A17 全链路 + 新会话按 plan_id 恢复；A18 中断标记 unknown_outcome 不自动重发、cancel 不复活；A19 取消后不可再 confirm；A20 manifest 含 item/missing/complete 不谎报。
