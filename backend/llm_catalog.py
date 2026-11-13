"""
全球主流大模型「配置目录 + 协议感知连通测试」。

用途：
- 前端「设置 → 大模型」选择「接口协议」（openai / anthropic / gemini / openai-image / generic-image / dashscope-maas-image / generic-video），
  不再强制从厂商目录里挑一个“大模型名称”；模型版本、Key、链接均由用户自行填写，选中协议后带出默认 Base URL 与常见 Model 建议。
  ModelConfig.provider 直接存储协议串，后端通过 _resolve_protocol() 解析鉴权方式（同时兼容旧数据存厂商 key 的情况）。
- 保存后后端用 test_llm_connection() 真正发起一次最小调用：
  - 成功：返回 ok + 延迟 + 模型回包片段；
  - 失败：结构化返回 error_type（auth / permission / not_found / rate_limit / network / bad_request / unknown）
    + 中文引导 + 该厂商官方文档链接，引导用户继续补全配置。

协议（protocol）：
- openai     ：OpenAI 兼容 /chat/completions（覆盖绝大多数厂商：DeepSeek、Qwen、Mistral、Groq、OpenRouter、Ollama、vLLM …）
- anthropic  ：Anthropic /v1/messages（x-api-key 头）
- gemini     ：Google Gemini /v1beta/models/{model}:generateContent?key=
"""
from typing import Optional
import time
import httpx

