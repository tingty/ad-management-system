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
            "message": "接口或模型不存在（404）。最常见原因：① Base URL 路径不对（如 DashScope 漏掉 /compatible-mode/v1、"
                       "Groq 漏掉 /openai）；② Model 名称拼写错误或未部署。请核对预设给出的默认 Base URL 与 Model。",
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


_TESTERS = {"openai": _test_openai, "anthropic": _test_anthropic, "gemini": _test_gemini}


async def test_llm_connection(req: dict) -> dict:
    """统一入口：按 provider 查目录决定协议，发起真实最小调用并返回结构化结果。

    req 字段：provider, api_key, base_url, model, protocol?(可选覆盖)。
    """
    provider = req.get("provider") or "custom"
    preset = get_preset(provider)
    protocol = (req.get("protocol") or (preset["protocol"] if preset else "openai"))
    tester = _TESTERS.get(protocol, _test_openai)
    return await tester(req, preset)
