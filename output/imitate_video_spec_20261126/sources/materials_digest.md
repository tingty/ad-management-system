# 资料摘要

## 资料一：AI视频重制工作台-产品功能策划.docx（用户提供的源草案）

- 来源：`/Users/leson/Desktop/资料/Work Zone/产品设计/媒体投放管理系统/新建功能/AI视频重制工作台-产品功能策划.docx`
- 版本：V1.0 草案，2026-11-26，PRD + 技术方案混合体
- 结构：执行摘要、背景与目标、产品定位、端到端管线（S1–S6）、功能模块（F1–F6）、大模型调用设计、技术方案与系统集成、非功能与合规、Q-M 待确认问题、里程碑建议（M1–M4）
- 草案要点：链接解析下载 → VLM 场景理解 → LLM 脚本策划 → 图生视频分段生成 → FFmpeg 后期合成（水印清理/字幕烧录/TTS 配音/混音）→ 预览与多规格下载；原型验证 34 秒家居广告 → 30 秒成片
- 草案技术假设（与本系统不符，需纠偏）：挂靠 RM BI System / WorkHub 侧边栏、PostgreSQL + 对象存储、经理/员工两级权限、独立异步队列 + FFmpeg worker、5 类模型含独立 VLM/图像编辑/TTS
- 草案 Q-M1~6：挂靠平台、模型供应商、目标语言、脚本确认页 prompt 编辑、自动推送投放、AI 标识默认值

## 资料二：对话中已确认的规划口径（本次任务书的主依据）

用户在本轮对话中明确的三条核心要求：
1. 原视频为广告主自主策划拍摄、有市场投放效果的专业推广视频，是最好的学习对象，应尽可能学习消化其创作方案；品牌/文案/销售/促销信息可作为选项出现在新片，但字幕与真人话术不得逐字一样，须优化调整；新片必须符合媒体平台投放规格。
2. 从原视频提取完整制作信息作为创作重要依据，但保持新片独立性与创新，不直接复制；现有视频创作未产生好案例，故新增本独立模块加强素材生成。
3. 分析须输出完整分析脚本，系统性、越详细越具象，含内容布局、结构、细节、画面要求、运动轨迹、颜色特点、拍摄手法等。

用户对 C-M1~C-M8 待确认事项答复「没有异议」，即全部按建议默认值执行。

## 资料三：现有系统架构调研结论（Explore 只读调研）

- 一级菜单：`frontend/src/App.tsx` 定义，hash 路由，新增单入口 `#/imitatevideo` 无需改 tabFromHash
- 异步任务：`backend/creative_tasks.py` 租约 worker（1.5s tick / 300s 租约 / VIDEO_CONCURRENCY=2），`generation_jobs` + `creative_batches`；`kind=="video"` 硬编码在 543/548/949 行需放开；状态机 processing/succeeded/needs_attention/failed/generation_blocked；按 provider_task_id 续查不重提
- 大模型：`backend/providers.py` get_llm_with_info/get_video；`model_configs` 仅 text/image/video 三模态、analysis/copy/image/video 四用途；无 TTS、无独立 vision；`last_test_ok` 硬门
- 视频能力：`video_claims`/`brand_lexicon`/`video_text_guard`/`video_vision_audit`(extract_frames/recognize_frames)/`asset_video_deconstruct.deconstruct_video`/`media_spec_library`；三道防线（画面零文字 + DOM 叠加 + 真实视觉 OCR）
- 存储：SQLite(WAL) + `backend/uploads/` + `/files` 静态挂载；无 yt-dlp / 系统 ffmpeg / ffprobe
- 时间：后端 `backend/timeutil.py` 统一 naive UTC，前端 `frontend/src/datetime.ts` 东八区展示
- 发版：`backend/version.py` APP_VERSION + CHANGELOG + `scripts/prepare_release.py --sync/--check` + tag + push
