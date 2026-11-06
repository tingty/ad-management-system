"""
全球主流大模型「配置目录 + 协议感知连通测试」。

用途：
- 前端「设置 → 大模型」按目录选择厂商（OpenAI / DeepSeek / 通义千问 / Anthropic / Gemini …），
  选中后自动带出默认 Base URL、常见 Model、必填字段与官方文档链接，用户只填 Key/Model 即可。
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


# ---------------------------------------------------------------------------
# 文生图（Text-to-Image）模型目录
# ---------------------------------------------------------------------------
# protocol:
#   openai-image   : OpenAI /images/generations（DALL·E 3/2、Azure OpenAI、多数网关兼容）
#   generic-image  : 通用图像端点，POST {base_url}{endpoint}，默认 /images/generations；
#                    不同厂商（通义万相 / 智谱 CogView / SD / Replicate 等）路径与字段差异大，
#                    由 provider 读取 params.endpoint 调整，并尽量兼容 {model, prompt, size} 形态。
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
        return IMAGE_PRESETS
    if usage == "video":
        return VIDEO_PRESETS
    return LLM_PRESETS


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
        base.update({
            "error_type": "permission",
            "message": "无权限访问（403）。该 Key 可能无权使用该模型，或所在区域/组织未开通该服务，"
                       "或请求头缺失（如 Azure 需要 api-version）。请检查账号配额与可用模型列表。",
        })
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


async def _test_generic_video(req: dict, preset: Optional[dict]) -> dict:
    """通用视频：POST {base_url}/video/generations，验证可达性与鉴权。

    视频多为异步任务，这里以「能连通 + 鉴权通过」作为最小通过标准。
    """
    api_key, base_url, model = req.get("api_key"), (req.get("base_url") or "").strip(), (req.get("model") or "").strip()
    if not (api_key and base_url and model):
        return {"ok": False, "error_type": "bad_request",
                "message": "缺少必填项：api_key / base_url / model 均不能为空。", "hint_url": "", "hint_url_label": ""}
    url = base_url.rstrip("/") + "/video/generations"
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url,
                             headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                             json={"model": model, "prompt": "a short product intro", "duration": 5, "aspect_ratio": "9:16"})
            if r.status_code >= 400:
                return _classify_error(None, r.status_code, _safe_body(r), preset)
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000),
                "reply": "reachable (async video API, verify output structure)",
                "protocol": "generic-video", "provider": req.get("provider"),
                "note": "通用视频端点已连通；视频多为异步任务，实际成片需轮询，请按厂商文档核对返回结构。"}
    except Exception as e:  # noqa
        return _classify_error(e, getattr(e, "status_code", 0) or 0, "", preset)


_TESTERS = {"openai": _test_openai, "anthropic": _test_anthropic, "gemini": _test_gemini,
            "openai-image": _test_openai_image, "generic-image": _test_generic_image,
            "generic-video": _test_generic_video}


async def test_llm_connection(req: dict) -> dict:
    """统一入口：按 provider 查目录决定协议，发起真实最小调用并返回结构化结果。

    req 字段：provider, api_key, base_url, model, protocol?(可选覆盖), endpoint?(通用图像端点)。
    当 protocol 为 openai-image / generic-image / generic-video 时走对应图像/视频测试。
    """
    provider = req.get("provider") or "custom"
    # 图像/视频厂商走各自目录解析协议；文本厂商走 LLM 目录
    preset = get_preset(provider) or get_image_preset(provider) or get_video_preset(provider)
    protocol = (req.get("protocol") or (preset["protocol"] if preset else "openai"))
    tester = _TESTERS.get(protocol, _test_openai)
    return await tester(req, preset)
