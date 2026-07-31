import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from text_model_client import chat_json, is_configured, text_model_config


LAYOUT_PRESETS = {
    "splash_opening": {
        "reading_flow": "top establishing panel, mid action beat, bottom page-turn splash",
        "visual_priority": "top establishing panel and bottom hook panel",
        "panels": [
            {"x": 0, "y": 0, "w": 1600, "h": 690, "role": "opening_splash", "shot_type": "wide_splash", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 12, "y": 722, "w": 764, "h": 700, "role": "action_advance", "shot_type": "medium_action", "shape": "rect", "border": 0, "render_order": 2},
            {"x": 812, "y": 722, "w": 764, "h": 700, "role": "emotional_reaction", "shot_type": "reaction", "shape": "rect", "border": 0, "render_order": 3},
            {"x": 0, "y": 1446, "w": 1600, "h": 954, "role": "page_turn_hook", "shot_type": "bottom_splash", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
    "diagonal_action": {
        "reading_flow": "upper setup, diagonal action cut, lower consequence panel",
        "visual_priority": "diagonal action panel",
        "panels": [
            {"x": 12, "y": 16, "w": 764, "h": 636, "role": "scene_setup", "shot_type": "establishing", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 812, "y": 16, "w": 764, "h": 636, "role": "close_reaction", "shot_type": "close_reaction", "shape": "rect", "border": 0, "render_order": 2},
            {"x": 0, "y": 688, "w": 1600, "h": 800, "role": "action_splash", "shot_type": "action_splash", "shape": "slant_right", "slant": 96, "border": 0, "render_order": 3},
            {"x": 0, "y": 1512, "w": 1600, "h": 888, "role": "consequence_hook", "shot_type": "reveal", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
    "bottom_reveal": {
        "reading_flow": "small setup beats, then a dominant bottom reveal",
        "visual_priority": "bottom reveal splash",
        "panels": [
            {"x": 12, "y": 16, "w": 504, "h": 552, "role": "detail_setup", "shot_type": "detail", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 548, "y": 16, "w": 504, "h": 552, "role": "character_reaction", "shot_type": "reaction", "shape": "rect", "border": 0, "render_order": 2},
            {"x": 1072, "y": 16, "w": 504, "h": 552, "role": "action_trigger", "shot_type": "action", "shape": "rect", "border": 0, "render_order": 3},
            {"x": 0, "y": 604, "w": 1600, "h": 1796, "role": "reveal_splash", "shot_type": "reveal_splash", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
    "bleed_tension": {
        "reading_flow": "near-bleed opening pressure, two reaction beats, final narrow silence",
        "visual_priority": "large near-bleed pressure panel",
        "panels": [
            {"x": 0, "y": 20, "w": 1600, "h": 1002, "role": "bleed_pressure", "shot_type": "bleed_splash", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 12, "y": 1042, "w": 760, "h": 650, "role": "counter_action", "shot_type": "medium_action", "shape": "slant_left", "slant": 64, "border": 0, "render_order": 2},
            {"x": 816, "y": 1042, "w": 760, "h": 650, "role": "reaction_cut", "shot_type": "reaction", "shape": "slant_right", "slant": 64, "border": 0, "render_order": 3},
            {"x": 0, "y": 1716, "w": 1600, "h": 684, "role": "silent_hook", "shot_type": "quiet_transition", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
    "inset_reaction": {
        "reading_flow": "main scene panel with an inset reaction, then a lower transition",
        "visual_priority": "main scene with upper-right inset reaction",
        "panels": [
            {"x": 0, "y": 0, "w": 1600, "h": 636, "role": "wide_opening", "shot_type": "wide_establishing", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 0, "y": 648, "w": 1600, "h": 1056, "role": "main_scene_action", "shot_type": "scene_splash", "shape": "rect", "border": 0, "render_order": 2},
            {"x": 1074, "y": 696, "w": 460, "h": 420, "role": "inset_reaction", "shot_type": "inset_reaction", "shape": "rect", "border": 0, "render_order": 3, "drop_shadow": True, "shadow_offset": 8},
            {"x": 0, "y": 1716, "w": 1600, "h": 684, "role": "page_transition", "shot_type": "transition", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode-plan", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--generation-context", default="")
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--max-pages", type=int, default=0)
    args = parser.parse_args()

    if not is_configured():
        raise SystemExit("小说处理模型未配置，不能执行细读拆解。")

    plan_path = Path(args.episode_plan)
    episode = read_json(plan_path)
    context = read_json(Path(args.generation_context)) if args.generation_context else {}
    pages = episode.get("pages") or []
    if not pages:
        raise SystemExit("章节计划没有页面，不能执行细读拆解。")

    protected_page_ids = {str(value) for value in (context.get("protected_page_ids") or []) if value}
    selected, protected = select_pages(pages, args.only_missing, args.max_pages, protected_page_ids)
    if not selected:
        result = {
            "ok": True,
            "completed": True,
            "updated": now(),
            "episode_plan": str(plan_path),
            "updated_pages": [],
            "protected_pages": protected,
            "message": "没有可安全细读的页面。已生成、已入库或已审核页面不会被覆盖。",
        }
        write_result(args.output, plan_path, result)
        return 0

    try:
        model_result = close_read_pages_with_model(episode, selected, context)
    except Exception as exc:
        result = {
            "ok": False,
            "completed": False,
            "updated": now(),
            "episode_plan": str(plan_path),
            "updated_pages": [],
            "protected_pages": protected,
            "candidate_pages": [page.get("page_id", "") for page in selected],
            "model": text_model_config().get("model", ""),
            "error_type": classify_model_error(str(exc)),
            "error": str(exc),
            "message": "小说处理模型暂不可用，未修改章节计划。请稍后重试细读拆解。",
        }
        write_result(args.output, plan_path, result)
        return 2
    refined_pages = normalize_model_pages(model_result.get("pages") or [])
    if not refined_pages:
        raise SystemExit("小说处理模型没有返回可用的页面细读结果。")

    by_page = {item["page_id"]: item for item in refined_pages if item.get("page_id")}
    updated_pages = []
    for page in pages:
        refined = by_page.get(str(page.get("page_id") or ""))
        if not refined:
            continue
        apply_refined_page(episode, page, refined, plan_path)
        updated_pages.append(page.get("page_id"))

    episode["updated"] = now_date()
    episode["skeleton"] = any(is_skeleton_page(page) for page in pages)
    episode["close_reading_required"] = episode["skeleton"]
    episode["adaptation_status"] = "close_reading_refined_needs_review"
    raw = episode.setdefault("close_reading", {})
    raw.update(
        {
            "updated": now(),
            "model": text_model_config().get("model", ""),
            "updated_pages": updated_pages,
            "protected_pages": protected,
            "generation_context_summary": (context or {}).get("summary", {}),
        }
    )
    plan_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "ok": True,
        "completed": True,
        "updated": now(),
        "episode_plan": str(plan_path),
        "episode_id": episode.get("episode_id", ""),
        "episode_title": episode.get("title") or episode.get("chapter_title", ""),
        "model": text_model_config().get("model", ""),
        "updated_pages": updated_pages,
        "protected_pages": protected,
        "referenced_settings": [item.get("name") for item in (context.get("settings") or []) if item.get("name")],
        "referenced_assets": [item.get("title") for item in (context.get("assets") or []) if item.get("title")],
        "adaptation_status": episode["adaptation_status"],
    }
    write_result(args.output, plan_path, result)
    return 0


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_result(output: str, plan_path: Path, result: dict) -> None:
    output_path = Path(output) if output else plan_path.with_name(plan_path.stem + "_close_reading.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def select_pages(pages: list[dict], only_missing: bool, max_pages: int, protected_page_ids: set[str]) -> tuple[list[dict], list[dict]]:
    selected = []
    protected = []
    for page in pages:
        reason = protected_reason(page, only_missing, protected_page_ids)
        if reason:
            protected.append({"page_id": page.get("page_id", ""), "reason": reason})
            continue
        selected.append(page)
        if max_pages > 0 and len(selected) >= max_pages:
            break
    return selected, protected


def protected_reason(page: dict, only_missing: bool, protected_page_ids: set[str]) -> str:
    if str(page.get("page_id") or "") in protected_page_ids:
        return "已有生成结果，受保护"
    media = page.get("media") or {}
    if media.get("exists") or media.get("db_synced") or media.get("db_output_id"):
        return "已有页面输出"
    status = str(media.get("db_review_status") or "")
    if status in {"approved", "pending_review", "needs_work"}:
        return "页面已有审核状态"
    for panel in page.get("panels") or []:
        panel_media = panel.get("media") or {}
        if panel_media.get("exists") or panel_media.get("db_synced") or panel_media.get("db_output_id"):
            return "已有分镜输出"
        panel_status = str(panel_media.get("db_review_status") or "")
        if panel_status in {"approved", "pending_review", "needs_work"}:
            return "分镜已有审核状态"
    if only_missing and not is_skeleton_page(page):
        return "不是骨架页面"
    return ""


def is_skeleton_page(page: dict) -> bool:
    if "skeleton" in str(page.get("status") or ""):
        return True
    text = (str(page.get("summary") or "") + " " + " ".join(str(panel.get("prompt") or "") for panel in page.get("panels") or []))
    return "待细读" in text or "初始页面骨架" in text


def close_read_pages_with_model(episode: dict, pages: list[dict], context: dict) -> dict:
    payload_pages = []
    for page in pages:
        payload_pages.append(
            {
                "page_id": page.get("page_id"),
                "title": page.get("title"),
                "source_excerpt": page.get("source_excerpt", ""),
                "current_summary": page.get("summary", ""),
                "panel_count": max(1, len(page.get("panels") or [])),
                "panel_ids": [panel.get("panel_id") for panel in page.get("panels") or []],
            }
        )
    messages = [
        {
            "role": "system",
            "content": (
                "你是长篇小说漫画改编的细读分镜师。只返回 JSON。"
                "必须基于原文，不得虚构脱离原文的大事件。"
                "所有用户可见字段使用中文。图片提示词可以中文为主，保留必要镜头术语。"
                "输出要适合中国神话幻想漫画，无画面内文字、无水印。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "episode_id": episode.get("episode_id"),
                    "episode_title": episode.get("title") or episode.get("chapter_title"),
                    "approved_settings": context.get("settings") or [],
                    "locked_assets": context.get("assets") or [],
                    "pages": payload_pages,
                    "required_schema": {
                        "pages": [
                            {
                                "page_id": "原 page_id",
                                "title": "中文页标题",
                                "summary": "本页剧情摘要，具体到人物、行动、情绪转折",
                                "director": {
                                    "page_rhythm": "本页阅读节奏，例如：铺垫-冲突-反应-悬念",
                                    "emotional_arc": "情绪推进，例如：疑惑到惊惧",
                                    "layout_style": "推荐版式：splash_opening / diagonal_action / bottom_reveal / bleed_tension / inset_reaction",
                                    "visual_priority": "本页最重要的视觉焦点",
                                    "lettering_strategy": "旁白和对白的排布策略，说明哪些格需要气泡或旁白",
                                    "page_turn_hook": "页尾悬念或下一页推动点",
                                    "camera_flow": ["每格镜头顺序和视线流向"]
                                },
                                "panel_intent": ["每格一句中文分镜意图"],
                                "panels": [
                                    {
                                        "panel_id": "原 panel_id",
                                        "title": "中文分镜标题",
                                        "panel_role": "开场 / 动作 / 反应 / 揭示 / 转场 / 嵌入",
                                        "shot_type": "远景 / 中景 / 特写 / 俯视 / 仰视 / 主视觉",
                                        "visual_priority": "这一格的视觉重点",
                                        "camera_direction": "读者视线和动作方向",
                                        "caption": "可空，最多一句",
                                        "dialogue": [{"speaker": "人物名，可空", "text": "对白，可空", "position": "bottom"}],
                                        "prompt": "具体画面提示词：角色、场景、动作、情绪、镜头、构图、风格约束",
                                        "reference_alias": "只能填写 locked_assets 中一个素材的 title；没有合适素材则留空"
                                    }
                                ],
                            }
                        ]
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    last_error = None
    for attempt in range(1, 4):
        try:
            result = chat_json(messages, temperature=0.25, timeout=180)
            result["_attempts"] = attempt
            return result
        except Exception as exc:
            last_error = exc
            if "503" not in str(exc) and "temporarily unavailable" not in str(exc).lower():
                raise
            if attempt < 3:
                time.sleep(5 * attempt)
    raise last_error


def classify_model_error(message: str) -> str:
    lower = message.lower()
    if "503" in lower or "temporarily unavailable" in lower:
        return "text_model_unavailable"
    if "401" in lower or "403" in lower or "api key" in lower:
        return "text_model_auth_failed"
    if "429" in lower or "rate" in lower:
        return "text_model_rate_limited"
    if "timeout" in lower or "timed out" in lower:
        return "text_model_timeout"
    return "text_model_error"


def normalize_model_pages(pages: list[dict]) -> list[dict]:
    normalized = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = str(page.get("page_id") or "").strip()
        panels = [panel for panel in page.get("panels") or [] if isinstance(panel, dict)]
        if not page_id or not panels:
            continue
        normalized.append(
            {
                "page_id": page_id,
                "title": clean_text(page.get("title"), 80),
                "summary": clean_text(page.get("summary"), 280),
                "director": normalize_director(page.get("director") or {}),
                "panel_intent": [clean_text(item, 120) for item in (page.get("panel_intent") or []) if clean_text(item, 120)],
                "panels": panels,
            }
        )
    return normalized


def normalize_director(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    camera_flow = raw.get("camera_flow") or []
    if not isinstance(camera_flow, list):
        camera_flow = [camera_flow]
    layout_style = clean_text(raw.get("layout_style"), 40)
    if layout_style not in LAYOUT_PRESETS:
        layout_style = infer_layout_style(raw)
    return {
        "page_rhythm": clean_text(raw.get("page_rhythm"), 120),
        "emotional_arc": clean_text(raw.get("emotional_arc"), 120),
        "layout_style": layout_style,
        "visual_priority": clean_text(raw.get("visual_priority"), 120),
        "lettering_strategy": clean_text(raw.get("lettering_strategy"), 180),
        "page_turn_hook": clean_text(raw.get("page_turn_hook"), 120),
        "camera_flow": [clean_text(item, 100) for item in camera_flow if clean_text(item, 100)],
    }


def infer_layout_style(raw: dict) -> str:
    text = compact(" ".join(str(raw.get(key) or "") for key in ("page_rhythm", "emotional_arc", "visual_priority", "lettering_strategy", "page_turn_hook")))
    if any(cue in text for cue in ("动作", "冲突", "追", "战", "撞", "奔", "速度", "斜")):
        return "diagonal_action"
    if any(cue in text for cue in ("揭示", "发现", "出现", "真相", "底部", "震惊")):
        return "bottom_reveal"
    if any(cue in text for cue in ("压迫", "恐惧", "紧张", "沉默", "水妖", "龙女")):
        return "bleed_tension"
    if any(cue in text for cue in ("表情", "反应", "凝视", "对视", "惊讶")):
        return "inset_reaction"
    return "splash_opening"


def apply_director_layout(page: dict, director: dict) -> None:
    style = (director or {}).get("layout_style") or "splash_opening"
    preset = LAYOUT_PRESETS.get(style) or LAYOUT_PRESETS["splash_opening"]
    panels = page.get("panels") or []
    for index, panel in enumerate(panels):
        layout = dict(preset["panels"][min(index, len(preset["panels"]) - 1)])
        panel["layout"] = layout
        panel.setdefault("panel_role", layout.get("role", ""))
        panel.setdefault("shot_type", layout.get("shot_type", ""))
    page["layout_style"] = style
    page["reading_flow"] = director.get("page_rhythm") or preset.get("reading_flow", "")
    page["visual_priority"] = director.get("visual_priority") or preset.get("visual_priority", "")


def apply_refined_page(episode: dict, page: dict, refined: dict, episode_plan_path: Path) -> None:
    page["status"] = "close_reading_refined_needs_review"
    page["title"] = refined.get("title") or page.get("title")
    page["summary"] = refined.get("summary") or page.get("summary")
    page["director"] = refined.get("director") or {}
    apply_director_layout(page, page["director"])
    page["panel_intent"] = refined.get("panel_intent") or []
    page["close_reading_required"] = False
    page["close_reading_refined"] = True
    page["close_reading_updated"] = now()

    refined_panels = {str(panel.get("panel_id") or ""): panel for panel in refined.get("panels") or []}
    for index, panel in enumerate(page.get("panels") or [], start=1):
        panel_id = str(panel.get("panel_id") or "")
        refined_panel = refined_panels.get(panel_id) or ((refined.get("panels") or [])[index - 1] if index <= len(refined.get("panels") or []) else {})
        apply_refined_panel(panel, refined_panel, index)

    page_plan_path = plan_path_for_page(episode_plan_path, page.get("page_id", ""))
    if page_plan_path.is_file():
        page_plan = read_json(page_plan_path)
        page_plan["updated"] = now_date()
        page_plan["status"] = page["status"]
        page_plan["title"] = page["title"]
        page_plan["summary"] = page["summary"]
        page_plan["director"] = page.get("director") or {}
        page_plan["layout_style"] = (page.get("director") or {}).get("layout_style", page_plan.get("layout_style", ""))
        page_plan["reading_flow"] = (page.get("director") or {}).get("page_rhythm", page_plan.get("reading_flow", ""))
        page_plan["visual_priority"] = (page.get("director") or {}).get("visual_priority", page_plan.get("visual_priority", ""))
        page_plan["source_excerpt"] = page.get("source_excerpt", page_plan.get("source_excerpt", ""))
        page_plan["panel_intent"] = page["panel_intent"]
        page_plan["close_reading_required"] = False
        page_plan["close_reading_refined"] = True
        page_plan["adaptation_status"] = "close_reading_refined_needs_review"
        plan_panels = {str(panel.get("panel_id") or ""): panel for panel in page_plan.get("panels") or []}
        for panel in page.get("panels") or []:
            target = plan_panels.get(str(panel.get("panel_id") or ""))
            if target:
                target.update(
                    {
                        key: panel.get(key)
                        for key in [
                            "title",
                            "reference_alias",
                            "caption",
                            "dialogue",
                            "prompt",
                            "fallback_prompt",
                            "panel_role",
                            "shot_type",
                            "visual_priority",
                            "camera_direction",
                            "layout",
                        ]
                    }
                )
        page_plan_path.write_text(json.dumps(page_plan, ensure_ascii=False, indent=2), encoding="utf-8")
        update_page_workflows(page_plan_path, page_plan)


def apply_refined_panel(panel: dict, refined_panel: dict, index: int) -> None:
    title = clean_text(refined_panel.get("title"), 80) or f"细读分镜 {index}"
    prompt = clean_text(refined_panel.get("prompt"), 800)
    if not prompt:
        prompt = clean_text(refined_panel.get("caption"), 240) or title
    panel_role = clean_text(refined_panel.get("panel_role"), 40) or panel.get("panel_role", "")
    shot_type = clean_text(refined_panel.get("shot_type"), 60) or panel.get("shot_type", "")
    visual_priority = clean_text(refined_panel.get("visual_priority"), 120)
    camera_direction = clean_text(refined_panel.get("camera_direction"), 120)
    prompt = enrich_prompt_with_director_notes(prompt, panel_role, shot_type, visual_priority, camera_direction)
    panel["title"] = title
    panel["reference_alias"] = clean_text(refined_panel.get("reference_alias"), 80)
    panel["panel_role"] = panel_role
    panel["shot_type"] = shot_type
    panel["visual_priority"] = visual_priority
    panel["camera_direction"] = camera_direction
    panel["caption"] = clean_text(refined_panel.get("caption"), 80)
    panel["dialogue"] = normalize_dialogue(refined_panel.get("dialogue"))
    panel["prompt"] = prompt
    panel["fallback_prompt"] = prompt
    panel["close_reading_refined"] = True


def enrich_prompt_with_director_notes(prompt: str, panel_role: str, shot_type: str, visual_priority: str, camera_direction: str) -> str:
    notes = []
    if panel_role:
        notes.append(f"Panel role: {panel_role}")
    if shot_type:
        notes.append(f"Shot type: {shot_type}")
    if visual_priority:
        notes.append(f"Visual priority: {visual_priority}")
    if camera_direction:
        notes.append(f"Camera direction and reader eye-flow: {camera_direction}")
    notes.append("Reserve clean negative space for possible caption or speech bubble; do not render text inside the image.")
    suffix = " ".join(notes)
    combined = f"{prompt} {suffix}".strip()
    return combined[:1200]


def normalize_dialogue(dialogue) -> list[dict]:
    rows = []
    if not isinstance(dialogue, list):
        return rows
    for item in dialogue[:2]:
        if not isinstance(item, dict):
            continue
        text = clean_text(item.get("text"), 60)
        if not text:
            continue
        rows.append(
            {
                "speaker": clean_text(item.get("speaker"), 20),
                "text": text,
                "position": clean_text(item.get("position"), 20) or "bottom",
            }
        )
    return rows


def update_page_workflows(page_plan_path: Path, page_plan: dict) -> None:
    panel_prompts = {str(panel.get("panel_id") or ""): str(panel.get("fallback_prompt") or panel.get("prompt") or "") for panel in page_plan.get("panels") or []}
    for panel in page_plan.get("panels") or []:
        panel_id = str(panel.get("panel_id") or "")
        if not panel_id:
            continue
        workflow_path = workflow_path_for_panel(page_plan_path, panel_id)
        if not workflow_path.is_file():
            continue
        workflow = read_json(workflow_path)
        changed = False
        for node in (workflow.get("prompt") or {}).values():
            if not isinstance(node, dict):
                continue
            inputs = node.setdefault("inputs", {})
            is_direct_node = node.get("class_type") == "OpenAICompatibleImageGenerate"
            is_local_positive = (
                node.get("class_type") == "CLIPTextEncode"
                and (node.get("_meta") or {}).get("comic_pipeline_role") == "positive_prompt"
            )
            if not is_direct_node and not is_local_positive:
                continue
            global_prompt = page_plan.get("global_prompt_block") or "中国神话幻想漫画，水墨与厚涂结合，清晰剪影，电影分镜。"
            prompt_key = "prompt" if is_direct_node else "text"
            inputs[prompt_key] = f"{global_prompt}\n\n{panel_prompts.get(panel_id, '')}".strip()
            changed = True
        if changed:
            workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")


def plan_path_for_page(episode_plan_path: Path, page_id: str) -> Path:
    match = re.search(r"EP0*(\d+)_P0*(\d+)", str(page_id), re.IGNORECASE)
    if not match:
        return episode_plan_path.with_name(f"{page_id.lower()}_plan.json")
    episode_number = int(match.group(1))
    page_number = int(match.group(2))
    return episode_plan_path.with_name(f"ssj_comic_ep{episode_number:02d}_p{page_number:03d}_plan.json")


def workflow_path_for_panel(page_plan_path: Path, panel_id: str) -> Path:
    suffix = re.sub(r"[^A-Za-z0-9_]+", "_", panel_id).lower()
    return page_plan_path.parent.parent / "workflows" / "comic" / f"{suffix}_fallback_v001.json"


def clean_text(value, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


if __name__ == "__main__":
    raise SystemExit(main())
