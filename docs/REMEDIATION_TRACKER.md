# 广告素材平台问题诊断与 AI 改造 · 问题追踪表

- 依据：《广告素材平台问题诊断与AI改造实施说明书.docx》v1.0（2026-11-10）
- 审查基线：`0ddbf3f159eeef4f15f2ff893f29d7ba9bd5106b`（V4.38）；本项目当前 HEAD 与基线一致，无代码差异。
- 事实边界：说明书的结论来自静态审查与最小复现，未运行完整服务、未做真实付费模型调用、未测量投放效果。
  本表只记录「当前代码里核对到的路径」与「已实际执行并通过的验证」，不把建议写成已上线能力。
- **行业适用范围**：说明书的样本是海外电商购买与订阅转化，但 12 个问题全部发生在「事实采集 → 文案生成 → 图片制作 → 归档」的通用链路上。
  因此改造按「通用主干 + 行业/品类局部配置」实施：主干对任何行业一致，`industry_profiles.py` 只调整价值维度、必须保留的语义、证据类型、视觉主体与版位偏好。
  电商与订阅是其中两个 profile，不是系统前提。

## 状态口径

| 标记 | 含义 |
|---|---|
| 说明书状态 | 已复现 / 静态确认 / 静态风险 / 新增设计需求（来自说明书，非本轮验证结果） |
| 代码核对 | 本轮阅读当前代码后确认存在 / 部分存在 / 不存在（含文件与行号） |
| 实施状态 | `待实施` / `已修复（版本号 + 验证结论）`；只有跑过对应回归用例才允许改为已修复 |

## 问题追踪表

