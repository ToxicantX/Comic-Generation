import argparse
import json
import re
from datetime import datetime
from pathlib import Path


CHARACTER_ALIASES = {
    "拓拔野": "tuobaye_turnaround",
    "白龙鹿": "bailonglu_reference",
    "神农": "shennong_turnaround",
    "黑衣少年": "",
    "黑衣老者": "",
    "青帝": "",
}

LAYOUT_PRESETS = {
    "splash_opening": [
        {"x": 0, "y": 0, "w": 1600, "h": 690, "role": "opening_splash", "shot_type": "wide_splash", "shape": "rect", "border": 0, "render_order": 1},
        {"x": 12, "y": 722, "w": 764, "h": 700, "role": "action_advance", "shot_type": "medium_action", "shape": "rect", "border": 0, "render_order": 2},
        {"x": 812, "y": 722, "w": 764, "h": 700, "role": "emotional_reaction", "shot_type": "reaction", "shape": "rect", "border": 0, "render_order": 3},
        {"x": 0, "y": 1446, "w": 1600, "h": 954, "role": "page_turn_hook", "shot_type": "bottom_splash", "shape": "rect", "border": 0, "render_order": 4},
    ],
    "diagonal_action": [
        {"x": 12, "y": 16, "w": 764, "h": 636, "role": "scene_setup", "shot_type": "establishing", "shape": "rect", "border": 0, "render_order": 1},
        {"x": 812, "y": 16, "w": 764, "h": 636, "role": "close_reaction", "shot_type": "close_reaction", "shape": "rect", "border": 0, "render_order": 2},
        {"x": 0, "y": 688, "w": 1600, "h": 800, "role": "action_splash", "shot_type": "action_splash", "shape": "slant_right", "slant": 96, "border": 0, "render_order": 3},
        {"x": 0, "y": 1512, "w": 1600, "h": 888, "role": "consequence_hook", "shot_type": "reveal", "shape": "rect", "border": 0, "render_order": 4},
    ],
    "bottom_reveal": [
        {"x": 12, "y": 16, "w": 504, "h": 552, "role": "detail_setup", "shot_type": "detail", "shape": "rect", "border": 0, "render_order": 1},
        {"x": 548, "y": 16, "w": 504, "h": 552, "role": "character_reaction", "shot_type": "reaction", "shape": "rect", "border": 0, "render_order": 2},
        {"x": 1072, "y": 16, "w": 504, "h": 552, "role": "action_trigger", "shot_type": "action", "shape": "rect", "border": 0, "render_order": 3},
        {"x": 0, "y": 604, "w": 1600, "h": 1796, "role": "reveal_splash", "shot_type": "reveal_splash", "shape": "rect", "border": 0, "render_order": 4},
    ],
    "bleed_tension": [
        {"x": 0, "y": 20, "w": 1600, "h": 1002, "role": "bleed_pressure", "shot_type": "bleed_splash", "shape": "rect", "border": 0, "render_order": 1},
        {"x": 12, "y": 1042, "w": 760, "h": 650, "role": "counter_action", "shot_type": "medium_action", "shape": "slant_left", "slant": 64, "border": 0, "render_order": 2},
        {"x": 816, "y": 1042, "w": 760, "h": 650, "role": "reaction_cut", "shot_type": "reaction", "shape": "slant_right", "slant": 64, "border": 0, "render_order": 3},
        {"x": 0, "y": 1716, "w": 1600, "h": 684, "role": "silent_hook", "shot_type": "quiet_transition", "shape": "rect", "border": 0, "render_order": 4},
    ],
    "inset_reaction": [
        {"x": 0, "y": 0, "w": 1600, "h": 636, "role": "wide_opening", "shot_type": "wide_establishing", "shape": "rect", "border": 0, "render_order": 1},
        {"x": 0, "y": 648, "w": 1600, "h": 1056, "role": "main_scene_action", "shot_type": "scene_splash", "shape": "rect", "border": 0, "render_order": 2},
        {"x": 1074, "y": 696, "w": 460, "h": 420, "role": "inset_reaction", "shot_type": "inset_reaction", "shape": "rect", "border": 0, "render_order": 3, "drop_shadow": True, "shadow_offset": 8},
        {"x": 0, "y": 1716, "w": 1600, "h": 684, "role": "page_transition", "shot_type": "transition", "shape": "rect", "border": 0, "render_order": 4},
    ],
}