# ---------------------------------------------------------------------------
# 主流大模型预设目录
# ---------------------------------------------------------------------------
# 字段说明：
#   key                : 唯一标识，存入 ModelConfig.provider
#   name              : 展示名
#   protocol          : openai / anthropic / gemini
#   default_base_url  : 默认 Base URL（用户可改）
#   base_url_editable : 是否允许用户修改 Base URL
#   models            : 常见模型名（前端作为建议）
#   api_key_label     : API Key 字段标签
#   api_key_placeholder / model_placeholder : 输入框占位
#   docs_url          : 官方 API / 控制台文档
#   setup_guide       : 配置步骤（中文）
#   notes             : 补充说明
LLM_PRESETS = [
    {
        "key": "openai", "name": "OpenAI（GPT-4o / o1）", "protocol": "openai",
        "default_base_url": "https://api.openai.com/v1",
        "base_url_editable": True,
        "models": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini", "gpt-4-turbo"],
        "api_key_label": "OpenAI API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "gpt-4o-mini",
        "docs_url": "https://platform.openai.com/docs/api-reference",
        "setup_guide": "1) 在 platform.openai.com 的 API Keys 页创建 Key；2) Base URL 保持默认 https://api.openai.com/v1；3) Model 填 gpt-4o-mini 等；4) 保存并测试。",
        "notes": "最通用的 OpenAI 兼容协议，多数第三方网关也兼容此格式。",
    },
    {
        "key": "deepseek", "name": "DeepSeek（深度求索）", "protocol": "openai",
        "default_base_url": "https://api.deepseek.com/v1",
        "base_url_editable": True,
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "api_key_label": "DeepSeek API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "deepseek-chat",
        "docs_url": "https://platform.deepseek.com/api-docs",
        "setup_guide": "1) 登录 platform.deepseek.com 获取 API Key；2) Base URL 默认 https://api.deepseek.com/v1（兼容 OpenAI）；3) Model 填 deepseek-chat 或 deepseek-reasoner；4) 保存并测试。",
        "notes": "完全兼容 OpenAI 协议，可直接用于分析/文案。",
    },
    {
        "key": "qwen", "name": "通义千问（阿里 DashScope）", "protocol": "openai",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "base_url_editable": True,
        "models": ["qwen-plus", "qwen-max", "qwen2.5-72b-instruct", "qwen-long"],
        "api_key_label": "DashScope API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "qwen-plus",
        "docs_url": "https://help.aliyun.com/zh/model-studio/",
        "setup_guide": "1) 在阿里云百炼/DashScope 控制台开通模型并获取 API Key；2) Base URL 必须使用兼容模式 https://dashscope.aliyuncs.com/compatible-mode/v1（直接填 /v1 会 404）；3) Model 填 qwen-plus / qwen-max 等；4) 保存并测试。",
        "notes": "务必使用 compatible-mode/v1 端点，否则模型找不到（404）。",
    },
    {
        "key": "qwen-maas", "name": "千问文本大模型（MaaS 专属部署）", "protocol": "openai",
        "default_base_url": "https://llm-nqw1vl6mhnuxv7d5.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
        "base_url_editable": True,
        "models": ["qwen-plus", "qwen-max", "qwen2.5-72b-instruct", "qwen-long"],
        "api_key_label": "DashScope MaaS API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "qwen-plus",
        "docs_url": "https://help.aliyun.com/zh/model-studio/",
        "setup_guide": "1) 在对应 MaaS 工作空间/部署控制台复制「绑定该工作空间的专用 API Key」（账户级 Key 会被 403 拒绝）；2) Base URL 用该工作空间的完整兼容模式地址（形如 .../compatible-mode/v1，整条即地址）；3) Model 填 qwen-plus；4) 保存并测试。",
        "notes": "专属 MaaS 工作空间部署，OpenAI 兼容协议（/compatible-mode/v1）。注意工作空间级 Key 与账户级 Key 不互通，且需与该工作空间区域一致。",
    },
    {
        "key": "qwen-intl", "name": "通义千问（DashScope 国际站 / International）", "protocol": "openai",
        "default_base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "base_url_editable": True,
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen2.5-72b-instruct", "qwen-long"],
        "api_key_label": "DashScope API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "qwen-plus",
        "docs_url": "https://www.alibabacloud.com/help/en/model-studio/",
        "setup_guide": "1) 在国际站开通模型并获取 API Key；2) Base URL 必须用兼容模式 https://dashscope-intl.aliyuncs.com/compatible-mode/v1（国际站 /api/v1 会 404）；3) Model 填 qwen-plus / qwen-max 等；4) 保存并测试。",
        "notes": "国际站域名 dashscope-intl.aliyuncs.com，同样需要 /compatible-mode/v1 路径；与国内站（dashscope.aliyuncs.com）的 Key 不互通。",
    },
    {
        "key": "moonshot", "name": "Kimi（月之暗面 Moonshot）", "protocol": "openai",
        "default_base_url": "https://api.moonshot.cn/v1",
        "base_url_editable": True,
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "api_key_label": "Moonshot API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "moonshot-v1-8k",
        "docs_url": "https://platform.moonshot.cn/docs",
        "setup_guide": "1) 在 platform.moonshot.cn 获取 API Key；2) Base URL 默认 https://api.moonshot.cn/v1；3) Model 填 moonshot-v1-8k 等；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议。",
    },
    {
        "key": "zhipu", "name": "智谱 GLM（BigModel）", "protocol": "openai",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "base_url_editable": True,
        "models": ["glm-4-plus", "glm-4-flash", "glm-4-air"],
        "api_key_label": "智谱 API Key", "api_key_placeholder": "id.secret / Bearer...",
        "model_placeholder": "glm-4-flash",
        "docs_url": "https://open.bigmodel.cn/dev/api",
        "setup_guide": "1) 在 open.bigmodel.cn 获取 API Key；2) Base URL 默认 https://open.bigmodel.cn/api/paas/v4；3) Model 填 glm-4-flash 等；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议。",
    },
    {
        "key": "baichuan", "name": "百川智能（Baichuan）", "protocol": "openai",
        "default_base_url": "https://api.baichuan-ai.com/v1",
        "base_url_editable": True,
        "models": ["Baichuan4", "Baichuan3-Turbo", "Baichuan2-53B"],
        "api_key_label": "百川 API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "Baichuan4",
        "docs_url": "https://platform.baichuan-ai.com/docs",
        "setup_guide": "1) 在平台获取 API Key；2) Base URL 默认 https://api.baichuan-ai.com/v1；3) Model 填 Baichuan4；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议。",
    },
    {
        "key": "minimax", "name": "MiniMax", "protocol": "openai",
        "default_base_url": "https://api.minimax.chat/v1",
        "base_url_editable": True,
        "models": ["abab6.5g-chat", "abab6.5s-chat"],
        "api_key_label": "MiniMax API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "abab6.5g-chat",
        "docs_url": "https://www.minimax.chat/document/API-to-Server/Proverv2",
        "setup_guide": "1) 在 minimax.chat 获取 Group ID 与 API Key；2) Base URL 默认 https://api.minimax.chat/v1；3) Model 填 abab6.5g-chat；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议。",
    },
    {
        "key": "siliconflow", "name": "硅基流动（SiliconFlow）", "protocol": "openai",
        "default_base_url": "https://api.siliconflow.cn/v1",
        "base_url_editable": True,
        "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct", "meta-llama/Llama-3.3-70B-Instruct"],
        "api_key_label": "SiliconFlow API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "deepseek-ai/DeepSeek-V3",
        "docs_url": "https://docs.siliconflow.cn/",
        "setup_guide": "1) 在 siliconflow.cn 获取 API Key；2) Base URL 默认 https://api.siliconflow.cn/v1；3) Model 填 deepseek-ai/DeepSeek-V3 等（含组织前缀）；4) 保存并测试。",
        "notes": "聚合多家开源模型，兼容 OpenAI 协议；Model 名需带组织前缀。",
    },
    {
        "key": "groq", "name": "Groq（极速推理）", "protocol": "openai",
        "default_base_url": "https://api.groq.com/openai/v1",
        "base_url_editable": True,
        "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
        "api_key_label": "Groq API Key", "api_key_placeholder": "gsk_...",
        "model_placeholder": "llama-3.3-70b-versatile",
        "docs_url": "https://console.groq.com/docs/openai",
        "setup_guide": "1) 在 console.groq.com 创建 Key；2) Base URL 默认 https://api.groq.com/openai/v1；3) Model 填 llama-3.3-70b-versatile；4) 保存并测试。",
        "notes": "路径含 /openai/v1，注意别漏掉。",
    },
    {
        "key": "openrouter", "name": "OpenRouter（聚合）", "protocol": "openai",
        "default_base_url": "https://openrouter.ai/api/v1",
        "base_url_editable": True,
        "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-70b-instruct"],
        "api_key_label": "OpenRouter API Key", "api_key_placeholder": "sk-or-...",
        "model_placeholder": "openai/gpt-4o",
        "docs_url": "https://openrouter.ai/docs",
        "setup_guide": "1) 在 openrouter.ai 获取 Key；2) Base URL 默认 https://openrouter.ai/api/v1；3) Model 填 openai/gpt-4o 等（含厂商前缀）；4) 保存并测试。",
        "notes": "通过单一接口调用数百家模型，Model 名带厂商前缀。",
    },
    {
        "key": "together", "name": "Together AI", "protocol": "openai",
        "default_base_url": "https://api.together.xyz/v1",
        "base_url_editable": True,
        "models": ["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
        "api_key_label": "Together API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "meta-llama/Llama-3.3-70B-Instruct",
        "docs_url": "https://docs.together.ai/",
        "setup_guide": "1) 在 together.ai 获取 Key；2) Base URL 默认 https://api.together.xyz/v1；3) Model 填 meta-llama/Llama-3.3-70B-Instruct；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议。",
    },
    {
        "key": "perplexity", "name": "Perplexity（联网问答）", "protocol": "openai",
        "default_base_url": "https://api.perplexity.ai",
        "base_url_editable": True,
        "models": ["sonar", "sonar-pro", "llama-3.1-sonar-large-32k-online"],
        "api_key_label": "Perplexity API Key", "api_key_placeholder": "pplx-...",
        "model_placeholder": "sonar-pro",
        "docs_url": "https://docs.perplexity.ai/",
        "setup_guide": "1) 在 perplexity.ai 获取 Key；2) Base URL 默认 https://api.perplexity.ai；3) Model 填 sonar-pro；4) 保存并测试。",
        "notes": "Base URL 不含 /v1，调用时自动追加 /chat/completions。",
    },
    {
        "key": "mistral", "name": "Mistral AI", "protocol": "openai",
        "default_base_url": "https://api.mistral.ai/v1",
        "base_url_editable": True,
        "models": ["mistral-large-latest", "mistral-small-latest", "open-mistral-7b"],
        "api_key_label": "Mistral API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "mistral-large-latest",
        "docs_url": "https://docs.mistral.ai/",
        "setup_guide": "1) 在 console.mistral.ai 获取 Key；2) Base URL 默认 https://api.mistral.ai/v1；3) Model 填 mistral-large-latest；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议。",
    },
    {
        "key": "ollama", "name": "Ollama（本地部署）", "protocol": "openai",
        "default_base_url": "http://localhost:11434/v1",
        "base_url_editable": True,
        "models": ["llama3", "qwen2.5", "mistral", "deepseek-r1"],
        "api_key_label": "API Key（本地可留空）", "api_key_placeholder": "ollama（可填任意非空串或留空取决于版本）",
        "model_placeholder": "llama3",
        "docs_url": "https://github.com/ollama/ollama/blob/main/docs/openai.md",
        "setup_guide": "1) 本地安装并运行 Ollama（ollama run llama3）；2) Base URL 默认 http://localhost:11434/v1；3) Model 填已拉取的模型名（如 llama3）；4) 部分版本需填任意 API Key，可填 ollama；5) 保存并测试。",
        "notes": "本地推理无需公网；注意服务器需能访问该地址（容器内需用宿主 IP 而非 localhost）。",
    },
    {
        "key": "vllm", "name": "vLLM / 自建 OpenAI 兼容服务", "protocol": "openai",
        "default_base_url": "http://localhost:8000/v1",
        "base_url_editable": True,
        "models": ["default", "Qwen2.5-72B-Instruct"],
        "api_key_label": "API Key（自建有则填）", "api_key_placeholder": "EMPTY（可留空）",
        "model_placeholder": "default",
        "docs_url": "https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html",
        "setup_guide": "1) 以 --served-model-name 启动 vLLM OpenAI 服务；2) Base URL 填服务地址（如 http://host:8000/v1）；3) Model 填 served-model-name；4) 保存并测试。",
        "notes": "适用于任何自建/第三方 OpenAI 兼容网关。",
    },
    {
        "key": "anthropic", "name": "Anthropic（Claude）", "protocol": "anthropic",
        "default_base_url": "https://api.anthropic.com",
        "base_url_editable": True,
        "models": ["claude-3-5-sonnet-latest", "claude-3-haiku-latest", "claude-opus-4-20250514"],
        "api_key_label": "Anthropic API Key", "api_key_placeholder": "sk-ant-...",
        "model_placeholder": "claude-3-5-sonnet-latest",
        "docs_url": "https://docs.anthropic.com/en/api/getting-started",
        "setup_guide": "1) 在 console.anthropic.com 获取 Key；2) Base URL 默认 https://api.anthropic.com；3) Model 填 claude-3-5-sonnet-latest；4) 保存并测试。",
        "notes": "使用 Anthropic 自有 /v1/messages 协议（x-api-key 头），后端已专门适配。",
    },
    {
        "key": "google", "name": "Google Gemini", "protocol": "gemini",
        "default_base_url": "https://generativelanguage.googleapis.com",
        "base_url_editable": True,
        "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
        "api_key_label": "Gemini API Key", "api_key_placeholder": "AIza...",
        "model_placeholder": "gemini-1.5-flash",
        "docs_url": "https://ai.google.dev/api/generate-content",
        "setup_guide": "1) 在 aistudio.google.com 获取 API Key；2) Base URL 默认 https://generativelanguage.googleapis.com；3) Model 填 gemini-1.5-flash 等；4) 保存并测试。",
        "notes": "使用 Gemini 自有 generateContent 协议，Key 以 ?key= 追加，后端已专门适配。",
    },
    # ----------------------------- 新增：国产 / 海外主流厂商（OpenAI 兼容或专属协议） -----------------------------
    {
        "key": "doubao", "name": "豆包 / 火山方舟（字节）", "protocol": "openai",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v1",
        "base_url_editable": True,
        "models": ["doubao-seed-1.6", "doubao-pro-32k", "doubao-vision-pro-32k"],
        "api_key_label": "火山方舟 API Key（ARK_API_KEY）", "api_key_placeholder": "xxxxx",
        "model_placeholder": "doubao-seed-1.6",
        "docs_url": "https://www.volcengine.com/docs/82379",
        "setup_guide": "1) 火山方舟控制台创建推理接入点并获取 ARK_API_KEY；2) Base URL 默认 https://ark.cn-beijing.volces.com/api/v1；3) Model 填接入点对应的模型名（如 doubao-seed-1.6）；4) 保存并测试。",
        "notes": "字节系模型，国内访问稳定，适合中文创意/落地页分析；完全兼容 OpenAI 协议。",
    },
    {
        "key": "hunyuan", "name": "腾讯混元（Hunyuan）", "protocol": "openai",
        "default_base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "base_url_editable": True,
        "models": ["hunyuan-turbo", "hunyuan-pro", "hunyuan-standard"],
        "api_key_label": "腾讯云 SecretId/Key 或混元 API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "hunyuan-turbo",
        "docs_url": "https://cloud.tencent.com/document/product/1729",
        "setup_guide": "1) 腾讯云开通混元大模型并获取 Key；2) Base URL 默认 https://api.hunyuan.cloud.tencent.com/v1；3) Model 填 hunyuan-turbo 等；4) 保存并测试。",
        "notes": "腾讯云混元，兼容 OpenAI 协议。",
    },
    {
        "key": "ernie", "name": "百度文心一言 / 千帆（ERNIE）", "protocol": "openai",
        "default_base_url": "https://qianfan.baidubce.com/v2",
        "base_url_editable": True,
        "models": ["ernie-4.5-8k-preview", "ernie-4.0-8k", "ernie-speed-128k"],
        "api_key_label": "千帆 API Key（AK/SK 换取 access_token）", "api_key_placeholder": "xxxxx",
        "model_placeholder": "ernie-4.0-8k",
        "docs_url": "https://cloud.baidu.com/doc/WENXINWORKSHOP",
        "setup_guide": "1) 百度智能云千帆控制台开通并获取 AK/SK；2) Base URL 默认 https://qianfan.baidubce.com/v2（OpenAI 兼容网关）；3) Model 填 ernie-4.0-8k 等；4) 保存并测试。",
        "notes": "千帆已提供 OpenAI 兼容 /v2 网关，可直接按 OpenAI 协议调用 ERNIE 系列。",
    },
    {
        "key": "yi", "name": "零一万物 Yi（01.ai）", "protocol": "openai",
        "default_base_url": "https://api.lingyiwanwu.com/v1",
        "base_url_editable": True,
        "models": ["yi-lightning", "yi-large", "yi-medium"],
        "api_key_label": "Yi API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "yi-lightning",
        "docs_url": "https://platform.lingyiwanwu.com/docs",
        "setup_guide": "1) 零一万物开放平台获取 Key；2) Base URL 默认 https://api.lingyiwanwu.com/v1；3) Model 填 yi-lightning；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议，中文与代码能力均衡。",
    },
    {
        "key": "step", "name": "阶跃星辰 StepFun", "protocol": "openai",
        "default_base_url": "https://api.stepfun.com/v1",
        "base_url_editable": True,
        "models": ["step-2", "step-1.5-flash", "step-1.5v-mini"],
        "api_key_label": "StepFun API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "step-2",
        "docs_url": "https://www.stepfun.com/docs",
        "setup_guide": "1) 阶跃星辰开放平台获取 Key；2) Base URL 默认 https://api.stepfun.com/v1；3) Model 填 step-2；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议，含多模态版本。",
    },
    {
        "key": "cohere", "name": "Cohere（Command R+）", "protocol": "openai",
        "default_base_url": "https://api.cohere.ai/compatibility/v1",
        "base_url_editable": True,
        "models": ["command-r-plus", "command-r", "command-a"],
        "api_key_label": "Cohere API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "command-r-plus",
        "docs_url": "https://docs.cohere.com/docs",
        "setup_guide": "1) cohere.com 获取 Key；2) Base URL 默认 https://api.cohere.ai/compatibility/v1（兼容网关）；3) Model 填 command-r-plus；4) 保存并测试。",
        "notes": "需使用其 OpenAI 兼容网关路径 /compatibility/v1。",
    },
    {
        "key": "xai", "name": "xAI（Grok）", "protocol": "openai",
        "default_base_url": "https://api.x.ai/v1",
        "base_url_editable": True,
        "models": ["grok-3", "grok-3-mini", "grok-2-latest"],
        "api_key_label": "xAI API Key", "api_key_placeholder": "xai-xxxxx",
        "model_placeholder": "grok-3",
        "docs_url": "https://docs.x.ai",
        "setup_guide": "1) x.ai 控制台获取 Key；2) Base URL 默认 https://api.x.ai/v1；3) Model 填 grok-3；4) 保存并测试。",
        "notes": "完全兼容 OpenAI 协议。",
    },
    {
        "key": "meta-llama", "name": "Llama 4（Meta）", "protocol": "openai",
        "default_base_url": "https://api.together.xyz/v1",
        "base_url_editable": True,
        "models": ["meta-llama/Llama-4-Scout-17B-16E-Instruct", "meta-llama/Llama-4-Maverick-17B-128E-Instruct"],
        "api_key_label": "Llama 4 托管平台 API Key（Together / Groq / Fireworks / Ollama 等）", "api_key_placeholder": "sk-...",
        "model_placeholder": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "docs_url": "https://www.llama.com",
        "setup_guide": "1) Llama 4 为开放权重模型，需通过 OpenAI 兼容网关调用；2) 在 Together / Groq / Fireworks / SambaNova 等平台获取 API Key（示例默认 Together https://api.together.xyz/v1）；3) Model 填对应模型名（如 meta-llama/Llama-4-Scout-17B-16E-Instruct）；4) 本地可用 Ollama/vLLM 部署，Base URL 改为 http://localhost:11434/v1；5) 保存并测试。",
        "notes": "Llama 4 为开放权重，不在任何单一厂商云端独占；选择你所在的托管平台填对应 Base URL 即可。",
    },
    {
        "key": "gemma", "name": "Gemma（Google 开放权重）", "protocol": "openai",
        "default_base_url": "https://api.groq.com/openai/v1",
        "base_url_editable": True,
        "models": ["gemma2-9b-it", "gemma-7b-it"],
        "api_key_label": "Gemma 托管平台 API Key（Groq / Google AI Studio / 自建等）", "api_key_placeholder": "gsk_... 或 AIza...",
        "model_placeholder": "gemma2-9b-it",
        "docs_url": "https://ai.google.dev/gemma",
        "setup_guide": "1) Gemma 为 Google 开放权重模型，可通过 Groq（https://api.groq.com/openai/v1，Model 填 gemma2-9b-it）或 Google AI Studio（Gemini 协议）调用；2) 也可本地用 Ollama/vLLM 部署；3) 选择对应平台填 Key 与 Base URL；4) 保存并测试。",
        "notes": "Gemma 开放权重，多平台可托管；示例默认 Groq 极速推理网关。",
    },
    {
        "key": "nvidia-nim", "name": "NVIDIA NIM（自建/云端推理）", "protocol": "openai",
        "default_base_url": "https://integrate.api.nvidia.com/v1",
        "base_url_editable": True,
        "models": ["meta/llama-3.3-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct", "deepseek-ai/deepseek-r1"],
        "api_key_label": "NVIDIA API Key", "api_key_placeholder": "nvapi-xxxxx",
        "model_placeholder": "meta/llama-3.3-70b-instruct",
        "docs_url": "https://developer.nvidia.com/nim",
        "setup_guide": "1) build.nvidia.com 获取 Key；2) Base URL 默认 https://integrate.api.nvidia.com/v1；3) Model 填托管模型名（带组织前缀）；4) 保存并测试。",
        "notes": "聚合大量开源模型，兼容 OpenAI 协议；Model 名需带组织前缀。",
    },
    {
        "key": "cloudflare-ai", "name": "Cloudflare Workers AI", "protocol": "openai",
        "default_base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "base_url_editable": True,
        "models": ["@cf/meta/llama-3.3-70b-instruct", "@cf/qwen/qwen2.5-72b-instruct", "@cf/deepseek-ai/deepseek-r1-distill-70b"],
        "api_key_label": "Cloudflare API Token", "api_key_placeholder": "xxxxx",
        "model_placeholder": "@cf/meta/llama-3.3-70b-instruct",
        "docs_url": "https://developers.cloudflare.com/workers-ai",
        "setup_guide": "1) Cloudflare 控制台获取 Account ID 与 API Token；2) 把 Base URL 中的 {account_id} 替换为你的 Account ID；3) Model 填 @cf/... 系列；4) 保存并测试。",
        "notes": "Base URL 需替换 {account_id}；使用 Cloudflare 边缘推理，免费额度友好。",
    },
    {
        "key": "novita", "name": "Novita AI", "protocol": "openai",
        "default_base_url": "https://api.novita.ai/v3/openai",
        "base_url_editable": True,
        "models": ["meta-llama/llama-3.3-70b-instruct", "deepseek/deepseek-v3", "qwen/qwen2.5-72b-instruct"],
        "api_key_label": "Novita API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "meta-llama/llama-3.3-70b-instruct",
        "docs_url": "https://novita.ai/docs",
        "setup_guide": "1) novita.ai 获取 Key；2) Base URL 默认 https://api.novita.ai/v3/openai；3) Model 填含组织前缀的模型名；4) 保存并测试。",
        "notes": "聚合开源模型，兼容 OpenAI 协议。",
    },
    {
        "key": "upstage", "name": "Upstage（Solar）", "protocol": "openai",
        "default_base_url": "https://api.upstage.ai/v1",
        "base_url_editable": True,
        "models": ["solar-pro2-preview", "solar-mini", "solar-pro"],
        "api_key_label": "Upstage API Key", "api_key_placeholder": "up_xxxxx",
        "model_placeholder": "solar-pro2-preview",
        "docs_url": "https://developers.upstage.ai",
        "setup_guide": "1) upstage.ai 获取 Key；2) Base URL 默认 https://api.upstage.ai/v1；3) Model 填 solar-pro2-preview；4) 保存并测试。",
        "notes": "韩国厂商，兼容 OpenAI 协议，韩英能力突出。",
    },
    {
        "key": "lemonfox", "name": "Lemonfox（柠檬熊，便宜聚合）", "protocol": "openai",
        "default_base_url": "https://api.lemonfox.ai/v1",
        "base_url_editable": True,
        "models": ["lemonfox-mini", "gpt-4o-mini", "deepseek-chat"],
        "api_key_label": "Lemonfox API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "lemonfox-mini",
        "docs_url": "https://docs.lemonfox.ai",
        "setup_guide": "1) lemonfox.ai 获取 Key；2) Base URL 默认 https://api.lemonfox.ai/v1；3) Model 填 lemonfox-mini 或代理的其它模型；4) 保存并测试。",
        "notes": "低成本聚合网关，兼容 OpenAI 协议，适合批量素材生成降本。",
    },
    {
        "key": "ppio", "name": "PPIO 派欧云", "protocol": "openai",
        "default_base_url": "https://api.ppio.cn/v1",
        "base_url_editable": True,
        "models": ["deepseek/deepseek-v3", "qwen/qwen2.5-72b-instruct", "meta-llama/llama-3.3-70b-instruct"],
        "api_key_label": "PPIO API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "deepseek/deepseek-v3",
        "docs_url": "https://www.ppio.cn/docs",
        "setup_guide": "1) ppio.cn 获取 Key；2) Base URL 默认 https://api.ppio.cn/v1；3) Model 填含组织前缀的模型名；4) 保存并测试。",
        "notes": "兼容 OpenAI 协议，价格低廉。",
    },
    {
      "key": "custom", "name": "自定义（OpenAI 兼容）", "protocol": "openai",
        "default_base_url": "",
        "base_url_editable": True,
        "models": [],
        "api_key_label": "API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "你的 model 名",
        "docs_url": "",
        "setup_guide": "适用于任何兼容 OpenAI /chat/completions 的网关（vLLM、本地部署、第三方代理、Azure 等）。请填写你的 Base URL、Model 与 API Key。",
        "notes": "通用兜底：只要端点暴露 /chat/completions 即可。",
    },
]