| 编号 | 说明书状态 | 当前代码核对（V4.38） | 触发输入 | 计划修改文件 | 验收用例 | 期次 / 版本 | 实施状态 |
|---|---|---|---|---|---|---|---|
| F01 截断文案被判定合格 | 已复现；P1 | 存在。`media_ad._build_fields` 调用 `fit_text` 后丢弃裁剪标记；`_validate` 只比较长度，残句 `valid=true`；`imaging._wrap` 超行数追加省略号 | 英文完整句超过平台字数上限（如 `Book in minutes.`） | `text_utils.py`、`media_ad.py`、`imaging.py`、`industry_profiles.py` | T01 / T02 | 第 1 期 / V4.39 | 已修复（T01 / T02 通过：残句阻断、语义压缩保留限制条件） |
| F02 域名被误当品牌和最终站点 | 已复现 + 静态确认；P1 | 存在。`media_ad._brand_of` 取 host 倒数第二段（`shop.example.co.uk` → `Co`）；`fetch_page` 跟随跳转但 `parse_page_meta(html, url)` / `extract_logo(html, url)` 仍用原始 URL；`og:image` 被无条件当 Logo | 追踪域名 `convert.ctypy.com`、多级后缀商品链接、含相对 Logo 的跳转页 | `services.py`、`media_ad.py`、`industry_profiles.py`、`schemas.py` | T03 / T04 | 第 1 期 / V4.39 | 已修复（T03 / T04 通过：追踪域名与多级后缀不再定品牌、相对 Logo 用最终地址） |
| F10 实际模型和来源标记不可靠 | 已复现 + 静态确认；P1 | 存在。`providers._pick_config` 的 `last_test_ok` 分支未过滤 `is_active`；`services._resolve_model` 自行挑配置、与 `get_llm` 路由不一致；`fallback` 在 `chat()` 之前读取且调用后不刷新 | 停用但测试成功的配置、真实模型超时回退 Mock、返回可解析 JSON 的 Mock | `providers.py`、`services.py`、`media_ad.py` | T13 / T14 | 第 1 期 / V4.39 | 已修复（T13 / T14 通过：停用配置不可选、回退与 source 在调用后定稿） |
| F07 任务截断和文案轮换破坏覆盖 | 已复现 + 静态确认；P1 | 存在。`MediaAdStudio.buildSlots` 把所选版位尺寸展开后 `slice(0, count)`；副文案池混合 `description/body/primary_text` | Facebook / Google / Unity 默认配置 | `MediaAdStudio.tsx`、`creationSession.ts` | T09 | 第 2 期 / V4.40 | 待实施 |
| F08 媒体与接口规则不足以保证交付 | 静态确认；P1 | 存在。`media_platforms.py` 按平台名组织、无广告产品 / 资产角色 / 规则版本；`schemas.MediaImageSlot.size` 为无约束字符串 | 异常尺寸、超像素总量、超任务数、未知平台 | `media_platforms.py`、`schemas.py`、`routers.py` | T10 | 第 2 期 / V4.40 | 待实施 |
| F11 批次失败和临时文件缺少隔离 | 静态风险；P1 | 存在。`media_ad._cleanup_ai_bgs` 按目录通配符删除全部 `_mabg_*` / `_mlogo_*`；`asyncio.gather` 无并发上限且异常直接跳过；`ai_used` 为批次级 | 两批并发出图、混合成功 / 回退 / 失败 | `media_ad.py`、`imaging.py` | T15 | 第 2 期 / V4.40 | 待实施 |
| F03 文案概念没有进入背景生成 | 静态确认；P1 | 存在。`_media_image_prompt` 不接收标题 / 副文案 / 证据；任务构造先算 `bg_prompt` 再选文案组合 | 同一 SKU 的「清洗演示 / 通勤场景」两个概念 | `media_ad.py`、`prompt_catalog.py` | T05 | 第 3 期 / V4.41 | 待实施 |
| F04 预设编辑结果没有完整参与生成 | 静态确认；P1 | 存在。`build_directives` 返回的 `direction_text/style_text/color_text/design_prompt` 未被 `_media_image_prompt` 消费；文案入口不接收视觉设置 | 管理员给方向 / 风格文本加唯一标记 | `presets.py`、`media_ad.py` | T06 | 第 3 期 / V4.41 | 待实施 |
| F05 固定排版和固定色板削弱表达 | 静态确认；P1 | 存在。`render_ad_png` 只有「小横幅 / 其他」两套布局，`accent` 调用方未传；`_prepare_bg` 固定混合 42% 暗色；`_composite_logo` 统一透明化近白像素 | 320×50 横幅、白色 Logo、新品牌色 | `imaging.py`、`media_ad.py` | T07 | 第 3 期 / V4.41 | 待实施 |
| F06 请求比例与居中裁切不保护主体 | 静态确认 + 几何推导；P1 | 存在。`DashScopeMaaSImageProvider` 把宽高分别对齐到 1024 / 2048；`_prepare_bg` 用 cover 居中裁切，无主体保护框 | 1200×628 横幅、1080×1920 竖图 | `providers.py`、`imaging.py` | T08 | 第 4 期 / V4.42 | 待实施 |
| F09 摘要丢失事实并允许空证据继续分析 | 静态确认；P1 | 存在。`build_landing_prompt` 只送正文前 4000 字符；`_normalize_landing` 无证据 ID；抓取失败仍进入模型 | 关键订阅条款在第 4001 字符之后、空页面 | `services.py`、`schemas.py` | T11 / T12 | 第 4 期 / V4.42 | 待实施 |
| F12 浏览器长请求无法可靠恢复和归档 | 静态确认 + 运行风险；P2 | 部分存在。V4.38 已做到「切换菜单不中断 + 刷新恢复现场」，但无服务端 `job_id`、归档仍由浏览器发起；历史追加 `uniq[-80:]` 截断 | 关闭浏览器、重复请求、历史超 80 张 | `models.py`、`routers.py`、`creationSession.ts` | T16 | 第 4 期 / V4.42 | 待实施 |

> 说明书中的 `Product / Offer / Evidence / CreativeConcept / VisualBrief / SpecProfile / GenerationJob / CreativeAsset`
> 属于「新增设计需求」（不是已存在的缺陷），按批次 B / C / D 分别落地，不单独占用 F 编号，也不计入每期 3 个问题的配额。

