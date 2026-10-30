"""规格校验：将生成素材与平台规格比对，输出可展示的合规结果。"""


def validate_copy(copy, limits):
    issues = []
    if not isinstance(copy, dict):
        return [{"level": "error", "code": "NO_COPY", "message": "无文案内容"}]
    tl = (limits or {}).get("title_max")
    dl = (limits or {}).get("description_max")
    pl = (limits or {}).get("primary_text_max")
    for t in copy.get("titles", []) or []:
        if tl and len(t) > tl:
            issues.append({"level": "error", "code": "TITLE_TOO_LONG",
                           "message": f"标题超限：{len(t)}>{tl} 字｜{t}"})
    for d in copy.get("descriptions", []) or []:
        if dl and len(d) > dl:
            issues.append({"level": "error", "code": "DESC_TOO_LONG",
                           "message": f"描述超限：{len(d)}>{dl} 字｜{d}"})
    # 主文案（若有）按 primary_text_max 校验
    primary = copy.get("primary_text")
    if pl and primary and len(primary) > pl:
        issues.append({"level": "warn", "code": "PRIMARY_TOO_LONG",
                       "message": f"主文案超出推荐：{len(primary)}>{pl} 字"})
    return issues


def validate_image(primary, sizes):
    issues = []
    sizes = sizes or []
    if primary and sizes and primary not in sizes:
        issues.append({"level": "error", "code": "IMAGE_SIZE_NOT_ALLOWED",
                       "message": f"尺寸 {primary} 不在平台允许列表：{', '.join(sizes)}"})
    if not sizes:
        issues.append({"level": "warn", "code": "NO_IMAGE_SPEC", "message": "该平台未配置图片尺寸规格"})
    return issues


def validate_keyword(kw):
    issues = []
    total = sum(len(v) for v in kw.values() if isinstance(v, list)) if isinstance(kw, dict) else 0
    if total == 0:
        issues.append({"level": "warn", "code": "EMPTY_KEYWORDS", "message": "关键词为空"})
    return issues


def build_validation(material_type, content, spec_json=None, limits=None):
    spec_json = spec_json or {}
    if material_type == "copy":
        issues = validate_copy(content, limits)
    elif material_type == "keyword":
        issues = validate_keyword(content)
    elif material_type == "image":
        issues = validate_image(spec_json.get("size") or spec_json.get("primary"),
                                spec_json.get("all_sizes") or spec_json.get("sizes"))
    elif material_type == "video":
        issues = []
        v = content or {}
        if isinstance(v, dict):
            if v.get("note", "").startswith("MOCK"):
                issues.append({"level": "warn", "code": "VIDEO_MOCK",
                               "message": "视频为占位描述，接入真实视频模型后可校验时长/比例"})
            if v.get("provider") == "storyboard":
                shots = v.get("shots") or []
                if len(shots) < 3:
                    issues.append({"level": "warn", "code": "STORYBOARD_INCOMPLETE",
                                   "message": f"分镜不足：{len(shots)} 个镜头（建议 ≥3）"})
                if not v.get("cta"):
                    issues.append({"level": "warn", "code": "NO_CTA",
                                   "message": "结尾缺少 CTA 收口"})
                if not (v.get("duration_sec") or 0):
                    issues.append({"level": "warn", "code": "NO_DURATION", "message": "缺少时长定义"})
            if v.get("provider") == "model" and not (v.get("file_path") or v.get("url")):
                issues.append({"level": "error", "code": "VIDEO_NO_OUTPUT",
                               "message": "视频模型返回成功但无文件/URL"})
    else:
        issues = []
    valid = not any(i["level"] == "error" for i in issues)
    return {"valid": valid, "issues": issues}