_PRESET_MAP = {p["key"]: p for p in LLM_PRESETS}


def get_preset(key: str) -> Optional[dict]:
    """按 provider key 取预设；未知返回 None（按 openai 兼容处理）。"""
    return _PRESET_MAP.get(key)


def protocol_of(provider: str) -> str:
    p = get_preset(provider)
    return p["protocol"] if p else "openai"


# 全部已知协议：用于判断「存储的 provider 字段本身就是协议串」（新配置直接存协议，
# 不再依赖厂商目录），从而让 get_llm/get_image/test 都能正确解析，无需再选厂商。
ALL_PROTOCOLS = {
    "openai", "anthropic", "gemini",
    "openai-image", "dashscope-maas-image", "generic-image", "generic-video",
}


def _resolve_protocol(provider: str) -> str:
    """把存储的 provider 字段解析为实际协议。

    - 若本身就是协议串（新配置直接存协议），原样返回；
    - 否则按厂商目录 / 文生图目录 / 文生视频目录查协议（兼容旧数据存的是厂商 key）；
    - 都查不到按 OpenAI 兼容处理。
    """
    if not provider:
        return "openai"
    if provider in ALL_PROTOCOLS:
        return provider
    p = get_preset(provider) or get_image_preset(provider) or get_video_preset(provider)
    return p["protocol"] if p else "openai"


