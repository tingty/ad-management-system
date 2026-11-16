"""V4.78 验证：视频用途的模型选择必须跳过文本模型。

场景（复现用户问题）：用户配了「阿里千问视频模型」(video 用途)，
但库里另一条 deepseek 文本配置的用途里残留了 video。旧逻辑按「测试通过 → id 更大」
挑，可能挑中 deepseek，表现为「创意工作台调用 deepseek 出片」。
"""
import os, tempfile, sys

tmp = os.path.join(tempfile.mkdtemp(), "v478.db")
os.environ["DATABASE_URL"] = "sqlite:///" + tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../backend")

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: F401,E402
from models import ModelConfig  # noqa: E402
from providers import _pick_config, is_video_capable, video_route_report  # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()

rows = [
    ModelConfig(name="千问文本大模型", usage="analysis", usages=["analysis", "copy"],
                provider="openai", api_key="sk-x", model="qwen-plus",
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                params={}, is_active=True, last_test_ok=True),
    ModelConfig(name="DeepSeek 文本", usage="analysis", usages=["analysis", "video"],
                provider="deepseek", api_key="sk-y", model="deepseek-chat",
                base_url="https://api.deepseek.com/v1", params={}, is_active=True,
                last_test_ok=True),
    ModelConfig(name="阿里千问视频模型", usage="video", usages=["video"],
                provider="aliyun-maas-video", api_key="sk-z", model="wan3.0-video",
                base_url="https://ws-4pdi7amcxvrey8qo.ap-southeast-1.maas.aliyuncs.com",
                params={"body_shape": "dashscope_maas", "endpoint": "/api/v1/services/aigc/video-generation/video-synthesis",
                        "async_header": "true", "poll_path": "/api/v1/tasks/{task_id}",
                        "output_aspect": "9:16"},
                is_active=True, last_test_ok=None),
]
db.add_all(rows)
db.commit()

rep = video_route_report(db)
picked = rep["picked"]
assert picked is not None, "应选中千问视频模型"
assert picked.model == "wan3.0-video", f"错误：选中了 {picked.model}（{picked.name}）"
assert [s["cfg"].model for s in rep["skipped"]] == ["deepseek-chat"], rep["skipped"]
print("用例1 通过：video 用途选中华南视频模型 wan3.0-video，deepseek 被跳过")

# 用例2：只有文本模型被误勾 video → 不应出片（返回 None），并给出跳过原因
for r in list(db.query(ModelConfig).all()):
    if r.model == "wan3.0-video":
        db.delete(r)
db.commit()
rep2 = video_route_report(db)
assert rep2["picked"] is None, f"文本模型不应接管出片，实际 {rep2['picked'].model}"
assert len(rep2["skipped"]) == 1 and "文本模型" in rep2["skipped"][0]["reason"]
print("用例2 通过：无可用视频模型时返回 None（回退分镜），原因：", rep2["skipped"][0]["reason"])

# 用例3：模态识别覆盖常见写法
class _C:
    def __init__(self, provider="", model="", params=None):
        self.provider, self.model, self.params = provider, model, params or {}

cases = [
    (_C("aliyun-maas-video", "wan3.0-video"), True),
    (_C("keling", "kling-v2"), True),
    (_C("ai302-video", "runway-gen3"), True),
    (_C("custom", "my-video-1"), True),
    (_C("openai", "sora-2"), True),
    (_C("deepseek", "deepseek-chat"), False),
    (_C("openai", "qwen-plus"), False),
    (_C("anthropic", "claude-3-5-sonnet"), False),
    (_C("custom", "x", {"poll_path": "/api/v1/tasks/{id}"}), True),
]
for c, want in cases:
    got = is_video_capable(c)
    assert got == want, f"is_video_capable({c.provider}/{c.model}) = {got}，期望 {want}"
print("用例3 通过：9 组供应商/模型模态识别全部正确")
print("全部通过")