LOCATION_ALIASES = {
    "南际山": "nanjishan_reference",
    "龙潭": "longtan_reference",
    "玉屏山": "",
    "玉屏峰": "",
    "天湖": "",
    "平原": "",
    "大河": "",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    plan = read_json(plan_path)
    excerpt = plan.get("source_excerpt") or plan.get("summary") or ""
    if not excerpt:
        raise SystemExit("Page plan has no source_excerpt or summary to refine from")

    characters = detect_terms(excerpt, CHARACTER_ALIASES)
    locations = detect_terms(excerpt, LOCATION_ALIASES)
    action_phrases = extract_action_phrases(excerpt)
    chunks = split_sentences(excerpt, 4)
    panel_specs = build_panel_specs(plan, chunks, characters, locations, action_phrases)

    for panel, spec in zip(plan.get("panels", []), panel_specs):
        panel["title"] = spec["title"]
        panel["reference_alias"] = spec["reference_alias"]
        panel["caption"] = spec["caption"]
        panel["dialogue"] = spec["dialogue"]
        panel["panel_role"] = spec["panel_role"]
        panel["shot_type"] = spec["shot_type"]
        panel["visual_priority"] = spec["visual_priority"]
        panel["prompt"] = spec["prompt"]
        panel["fallback_prompt"] = spec["prompt"]
        panel["draft_from_source_excerpt"] = True

    plan["updated"] = datetime.now().strftime("%Y-%m-%d")
    plan["draft_refined_from_source_excerpt"] = True
    plan["adaptation_status"] = "source_excerpt_panel_draft_needs_human_review"
    director = build_director_notes(plan, chunks, characters, locations, action_phrases)
    plan["director"] = director
    plan["layout_style"] = director["layout_style"]
    plan["reading_flow"] = director["page_rhythm"]
    plan["visual_priority"] = director["visual_priority"]
    apply_layout_preset(plan, director["layout_style"])
    plan["detected_characters"] = characters
    plan["detected_locations"] = locations

    output_path = Path(args.output) if args.output else plan_path
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "ok": True,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "plan": str(output_path),
        "page_id": plan.get("page_id"),
        "panels": len(panel_specs),
        "detected_characters": characters,
        "detected_locations": locations,
        "adaptation_status": plan["adaptation_status"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def detect_terms(text: str, alias_map: dict[str, str]) -> list[str]:
    return [term for term in alias_map if term in text]


def extract_action_phrases(text: str) -> list[str]:
    verbs = ["骑", "飞奔", "抱住", "松手", "唱歌", "欢鸣", "逃", "路过", "洗衣", "查看", "寻找", "大笑", "捕鱼", "生火", "烤", "藏", "挥鞭", "怒吼", "跟"]
    phrases = []
    sentences = sentence_list(text)
    for sentence in sentences:
        if any(verb in sentence for verb in verbs):
            phrases.append(sentence)
    return phrases[:8]


def split_sentences(text: str, parts: int) -> list[str]:
    sentences = sentence_list(text)
    if not sentences:
        return [text] * parts
    chunks = [[] for _ in range(parts)]
    for index, sentence in enumerate(sentences):
        chunks[min(parts - 1, int(index * parts / max(1, len(sentences))))].append(sentence)
    return ["".join(chunk).strip() or sentences[min(i, len(sentences) - 1)] for i, chunk in enumerate(chunks)]


def sentence_list(text: str) -> list[str]:
    pieces = re.split(r"(?<=[。！？；])", re.sub(r"\s+", "", text))
    return [piece for piece in pieces if piece]


def build_panel_specs(plan: dict, chunks: list[str], characters: list[str], locations: list[str], actions: list[str]) -> list[dict]:
    chapter_title = plan.get("title", "comic page")

    roles = [
        ("开场", "wide establishing shot", "拉开场景，交代人物所处环境", "主环境和人物位置必须清楚"),
        ("行动", "dynamic medium action shot", "呈现本页最明确的动作", "动作方向、速度线和身体姿态优先"),
        ("反应", "close expressive character beat", "抓住人物情绪变化", "脸部表情、手势和视线方向优先"),
        ("转折", "dramatic page-turn hook", "留下下一页的悬念", "画面应有强烈悬念或揭示感"),
    ]
    specs = []
    for index, (label, shot, intent, visual_priority) in enumerate(roles):
        chunk = chunks[index] if index < len(chunks) else chunks[-1]
        chunk_characters = detect_terms(chunk, CHARACTER_ALIASES) or characters
        chunk_locations = detect_terms(chunk, LOCATION_ALIASES) or locations
        dominant_character = chunk_characters[0] if chunk_characters else "主角"
        dominant_location = chunk_locations[0] if chunk_locations else "大荒途中"
        fallback_alias = CHARACTER_ALIASES.get(dominant_character, "") or LOCATION_ALIASES.get(dominant_location, "")
        action = actions[index] if index < len(actions) else summarize(chunk, 70)
        title = f"{chapter_title} / {label}"
        caption = summarize(chunk, 34) if index in (0, 3) else ""
        dialogue = extract_dialogue(chunk)
        prompt = (
            f"{shot} for an ancient Chinese mythic fantasy comic page. "
            f"Scene: {dominant_location}. Characters: {', '.join(chunk_characters) if chunk_characters else dominant_character}. "
            f"Story action: {action}. "
            f"Panel purpose: {intent}. Composition priority: {visual_priority}. "
            f"Use clear foreground, midground, and background separation, strong silhouette readability, cinematic eye-flow, "
            f"premium ink-and-watercolor graphic novel style, no baked-in text, no watermark."
        )
        specs.append(
            {
                "title": title,
                "reference_alias": fallback_alias,
                "caption": caption,
                "dialogue": dialogue[:1],
                "panel_role": label,
                "shot_type": shot,
                "visual_priority": visual_priority,
                "prompt": prompt,
            }
        )
    return specs


def build_director_notes(plan: dict, chunks: list[str], characters: list[str], locations: list[str], actions: list[str]) -> dict:
    source = "".join(chunks)
    layout_style = choose_layout_style(source, actions)
    page_turn_hook = summarize(chunks[-1] if chunks else source, 46)
    camera_flow = [
        "先用环境或主视觉建立空间",
        "转入人物动作或冲突核心",
        "插入表情/细节反应强化情绪",
        "以揭示或悬念收束到下一页",
    ]
    return {
        "page_rhythm": "铺垫-行动-反应-悬念",
        "emotional_arc": infer_emotional_arc(source),
        "layout_style": layout_style,
        "visual_priority": infer_visual_priority(source, characters, locations),
        "lettering_strategy": "旁白只保留必要剧情推进，对白优先放在人物视线外的上方或下方留白区。",
        "page_turn_hook": page_turn_hook,
        "camera_flow": camera_flow,
    }


def apply_layout_preset(plan: dict, layout_style: str) -> None:
    layouts = LAYOUT_PRESETS.get(layout_style) or LAYOUT_PRESETS["splash_opening"]
    for index, panel in enumerate(plan.get("panels", [])):
        layout = dict(layouts[min(index, len(layouts) - 1)])
        panel["layout"] = layout
        panel.setdefault("panel_role", layout.get("role", ""))
        panel.setdefault("shot_type", layout.get("shot_type", ""))
    page = plan.setdefault("page", {})
    page.setdefault("safe_margin", 48)
    page.setdefault("paper_border", 0)


def choose_layout_style(text: str, actions: list[str]) -> str:
    compacted = compact_text(text + "".join(actions))
    if any(cue in compacted for cue in ("冲", "奔", "战", "追", "挥", "怒吼", "飞", "跃")):
        return "diagonal_action"
    if any(cue in compacted for cue in ("水妖", "龙女", "巨", "压", "惊", "惧")):
        return "bleed_tension"
    if any(cue in compacted for cue in ("出现", "看见", "发现", "忽然", "只见")):
        return "bottom_reveal"
    if any(cue in compacted for cue in ("笑", "泪", "望", "凝", "惊", "怒")):
        return "inset_reaction"
    return "splash_opening"


def infer_emotional_arc(text: str) -> str:
    compacted = compact_text(text)
    if any(cue in compacted for cue in ("惊", "惧", "慌", "骇")):
        return "疑惑到惊惧"
    if any(cue in compacted for cue in ("怒", "喝", "吼")):
        return "压抑到爆发"
    if any(cue in compacted for cue in ("笑", "喜", "欢")):
        return "紧张中出现轻松反差"
    return "平静铺垫到悬念"


def infer_visual_priority(text: str, characters: list[str], locations: list[str]) -> str:
    if characters:
        return f"{characters[0]}的动作与情绪变化"
    if locations:
        return f"{locations[0]}的空间压迫感"
    return "主角、场景和动作方向的清晰关系"


def extract_dialogue(text: str) -> list[dict]:
    matches = re.findall(r"“([^”]{1,36})”", text)
    if not matches:
        return []
    return [{"speaker": "", "text": matches[0], "position": "bottom"}]


def summarize(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", "", text)
    return compact if len(compact) <= limit else compact[:limit] + "..."


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


if __name__ == "__main__":
    raise SystemExit(main())