def modality_of(protocol: str) -> str:
    """协议 → 模态分类，供前端按模态决定可选的「用途」范围。"""
    if protocol in ("openai-image", "generic-image", "dashscope-maas-image"):
        return "image"
    if protocol == "generic-video":
        return "video"
    return "text"


# 主流大模型厂商（用户配置时优先展示的「推荐」分组）。
# 覆盖：GPT、Claude、Gemini、Grok、Command R、Llama4、Mistral、Gemma、
#       通义千问、Kimi、DeepSeek、GLM、文心一言、MiniMax、豆包、腾讯混元、百川大模型。
MAINSTREAM_KEYS = {
    "openai", "anthropic", "google", "xai", "cohere", "mistral", "meta-llama",
    "qwen", "qwen-maas", "moonshot", "deepseek", "zhipu", "ernie", "minimax", "doubao",
    "hunyuan", "baichuan", "gemma", "aliyun-maas-video",
}


def _with_mainstream(p: dict) -> dict:
    d = dict(p)
    d["mainstream"] = p.get("key") in MAINSTREAM_KEYS
    return d


def get_all_presets() -> list:
    """全部预设（文本 + 文生图 + 文生视频），供前端「大模型」下拉一次性拉取。"""
    return [_with_mainstream(p) for p in (LLM_PRESETS + IMAGE_PRESETS + VIDEO_PRESETS)]


# 不同协议默认需要的「厂商专属附加字段」；预设本身也可通过 extra_fields 覆盖。
# 这里统一在后端 preset 接口输出时附加，避免每个预设重复声明。
_PROTOCOL_EXTRA = {
    "generic-image": [{
        "key": "endpoint", "label": "自定义端点路径（可选）",
        "placeholder": "/images/generations 或 /sdapi/v1/txt2img",
        "hint": "留空使用默认端点；Stable Diffusion 等需填 /sdapi/v1/txt2img。",
    }],
    "generic-video": [{
        "key": "endpoint", "label": "自定义端点路径（可选）",
        "placeholder": "/video/generations",
        "hint": "留空使用默认端点 /video/generations。",
    }],
}