## 分期路线图（每期 3 个问题，独立提交、独立版本通知）

| 期次 | 版本 | 问题 | 主题 | 行业/品类适配的落点 | 状态 |
|---|---|---|---|---|---|
| 第 1 期 | V4.39 | F01 / F02 / F10 | 输入与输出可信度 | 建立 `industry_profiles.py` 通用主干；压缩语义保护、品牌来源规则、归因规则对全行业一致，各 profile 只提供局部词表与价值维度 | 已完成（V4.39，2026-11-10） |
| 第 2 期 | V4.40 | F07 / F08 / F11 | 任务与规则可靠性 | 版位矩阵与媒体规则按 profile 给出偏好，不写死电商版位 | 规划中 |
| 第 3 期 | V4.41 | F03 / F04 / F05 | 创意与视觉表达 | profile 的 `visual_subject` / 配色 / 布局偏好驱动 `VisualBrief`，其它行业只改配置即可出图 | 规划中 |
| 第 4 期 | V4.42 | F06 / F09 / F12 | 事实与工程化 | profile 的 `evidence_types` 决定要核验的事实类型；服务端任务与归档全行业通用 | 规划中 |

运行时的期次状态**不在此表维护**：`backend/roadmap.py` 保存静态规划，`release_notes.py` 从 CHANGELOG 每个版本的
`**改造期次**` 字段解析「本期问题编号 + 版本」，自动把对应问题标记为已完成并绑定版本，「新版通知」据此统一展示。
即：每做完一期、写好版本更新文案并同步 git，进度自动更新，不会出现「文档说完成、系统没发布」的偏差。

## 第 1 期验证记录（V4.39 · 2026-11-10）

| 项目 | 实际执行结果 |
|---|---|
| 后端编译 | `python3 -m compileall -q backend` 通过；`import main` 正常，版本 4.39.0 |
| 确定性回归 | DB 副本上 33 项断言全通过：T01（残句阻断 / 语义压缩成功与失败两条路径）、T02（否定 / 价格 / 订阅限制保留）、T03（追踪域名、多级后缀、官方资料、结构化品牌）、T04（相对 Logo 用最终地址、og:image 待核验、JSON-LD 品牌、分析结果证据字段）、T13（停用配置不可选）、T14（回退归因与错误分类、Mock 不误标 llm） |
| HTTP 端到端 | DB 副本 TestClient 22 项断言全通过：登录 / 权限、新版通知 `current` + `roadmap`、行业画像接口、落地页分析、文案调用快照、短文案 4 版位出图且 PNG 落盘、超预算版位 `partial_success` 且不出残图、旧调用兼容、`strict_text=false` 应急开关、素材历史未受影响、viewer 权限 |
| 前端 | `tsc --noEmit` 通过；`vite build` 43 模块，253.88 kB JS / 52.51 kB CSS |
| 发版校验 | `python3 scripts/prepare_release.py --check` 通过，无警告（含改造期次 3 问题 / 版本一致性校验） |
| 未验证 | 真实付费模型调用、真实投放效果与视觉逐图人工抽检（本期未改视觉生成逻辑）；并发隔离 F11、商品一致性 F03 / F05 / F06 属后续期次 |

所有回归均在数据库副本与模拟供应商上执行，测试生成的 PNG 与临时库已清理；未修改生产数据、未读取或输出任何密钥。

## 发布门槛（沿用说明书，按每期执行）

1. 对应的确定性回归用例（T01–T16 中属于本期的）全部通过；先用模拟供应商，再注明哪些经过真实模型验证。
2. 不得通过放宽字数、增加模板、切换模型或隐藏错误获得通过；失败结果不计入合格素材。
3. 保留旧接口兼容与已有用户数据；旧分析标注 `legacy_unverified`，不自动补成已验证。
4. 每期 CHANGELOG 写明触发条件、修复前后行为、兼容变化、实际验证结果，并通过 `scripts/prepare_release.py --check`。
5. 明确列出未验证项与仍需真实样本 / 投放数据的结论，不承诺 ROAS 提升。