# ---------------------------------------------------------------------------
# 文生图（Text-to-Image）模型目录
# ---------------------------------------------------------------------------
# protocol:
#   openai-image   : OpenAI /images/generations（DALL·E 3/2、Azure OpenAI、多数网关兼容）
#   generic-image  : 通用图像端点，POST {base_url}{endpoint}，默认 /images/generations；
#                    不同厂商（通义万相 / 智谱 CogView / SD / Replicate 等）路径与字段差异大，
#                    由 provider 读取 params.endpoint 调整，并尽量兼容 {model, prompt, size} 形态。
#   dashscope-maas-image : 阿里云 MaaS 多模态生成（qwen-image 系列）；base_url 即完整 endpoint，
#                    请求体为 messages 数组、parameters.size=W*H，同步返回签名 OSS URL 需立即下载落盘。
IMAGE_PRESETS = [
    {
        "key": "dalle3", "name": "OpenAI DALL·E 3 / 2", "protocol": "openai-image",
        "default_base_url": "https://api.openai.com/v1", "base_url_editable": True,
        "models": ["dall-e-3", "dall-e-2"],
        "api_key_label": "OpenAI API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "dall-e-3",
        "docs_url": "https://platform.openai.com/docs/api-reference/images",
        "setup_guide": "1) platform.openai.com 创建 Key；2) Base URL 默认 https://api.openai.com/v1；3) Model 填 dall-e-3；4) 保存并测试。",
        "notes": "标准 OpenAI 图像协议，后端直接 POST /images/generations，自动裁剪到目标尺寸并叠加文案。",
    },
    {
        "key": "azure-dalle", "name": "Azure OpenAI（DALL·E）", "protocol": "openai-image",
        "default_base_url": "https://YOUR-RESOURCE.openai.azure.com/openai", "base_url_editable": True,
        "models": ["dall-e-3", "dall-e-2"],
        "api_key_label": "Azure OpenAI Key", "api_key_placeholder": "xxxx...",
        "model_placeholder": "dall-e-3",
        "docs_url": "https://learn.microsoft.com/azure/ai-services/openai/dall-e-quickstart",
        "setup_guide": "1) Azure 门户创建 OpenAI 资源；2) Base URL 形如 https://<res>.openai.azure.com/openai；3) Model 填部署名；4) 调用自动追加 /images/generations?api-version。",
        "notes": "Endpoint 需带 api-version 查询参数，后端已拼接到请求地址。",
    },
    {
        "key": "wanx", "name": "通义万相（阿里 DashScope）", "protocol": "generic-image",
        "default_base_url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
        "base_url_editable": True,
        "models": ["wanx-v1", "wanx2.1-t2i-turbo", "wanx2.1-t2i-plus"],
        "api_key_label": "DashScope API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "wanx-v1",
        "docs_url": "https://help.aliyun.com/zh/model-studio/user-guide/text-to-image",
        "setup_guide": "1) 百炼/DashScope 开通万相并获取 Key；2) Base URL 用上面的 image-synthesis 任务地址；3) Model 填 wanx-v1；4) 注意万相是异步任务 API，需轮询，当前后端按一次性返回兼容处理，建议先用自定义端点验证。",
        "notes": "万相为异步任务式（提交任务→轮询结果），与 OpenAI 一次性返回不同；如回调结构不同，请用「custom-image」自行配置 endpoint 与字段。",
    },
    {
        "key": "cogview", "name": "智谱 CogView", "protocol": "generic-image",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4/images/generations",
        "base_url_editable": True,
        "models": ["cogview-3-plus", "cogview-3", "cogview-3-flash"],
        "api_key_label": "智谱 API Key", "api_key_placeholder": "id.secret / Bearer...",
        "model_placeholder": "cogview-3-plus",
        "docs_url": "https://open.bigmodel.cn/dev/api/images",
        "setup_guide": "1) open.bigmodel.cn 获取 Key；2) Base URL 默认 .../images/generations；3) Model 填 cogview-3-plus；4) 保存并测试。",
        "notes": "采用类 OpenAI 图像端点，后端默认按 {model, prompt, size} 发送。",
    },
    {
        "key": "sd", "name": "Stable Diffusion（A1111 / ComfyUI）", "protocol": "generic-image",
        "default_base_url": "http://localhost:7860", "base_url_editable": True,
        "models": ["sd_xl_base_1.0", "majicmixRealistic_v7", "default"],
        "api_key_label": "API Key（本地可留空）", "api_key_placeholder": "可留空",
        "model_placeholder": "sd_xl_base_1.0",
        "docs_url": "https://github.com/AUTOMATIC1111/automatic1111/wiki/API",
        "setup_guide": "1) 本地/服务器启动 Automatic1111 并开启 --api（或 ComfyUI 的 API 模式）；2) Base URL 填 http://host:7860；3) Model 填已加载的 checkpoint；4) 端点默认 /sdapi/v1/txt2img。注意容器内需用宿主 IP 而非 localhost。",
        "notes": "默认 endpoint 为 /sdapi/v1/txt2img；如需更换路径，在「参数(JSON)」里填 endpoint，例如 {\"endpoint\":\"/sdapi/v1/txt2img\"}。本地部署无需公网。",
    },
    {
        "key": "flux-replicate", "name": "Flux（Replicate）", "protocol": "generic-image",
        "default_base_url": "https://api.replicate.com/v1/predictions", "base_url_editable": True,
        "models": ["black-forest-labs/flux-schnell", "black-forest-labs/flux1.1-pro"],
        "api_key_label": "Replicate API Token", "api_key_placeholder": "r8_...",
        "model_placeholder": "black-forest-labs/flux-schnell",
        "docs_url": "https://replicate.com/docs/reference/api",
        "setup_guide": "1) replicate.com 获取 Token；2) Base URL 默认 https://api.replicate.com/v1/predictions；3) Model 填模型名；4) Replicate 为异步预测，建议先验证返回结构后用 custom-image 微调。",
        "notes": "Replicate 预测是异步的，标准测试仅验证可达性与鉴权，实际出图需轮询；当前后端按一次性返回兼容。",
    },
    {
        "key": "jimeng-image", "name": "即梦 / 火山方舟（图像）", "protocol": "generic-image",
        "default_base_url": "https://visual.volcengineapi.com", "base_url_editable": True,
        "models": ["jimeng-2.1", "jimeng-2.0-pro"],
        "api_key_label": "火山引擎 API Key", "api_key_placeholder": "AK...",
        "model_placeholder": "jimeng-2.1",
        "docs_url": "https://www.volcengine.com/docs/82379",
        "setup_guide": "1) 火山引擎开通方舟/即梦并获取 AK/SK；2) Base URL 默认 https://visual.volcengineapi.com；3) Model 填即梦模型名；4) 实际调用需签名，建议先用自定义端点验证。",
        "notes": "火山方舟请求需鉴权签名，测试仅验证可达性；生产接入建议封装签名。",
    },
    {
        "key": "custom-image", "name": "自定义图像模型（OpenAI 兼容）", "protocol": "generic-image",
        "default_base_url": "", "base_url_editable": True,
        "models": [],
        "api_key_label": "API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "你的图像模型名",
        "docs_url": "",
        "setup_guide": "适用于任何暴露 {base_url}{endpoint}（默认 /images/generations）且接受 {model, prompt, size} 的图像服务。如需自定义路径/字段，在「参数(JSON)」里填 endpoint，例如 {\"endpoint\":\"/sdapi/v1/txt2img\"}。",
        "notes": "通用兜底：只要端点能接收 prompt 并返回图像（b64/json 或 url）即可。",
    },
    {
        "key": "qwen-image-maas", "name": "通义千问图像（DashScope MaaS 多模态）", "protocol": "dashscope-maas-image",
        "default_base_url": "https://llm-nqw1vl6mhnuxv7d5.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        "base_url_editable": True,
        "models": ["qwen-image-3.0", "qwen-image-3.0-pro"],
        "api_key_label": "DashScope MaaS API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "qwen-image-3.0",
        "docs_url": "https://help.aliyun.com/zh/model-studio/",
        "setup_guide": "1) 在对应 MaaS 工作空间/部署控制台复制「绑定该工作空间的专用 API Key」（账户级 Key 会被 403 拒绝）；2) Base URL 用该工作空间的完整多模态生成地址（形如 .../api/v1/services/aigc/multimodal-generation/generation，整条即地址，无需再附加路径）；3) Model 填 qwen-image-3.0；4) 保存并测试。",
        "notes": "专属协议 dashscope-maas-image：同步调用、请求体为 messages 数组、返回签名 OSS 临时 URL 立即下载。仅同步（禁异步）。注意不同 MaaS 工作空间 Key 不互通，且需与该工作空间区域一致。",
    },
    # ----------------------------- 新增：文生图厂商 -----------------------------
    {
        "key": "stability", "name": "Stability AI（SD3.5 / Stable Image）", "protocol": "openai-image",
        "default_base_url": "https://api.stability.ai/v1", "base_url_editable": True,
        "models": ["sd3.5-large", "stable-image-ultra", "stable-diffusion-3-5-large"],
        "api_key_label": "Stability API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "stable-image-ultra",
        "docs_url": "https://platform.stability.ai/docs/api-reference",
        "setup_guide": "1) platform.stability.ai 创建 Key；2) Base URL 默认 https://api.stability.ai/v1；3) Model 填 stable-image-ultra；4) 保存并测试。",
        "notes": "Stability 已提供 OpenAI 兼容 /images/generations 端点，后端按 DALL·E 兼容协议调用。",
    },
    {
        "key": "ideogram", "name": "Ideogram（文字渲染强）", "protocol": "openai-image",
        "default_base_url": "https://api.ideogram.ai", "base_url_editable": True,
        "models": ["ideogram-v2", "ideogram-v3", "ideogram-turbo"],
        "api_key_label": "Ideogram API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "ideogram-v2",
        "docs_url": "https://developer.ideogram.ai",
        "setup_guide": "1) ideogram.ai 获取 Key；2) Base URL 默认 https://api.ideogram.ai；3) Model 填 ideogram-v2；4) 保存并测试。",
        "notes": "擅长图中文字/海报排版，OpenAI 兼容 /images/generations。",
    },
    {
        "key": "recraft", "name": "Recraft（品牌矢量/图标）", "protocol": "openai-image",
        "default_base_url": "https://api.recraft.ai/v1", "base_url_editable": True,
        "models": ["recraft-20b", "recraft-v3", "recraft-18b"],
        "api_key_label": "Recraft API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "recraft-20b",
        "docs_url": "https://www.recraft.ai/docs",
        "setup_guide": "1) recraft.ai 获取 Key；2) Base URL 默认 https://api.recraft.ai/v1；3) Model 填 recraft-20b；4) 保存并测试。",
        "notes": "OpenAI 兼容 /images/generations，适合品牌风素材与矢量图标。",
    },
    {
        "key": "tencent-hunyuan-image", "name": "腾讯混元图像", "protocol": "generic-image",
        "default_base_url": "https://api.hunyuan.cloud.tencent.com/hy/v1", "base_url_editable": True,
        "models": ["hunyuan-image", "hunyuan-image-3.0"],
        "api_key_label": "腾讯云混元 API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "hunyuan-image",
        "docs_url": "https://cloud.tencent.com/document/product/1729",
        "setup_guide": "1) 腾讯云开通混元图像并获取 Key；2) Base URL 默认 https://api.hunyuan.cloud.tencent.com/hy/v1；3) Model 填 hunyuan-image；4) 保存并测试。",
        "notes": "采用类 OpenAI 图像端点，后端默认按 {model, prompt, size} 发送。",
    },
    {
        "key": "lemonfox-image", "name": "Lemonfox 图像（便宜聚合）", "protocol": "generic-image",
        "default_base_url": "https://api.lemonfox.ai/v1", "base_url_editable": True,
        "models": ["flux-1-schnell", "sdxl", "stable-diffusion-3.5"],
        "api_key_label": "Lemonfox API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "flux-1-schnell",
        "docs_url": "https://docs.lemonfox.ai",
        "setup_guide": "1) lemonfox.ai 获取 Key；2) Base URL 默认 https://api.lemonfox.ai/v1；3) Model 填 flux-1-schnell；4) 端点默认 /images/generations，如不同请在「参数(JSON)」填 endpoint。",
        "notes": "聚合 FLUX/SD 等图像模型，兼容 {model, prompt, size}。",
    },
    {
        "key": "ai302-image", "name": "302.AI 图像", "protocol": "generic-image",
        "default_base_url": "https://api.302.ai/v1", "base_url_editable": True,
        "models": ["flux", "sdxl", "sd3"],
        "api_key_label": "302.AI API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "flux",
        "docs_url": "https://302.ai",
        "setup_guide": "1) 302.ai 获取 Key；2) Base URL 默认 https://api.302.ai/v1；3) Model 填 flux；4) 端点默认 /images/generations，如不同请在「参数(JSON)」填 endpoint。",
        "notes": "聚合多家图像模型，兼容 {model, prompt, size}；部分模型需自定义 endpoint。",
    },
    {
        "key": "minimax-image", "name": "MiniMax 图像（image-01）", "protocol": "generic-image",
        "default_base_url": "https://api.minimax.chat/v1/image_generation", "base_url_editable": True,
        "models": ["image-01", "image-01-live"],
        "api_key_label": "MiniMax API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "image-01",
        "docs_url": "https://www.minimax.chat/document/API-to-Server/Proverv2",
        "setup_guide": "1) minimax.chat 获取 Key 与 Group ID；2) Base URL 默认 https://api.minimax.chat/v1/image_generation；3) Model 填 image-01；4) 保存并测试。",
        "notes": "MiniMax 图像端点路径为 /image_generation，与通用 /images/generations 不同，请在「参数(JSON)」填 endpoint=\"/image_generation\"。",
    },
]

# ---------------------------------------------------------------------------
# 文生视频（Text-to-Video）模型目录
# ---------------------------------------------------------------------------
# protocol: generic-video —— POST {base_url}/video/generations（兼容 Runway/可灵/Pika 等最小契约）
VIDEO_PRESETS = [
    {
        "key": "runway", "name": "Runway（Gen-3 / Gen-4）", "protocol": "generic-video",
        "default_base_url": "https://api.runwayml.com/v1", "base_url_editable": True,
        "models": ["gen3a-turbo", "gen3", "gen4-turbo"],
        "api_key_label": "Runway API Key", "api_key_placeholder": "key_...",
        "model_placeholder": "gen3a-turbo",
        "docs_url": "https://dev.runwayml.com/docs/getting-started",
        "setup_guide": "1) runwayml.com 获取 API Key；2) Base URL 默认 https://api.runwayml.com/v1；3) Model 填 gen3a-turbo；4) 保存并测试。",
        "notes": "后端按 /video/generations 最小契约发送 {model, prompt, duration, aspect_ratio}，成功返回 b64 或 url。",
    },
    {
        "key": "keling", "name": "可灵（Kling AI）", "protocol": "generic-video",
        "default_base_url": "https://api.klingai.com", "base_url_editable": True,
        "models": ["kling-v1", "kling-v1-6", "kling-v2-master"],
        "api_key_label": "可灵 API Key", "api_key_placeholder": "ak-...",
        "model_placeholder": "kling-v1",
        "docs_url": "https://docs.klingai.com/",
        "setup_guide": "1) klingai.com 获取 Key；2) Base URL 默认 https://api.klingai.com；3) Model 填 kling-v1；4) 可灵为异步任务，建议先验证返回结构。",
        "notes": "可灵为异步任务式，标准测试仅验证可达性，实际出片需轮询。",
    },
    {
        "key": "pika", "name": "Pika", "protocol": "generic-video",
        "default_base_url": "https://api.pika.art/v1", "base_url_editable": True,
        "models": ["pika-1.5", "pika-2.0"],
        "api_key_label": "Pika API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "pika-1.5",
        "docs_url": "https://docs.pika.art/",
        "setup_guide": "1) pika.art 获取 Key；2) Base URL 默认 https://api.pika.art/v1；3) Model 填 pika-1.5；4) 保存并测试。",
        "notes": "按 /video/generations 最小契约发送。",
    },
    {
        "key": "jimeng-video", "name": "即梦 / 火山方舟（视频）", "protocol": "generic-video",
        "default_base_url": "https://visual.volcengineapi.com", "base_url_editable": True,
        "models": ["jimeng-video-2.1", "jimeng-video-pro"],
        "api_key_label": "火山引擎 API Key", "api_key_placeholder": "AK...",
        "model_placeholder": "jimeng-video-2.1",
        "docs_url": "https://www.volcengine.com/docs/82379",
        "setup_guide": "1) 火山引擎开通即梦视频并获取 AK/SK；2) Base URL 默认 https://visual.volcengineapi.com；3) Model 填即梦视频模型名；4) 需签名，建议先验证。",
        "notes": "火山方舟请求需鉴权签名，测试仅验证可达性。",
    },
    {
        "key": "custom-video", "name": "自定义视频模型（兼容 /video/generations）", "protocol": "generic-video",
        "default_base_url": "", "base_url_editable": True,
        "models": [],
        "api_key_label": "API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "你的视频模型名",
        "docs_url": "",
        "setup_guide": "适用于任何暴露 {base_url}/video/generations 且接受 {model, prompt, duration, aspect_ratio} 的服务。",
        "notes": "通用兜底：返回 data[0].b64_json 或 data[0].url 即视为成功。",
    },
    # ----------------------------- 新增：文生视频厂商 -----------------------------
    {
        "key": "luma", "name": "Luma Dream Machine", "protocol": "generic-video",
        "default_base_url": "https://api.luma.ai/v1", "base_url_editable": True,
        "models": ["dream-machine-1.6", "dream-machine-2.0", "ray-1"],
        "api_key_label": "Luma API Key", "api_key_placeholder": "luma-...",
        "model_placeholder": "dream-machine-1.6",
        "docs_url": "https://docs.lumalabs.ai",
        "setup_guide": "1) lumalabs.ai 获取 Key；2) Base URL 默认 https://api.luma.ai/v1；3) Model 填 dream-machine-1.6；4) 保存并测试。",
        "notes": "Luma 为异步任务式，标准测试仅验证可达性，实际成片需轮询。",
    },
    {
        "key": "pixverse", "name": "PixVerse", "protocol": "generic-video",
        "default_base_url": "https://app.pixverse.ai/api", "base_url_editable": True,
        "models": ["v3", "v4", "v4.5"],
        "api_key_label": "PixVerse API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "v4",
        "docs_url": "https://docs.pixverse.ai",
        "setup_guide": "1) pixverse.ai 获取 Key；2) Base URL 默认 https://app.pixverse.ai/api；3) Model 填 v4；4) 保存并测试。",
        "notes": "按 /video/generations 最小契约发送；多为异步任务，实际成片需轮询。",
    },
    {
        "key": "haiper", "name": "Haiper", "protocol": "generic-video",
        "default_base_url": "https://api.haiper.ai/v1", "base_url_editable": True,
        "models": ["haiper-2.0", "haiper-1.5"],
        "api_key_label": "Haiper API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "haiper-2.0",
        "docs_url": "https://haiper.ai",
        "setup_guide": "1) haiper.ai 获取 Key；2) Base URL 默认 https://api.haiper.ai/v1；3) Model 填 haiper-2.0；4) 保存并测试。",
        "notes": "按 /video/generations 最小契约发送；异步任务式。",
    },
    {
        "key": "vidu", "name": "Vidu（生数科技）", "protocol": "generic-video",
        "default_base_url": "https://api.vidu.com/v1", "base_url_editable": True,
        "models": ["vidu-2.0", "vidu-q", "vidu-1.5"],
        "api_key_label": "Vidu API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "vidu-2.0",
        "docs_url": "https://www.vidu.com",
        "setup_guide": "1) vidu.com 开放平台获取 Key；2) Base URL 默认 https://api.vidu.com/v1；3) Model 填 vidu-2.0；4) 保存并测试。",
        "notes": "国产文生视频，按 /video/generations 最小契约发送；异步任务式。",
    },
    {
        "key": "tencent-zhiying", "name": "腾讯智影", "protocol": "generic-video",
        "default_base_url": "https://api.zhiying.tencent.com/v1", "base_url_editable": True,
        "models": ["zhiying-video", "zhiying-video-pro"],
        "api_key_label": "腾讯云智影 API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "zhiying-video",
        "docs_url": "https://zhiying.tencent.com",
        "setup_guide": "1) 腾讯云开通智影并获取 Key；2) Base URL 默认 https://api.zhiying.tencent.com/v1；3) Model 填 zhiying-video；4) 保存并测试。",
        "notes": "按 /video/generations 最小契约发送；异步任务式。",
    },
    {
        "key": "higgsfield", "name": "Higgsfield", "protocol": "generic-video",
        "default_base_url": "https://api.higgsfield.ai/v1", "base_url_editable": True,
        "models": ["higgsfield-1", "higgsfield-cinematic"],
        "api_key_label": "Higgsfield API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "higgsfield-1",
        "docs_url": "https://higgsfield.ai",
        "setup_guide": "1) higgsfield.ai 获取 Key；2) Base URL 默认 https://api.higgsfield.ai/v1；3) Model 填 higgsfield-1；4) 保存并测试。",
        "notes": "按 /video/generations 最小契约发送；异步任务式。",
    },
    {
        "key": "ai302-video", "name": "302.AI 视频", "protocol": "generic-video",
        "default_base_url": "https://api.302.ai/v1", "base_url_editable": True,
        "models": ["kling", "runway", "luma"],
        "api_key_label": "302.AI API Key", "api_key_placeholder": "xxxxx",
        "model_placeholder": "kling",
        "docs_url": "https://302.ai",
        "setup_guide": "1) 302.ai 获取 Key；2) Base URL 默认 https://api.302.ai/v1；3) Model 填 kling/runway/luma 等；4) 端点默认 /video/generations，如不同请在「参数(JSON)」填 endpoint。",
        "notes": "聚合多家视频模型，兼容 /video/generations 最小契约；异步任务式。",
    },
    {
        "key": "aliyun-maas-video", "name": "阿里云百炼 MaaS（wan3.0-video）", "protocol": "generic-video",
        "modality": "video",
        "default_base_url": "https://ws-4pdi7amcxvrey8qo.ap-southeast-1.maas.aliyuncs.com", "base_url_editable": True,
        "models": ["wan3.0-video"],
        "api_key_label": "阿里云百炼 / DashScope API Key", "api_key_placeholder": "sk-...",
        "model_placeholder": "wan3.0-video",
        "docs_url": "https://help.aliyun.com/zh/model-studio/",
        "setup_guide": "1) 阿里云百炼开通 wan3.0-video 并获取 API Key；2) 在 Key 所在资源组把部署机公网 IP 加入白名单（否则 403 IP access denied）；3) Base URL 默认已填本次实测网关地址，可改；4) Model 填 wan3.0-video；5) 保存并测试。选此预设会自动填好下方请求头与参数，无需手改。",
        "notes": "实测可用（2026-11-13）：提交后约 3 分钟出 5s/1080p/30fps/9:16 竖屏 MP4，成片 URL 有效期约 24h。\n【请求头】必须带 X-DashScope-Async: enable（由 async_header 参数控制，选预设已自动开启）。\n【提交参数】endpoint= /api/v1/services/aigc/video-generation/video-synthesis；body_shape= dashscope_maas → 请求体 {model,input:{prompt},parameters:{size,count}}（非通用 {model,prompt,duration,aspect_ratio}）。\n【轮询】poll_path= /api/v1/tasks（GET {base_url}/api/v1/tasks/{task_id}）。\n以上四项（endpoint/body_shape/poll_path/async_header）已写进预设默认参数，选此预设即自动装配；通用测试也会按这些开关提交，故「保存并测试」可直接通过。",
        "default_params": {
            "endpoint": "/api/v1/services/aigc/video-generation/video-synthesis",
            "body_shape": "dashscope_maas",
            "poll_path": "/api/v1/tasks",
            "async_header": "true",
        },
    },
]

_IMAGE_PRESET_MAP = {p["key"]: p for p in IMAGE_PRESETS}
_VIDEO_PRESET_MAP = {p["key"]: p for p in VIDEO_PRESETS}


def get_image_preset(key: str) -> Optional[dict]:
    return _IMAGE_PRESET_MAP.get(key)


def get_video_preset(key: str) -> Optional[dict]:
    return _VIDEO_PRESET_MAP.get(key)


def image_protocol_of(provider: str) -> str:
    p = get_image_preset(provider)
    return p["protocol"] if p else "generic-image"


def video_protocol_of(provider: str) -> str:
    p = get_video_preset(provider)
    return p["protocol"] if p else "generic-video"


def get_presets(usage: str) -> list:
    """按用途返回对应模型目录（不含密钥）。

    usage: analysis/copy → 文本 LLM 目录；image → 文生图目录；video → 文生视频目录。
    """
    if usage == "image":
        return [_with_mainstream(p) for p in IMAGE_PRESETS]
    if usage == "video":
        return [_with_mainstream(p) for p in VIDEO_PRESETS]
    return [_with_mainstream(p) for p in LLM_PRESETS]


# ---------------------------------------------------------------------------
# 协议感知连通测试
# ---------------------------------------------------------------------------
def _classify_error(exc, status: int, body: str, preset: Optional[dict]) -> dict:
    """把异常/状态码转成结构化中文诊断 + 文档引导。"""
    docs = preset.get("docs_url") if preset else ""
    docs_label = (preset.get("name") if preset else "该厂商") + " 官方文档"
    base = {
        "ok": False,
        "error_type": "unknown",
        "message": "",
        "http_status": int(status or 0),   # V4.34：服务器返回的 HTTP code；网络层失败为 0
        "hint_url": docs,
        "hint_url_label": docs_label if docs else "",
        "raw": (str(exc)[:240] if exc else "") or (body[:240] if body else ""),
    }
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                        httpx.TimeoutException, httpx.NetworkError)):
        base.update({
            "error_type": "network",
            "message": "无法连接 Base URL（网络不通 / 地址错误 / 服务器出网受限 / 容器内用了 localhost 但服务在外网）。"
                       "请核对 Base URL 是否可从运行环境访问，并确认端口与协议（http/https）。",
        })
        return base
    if status == 401:
        base.update({
            "error_type": "auth",
            "message": "API Key 无效或缺失（401 未授权）。请检查：① Key 是否复制完整、首尾无空格；"
                       "② 该 Key 是否已启用 / 未过期；③ 个别厂商需在控制台为 Key 开通对应模型权限。",
        })
    elif status == 403:
        msg = ("无权限访问（403）。该 Key 可能无权使用该模型，或所在区域/组织未开通该服务，"
               "或请求头缺失（如 Azure 需要 api-version）。请检查账号配额与可用模型列表。")
        body_low = (body or "").lower()
        if "workspace" in body_low or "access_denied" in body_low or "access denied" in body_low:
            msg += ("\n\n检测到 MaaS / 工作空间端点返回 access denied：形如 ws-*.maas.aliyuncs.com 的端点是"
                    "「工作空间级别」专属端点，需要使用**绑定到该工作空间/部署的专用 API Key**，"
                    "而不是账户级 Key；此外请确认所用 Key 的区域（国际站 dashscope-intl / 国内站 dashscope）"
                    "与该工作空间一致。请到该 MaaS 工作空间/部署控制台复制其专用 API Key 后重试。")
        base.update({"error_type": "permission", "message": msg})
    elif status == 404:
        base.update({
            "error_type": "not_found",
            "message": "接口或模型不存在（404）。最常见原因：① Base URL 路径不对（如 DashScope 国内站漏掉 /compatible-mode/v1、"
                       "DashScope 国际站 dashscope-intl 误用 /api/v1、Groq 漏掉 /openai）；② Model 名称拼写错误或未部署。"
                       "请核对预设给出的默认 Base URL 与 Model（国际站统一为 .../compatible-mode/v1）。",
        })
    elif status == 429:
        base.update({
            "error_type": "rate_limit",
            "message": "触发限流或额度不足（429）。请检查账户余额 / 免费额度，或稍后重试；必要时升级套餐。",
        })
    elif status == 400:
        base.update({
            "error_type": "bad_request",
            "message": "请求被拒绝（400）。通常是 Model 名称不被识别或参数非法。请核对 Model 字段（参考预设里的常见模型名）。",
        })
    else:
        base.update({
            "error_type": "unknown",
            "message": f"调用返回非预期状态（HTTP {status}）。响应片段：{(body or str(exc))[:200]}",
        })
    # 把厂商返回的具体错误信息带上，便于定位
    if body:
        base["raw"] = body[:240]
    return base


async def _test_openai(req: dict, preset: Optional[dict]) -> dict:
    api_key, base_url, model = req.get("api_key"), (req.get("base_url") or "").strip(), (req.get("model") or "").strip()
    if not (api_key and base_url and model):
        return {"ok": False, "error_type": "bad_request",
                "message": "缺少必填项：api_key / base_url / model 均不能为空。", "hint_url": "", "hint_url_label": ""}
    url = base_url.rstrip("/") + "/chat/completions"
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url,
                             headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                             json={"model": model,
                                   "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
                                   "max_tokens": 8})
            if r.status_code >= 400:
                return _classify_error(None, r.status_code, _safe_body(r), preset)
            data = r.json()
            reply = data["choices"][0]["message"]["content"][:60]
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000), "reply": reply,
                "protocol": "openai", "provider": req.get("provider")}
    except Exception as e:  # noqa
        return _classify_error(e, getattr(e, "status_code", 0) or 0, "", preset)


async def _test_anthropic(req: dict, preset: Optional[dict]) -> dict:
    api_key, base_url, model = req.get("api_key"), (req.get("base_url") or "").strip(), (req.get("model") or "").strip()
    if not (api_key and base_url and model):
        return {"ok": False, "error_type": "bad_request",
                "message": "缺少必填项：api_key / base_url / model 均不能为空。", "hint_url": "", "hint_url_label": ""}
    url = base_url.rstrip("/") + "/v1/messages"
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url,
                             headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                      "Content-Type": "application/json"},
                             json={"model": model, "max_tokens": 16,
                                   "messages": [{"role": "user", "content": "Reply with the single word: OK"}]})
            if r.status_code >= 400:
                return _classify_error(None, r.status_code, _safe_body(r), preset)
            data = r.json()
            reply = data["content"][0]["text"][:60]
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000), "reply": reply,
                "protocol": "anthropic", "provider": req.get("provider")}
    except Exception as e:  # noqa
        return _classify_error(e, getattr(e, "status_code", 0) or 0, "", preset)


async def _test_gemini(req: dict, preset: Optional[dict]) -> dict:
    api_key, base_url, model = req.get("api_key"), (req.get("base_url") or "").strip(), (req.get("model") or "").strip()
    if not (api_key and base_url and model):
        return {"ok": False, "error_type": "bad_request",
                "message": "缺少必填项：api_key / base_url / model 均不能为空。", "hint_url": "", "hint_url_label": ""}
    url = base_url.rstrip("/") + f"/v1beta/models/{model}:generateContent?key={api_key}"
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url,
                             headers={"Content-Type": "application/json"},
                             json={"contents": [{"role": "user", "parts": [{"text": "Reply with the single word: OK"}]}],
                                   "generationConfig": {"maxOutputTokens": 16}})
            if r.status_code >= 400:
                return _classify_error(None, r.status_code, _safe_body(r), preset)
            data = r.json()
            reply = data["candidates"][0]["content"]["parts"][0]["text"][:60]
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000), "reply": reply,
                "protocol": "gemini", "provider": req.get("provider")}
    except Exception as e:  # noqa
        return _classify_error(e, getattr(e, "status_code", 0) or 0, "", preset)


def _safe_body(r: httpx.Response) -> str:
    try:
        return r.text[:400]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 图像 / 视频协议感知测试
# ---------------------------------------------------------------------------
async def _test_openai_image(req: dict, preset: Optional[dict]) -> dict:
    """DALL·E 兼容：POST {base_url}/images/generations，最小出图验证。"""
    api_key, base_url, model = req.get("api_key"), (req.get("base_url") or "").strip(), (req.get("model") or "").strip()
    if not (api_key and base_url and model):
        return {"ok": False, "error_type": "bad_request",
                "message": "缺少必填项：api_key / base_url / model 均不能为空。", "hint_url": "", "hint_url_label": ""}
    url = base_url.rstrip("/") + "/images/generations"
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url,
                             headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                             json={"model": model, "prompt": "a minimal red square logo, solid background",
                                   "n": 1, "size": "256x256", "response_format": "b64_json"})
            if r.status_code >= 400:
                return _classify_error(None, r.status_code, _safe_body(r), preset)
            data = r.json()
            item = (data.get("data") or [{}])[0]
            has_img = bool(item.get("b64_json") or item.get("url"))
        return {"ok": has_img, "latency_ms": int((time.time() - t0) * 1000),
                "reply": "image returned" if has_img else "no image field",
                "protocol": "openai-image", "provider": req.get("provider")}
    except Exception as e:  # noqa
        return _classify_error(e, getattr(e, "status_code", 0) or 0, "", preset)


async def _test_generic_image(req: dict, preset: Optional[dict]) -> dict:
    """通用图像：POST {base_url}{endpoint|/images/generations}，验证可达性与鉴权。

    不同厂商（万相/CogView/SD/Replicate）字段差异大，无法一次性验证出图，
    这里以「能连通 + 鉴权通过 + 返回 JSON」作为最小通过标准，并提示实际出图可能需轮询/签名。
    """
    api_key, base_url, model = req.get("api_key"), (req.get("base_url") or "").strip(), (req.get("model") or "").strip()
    if not (api_key and base_url and model):
        return {"ok": False, "error_type": "bad_request",
                "message": "缺少必填项：api_key / base_url / model 均不能为空。", "hint_url": "", "hint_url_label": ""}
    endpoint = (req.get("endpoint") or "").strip() or "/images/generations"
    url = base_url.rstrip("/") + endpoint
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers=headers,
                             json={"model": model, "prompt": "a minimal red square", "size": "256x256", "n": 1})
            if r.status_code >= 400:
                return _classify_error(None, r.status_code, _safe_body(r), preset)
            data = r.json()
            item = ((data.get("data") or [{}])[0]) if isinstance(data, dict) else {}
            has_img = bool((isinstance(item, dict) and (item.get("b64_json") or item.get("url")))
                           or data.get("output") or data.get("images"))
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000),
                "reply": ("image returned" if has_img else "reachable (async/non-standard image API, verify output structure)"),
                "protocol": "generic-image", "provider": req.get("provider"),
                "note": "通用图像端点已连通；若厂商为异步任务（万相/可灵/Replicate 等），实际出图需轮询，请按厂商文档核对返回结构。"}
    except Exception as e:  # noqa
        return _classify_error(e, getattr(e, "status_code", 0) or 0, "", preset)


async def _test_dashscope_maas_image(req: dict, preset: Optional[dict]) -> dict:
    """阿里 MaaS 多模态图像：POST 完整 base_url，同步返回图片签名 URL 即视为通过。

    点击测试即真实生成一次图片（消耗额度）。请求体为 messages 数组格式，非 OpenAI 风格。
    """
    api_key, base_url, model = req.get("api_key"), (req.get("base_url") or "").strip(), (req.get("model") or "").strip()
    if not (api_key and base_url and model):
        return {"ok": False, "error_type": "bad_request",
                "message": "缺少必填项：api_key / base_url / model 均不能为空。", "hint_url": "", "hint_url_label": ""}
    url = base_url.rstrip("/")
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(url,
                             headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                             json={"model": model,
                                   "input": {"messages": [{"role": "user",
                                                           "content": [{"text": "a small red dot on white background, simple"}]}]},
                                   "parameters": {"size": "1024*1024", "n": 1}})
            if r.status_code >= 400:
                return _classify_error(None, r.status_code, _safe_body(r), preset)
            data = r.json()
            img_url = (
                data.get("output", {}).get("choices", [{}])[0]
                .get("message", {}).get("content", [{}])[0].get("image")
            )
        return {"ok": bool(img_url), "latency_ms": int((time.time() - t0) * 1000),
                "reply": ("image url returned" if img_url else "reachable but no image field"),
                "protocol": "dashscope-maas-image", "provider": req.get("provider"),
                "note": "已同步返回图片签名 URL，点击测试即真实生成一次图片（消耗额度）。"}
    except Exception as e:  # noqa
        return _classify_error(e, getattr(e, "status_code", 0) or 0, "", preset)


async def _test_generic_video(req: dict, preset: Optional[dict]) -> dict:
    """通用视频：按 params 决定端点 / 请求体 / 请求头，验证可达性与鉴权。

    视频多为异步任务，这里以「能连通 + 鉴权通过 + 任务被受理」作为最小通过标准：
    - 成功返回 task_id / 媒体即视为通过；不阻塞轮询（视频生成常需数分钟）。
    - 兼容两种契约：
        * 默认（无 body_shape）：POST {base_url}/video/generations，body={model,prompt,duration,aspect_ratio}
        * body_shape=dashscope_maas：POST {base_url}{endpoint}，body={model,input:{prompt},parameters:{size,count}}，
          并附加 X-DashScope-Async: enable 头（阿里云百炼 MaaS / wan3.0-video 实测所需）。
    """
    api_key = (req.get("api_key") or "").strip()
    base_url = (req.get("base_url") or "").strip()
    model = (req.get("model") or "").strip()
    if not (api_key and base_url and model):
        return {"ok": False, "error_type": "bad_request",
                "message": "缺少必填项：api_key / base_url / model 均不能为空。", "hint_url": "", "hint_url_label": ""}
    params = req.get("params") if isinstance(req.get("params"), dict) else {}
    endpoint = (params.get("endpoint") or req.get("endpoint") or "/video/generations").strip()
    body_shape = (params.get("body_shape") or "").strip()
    if body_shape == "dashscope_maas":
        # 阿里云百炼 MaaS（wan3.0-video 等）契约：提交体为 {model,input:{prompt},parameters:{size,count}}，
        # 且需 X-DashScope-Async: enable 头。实测该端点忽略 size、固定输出 9:16 竖屏，这里仍推导一个合理 size。
        aspect = (params.get("aspect") or "9:16")
        size = params.get("size") or ("1080*1920" if aspect == "9:16" else "1280*720")
        body = {"model": model, "input": {"prompt": "a short product intro"},
                "parameters": {"size": size, "count": 1}}
    else:
        body = {"model": model, "prompt": "a short product intro", "duration": 5, "aspect_ratio": "9:16"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if str(params.get("async_header") or "").strip().lower() in ("true", "1", "yes"):
        headers["X-DashScope-Async"] = "enable"
    url = base_url.rstrip("/") + endpoint
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                return _classify_error(None, r.status_code, _safe_body(r), preset)
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            out = data.get("output") if isinstance(data.get("output"), dict) else {}
            task_id = out.get("task_id") or data.get("task_id") or data.get("id")
            reply = "reachable (async video API, verify output structure)"
            note = "视频端点已连通；视频多为异步任务，实际成片需轮询，请按厂商文档核对返回结构。"
            if task_id:
                reply = f"提交成功，异步任务已受理（task_id={task_id}）"
                note = "已提交视频生成任务并获得任务 ID；实际出片为异步，需在生成流程中轮询取片。"
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000),
                "reply": reply, "protocol": "generic-video", "provider": req.get("provider"),
                "note": note}
    except Exception as e:  # noqa
        return _classify_error(e, getattr(e, "status_code", 0) or 0, "", preset)


_TESTERS = {"openai": _test_openai, "anthropic": _test_anthropic, "gemini": _test_gemini,
            "openai-image": _test_openai_image, "generic-image": _test_generic_image,
            "dashscope-maas-image": _test_dashscope_maas_image,
            "generic-video": _test_generic_video, "aliyun-maas-video": _test_generic_video}


async def test_llm_connection(req: dict) -> dict:
    """统一入口：按 provider 查目录决定协议，发起真实最小调用并返回结构化结果。

    req 字段：provider, api_key, base_url, model, protocol?(可选覆盖), endpoint?(通用图像端点)。
    当 protocol 为 openai-image / generic-image / generic-video 时走对应图像/视频测试。
    """
    provider = req.get("provider") or "custom"
    # 图像/视频厂商走各自目录解析协议；文本厂商走 LLM 目录
    preset = get_preset(provider) or get_image_preset(provider) or get_video_preset(provider)
    protocol = req.get("protocol") or _resolve_protocol(provider)
    tester = _TESTERS.get(protocol, _test_openai)
    res = await tester(req, preset)
    # V4.34：统一补齐 http_status，供每日自动测试落库。
    # - 失败分支（_classify_error）已带真实 HTTP code；网络层异常为 0
    # - 成功分支 / 缺参提前返回未带，这里补 200 / 0
    if "http_status" not in res:
        res["http_status"] = 200 if res.get("ok") else 0
    return res
