import argparse
import json
import re
from datetime import datetime
from pathlib import Path


LAYOUT_PRESETS = [
    {
        "name": "splash_opening",
        "reading_flow": "top establishing panel, mid action beat, bottom page-turn splash",
        "visual_priority": "top establishing panel and bottom hook panel",
        "panels": [
            {"x": 0, "y": 0, "w": 1600, "h": 690, "role": "opening_splash", "shot_type": "wide_splash", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 12, "y": 722, "w": 764, "h": 700, "role": "action_advance", "shot_type": "medium_action", "shape": "rect", "border": 0, "render_order": 2},
            {"x": 812, "y": 722, "w": 764, "h": 700, "role": "emotional_reaction", "shot_type": "reaction", "shape": "rect", "border": 0, "render_order": 3},
            {"x": 0, "y": 1446, "w": 1600, "h": 954, "role": "page_turn_hook", "shot_type": "bottom_splash", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
    {
        "name": "diagonal_action",
        "reading_flow": "upper setup, diagonal action cut, lower consequence panel",
        "visual_priority": "diagonal action panel",
        "panels": [
            {"x": 12, "y": 16, "w": 764, "h": 636, "role": "scene_setup", "shot_type": "establishing", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 812, "y": 16, "w": 764, "h": 636, "role": "close_reaction", "shot_type": "close_reaction", "shape": "rect", "border": 0, "render_order": 2},
            {"x": 0, "y": 688, "w": 1600, "h": 800, "role": "action_splash", "shot_type": "action_splash", "shape": "slant_right", "slant": 96, "border": 0, "render_order": 3},
            {"x": 0, "y": 1512, "w": 1600, "h": 888, "role": "consequence_hook", "shot_type": "reveal", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
    {
        "name": "bottom_reveal",
        "reading_flow": "small setup beats, then a dominant bottom reveal",
        "visual_priority": "bottom reveal splash",
        "panels": [
            {"x": 12, "y": 16, "w": 504, "h": 552, "role": "detail_setup", "shot_type": "detail", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 548, "y": 16, "w": 504, "h": 552, "role": "character_reaction", "shot_type": "reaction", "shape": "rect", "border": 0, "render_order": 2},
            {"x": 1072, "y": 16, "w": 504, "h": 552, "role": "action_trigger", "shot_type": "action", "shape": "rect", "border": 0, "render_order": 3},
            {"x": 0, "y": 604, "w": 1600, "h": 1796, "role": "reveal_splash", "shot_type": "reveal_splash", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
    {
        "name": "bleed_tension",
        "reading_flow": "near-bleed opening pressure, two reaction beats, final narrow silence",
        "visual_priority": "large near-bleed pressure panel",
        "panels": [
            {"x": 0, "y": 20, "w": 1600, "h": 1002, "role": "bleed_pressure", "shot_type": "bleed_splash", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 12, "y": 1042, "w": 760, "h": 650, "role": "counter_action", "shot_type": "medium_action", "shape": "slant_left", "slant": 64, "border": 0, "render_order": 2},
            {"x": 816, "y": 1042, "w": 760, "h": 650, "role": "reaction_cut", "shot_type": "reaction", "shape": "slant_right", "slant": 64, "border": 0, "render_order": 3},
            {"x": 0, "y": 1716, "w": 1600, "h": 684, "role": "silent_hook", "shot_type": "quiet_transition", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
    {
        "name": "inset_reaction",
        "reading_flow": "main scene panel with an inset reaction, then a lower transition",
        "visual_priority": "main scene with upper-right inset reaction",
        "panels": [
            {"x": 0, "y": 0, "w": 1600, "h": 636, "role": "wide_opening", "shot_type": "wide_establishing", "shape": "rect", "border": 0, "render_order": 1},
            {"x": 0, "y": 648, "w": 1600, "h": 1056, "role": "main_scene_action", "shot_type": "scene_splash", "shape": "rect", "border": 0, "render_order": 2},
            {"x": 1074, "y": 696, "w": 460, "h": 420, "role": "inset_reaction", "shot_type": "inset_reaction", "shape": "rect", "border": 0, "render_order": 3, "drop_shadow": True, "shadow_offset": 8},
            {"x": 0, "y": 1716, "w": 1600, "h": 684, "role": "page_transition", "shot_type": "transition", "shape": "rect", "border": 0, "render_order": 4},
        ],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plans", nargs="+", help="Plan JSON files or glob patterns.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = expand_paths(args.plans)
    results = []
    for path in paths:
        plan = read_json(path)
        page_number = page_number_from_id(plan.get("page_id") or path.stem)
        preset = LAYOUT_PRESETS[(page_number - 1) % len(LAYOUT_PRESETS)]
        apply_preset(plan, preset)
        if not args.dry_run:
            path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append({"plan": str(path), "page_id": plan.get("page_id", ""), "layout_style": preset["name"], "updated": not args.dry_run})

    print(json.dumps({"ok": True, "count": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 0


def expand_paths(patterns: list[str]) -> list[Path]:
    paths = []
    for pattern in patterns:
        matched = sorted(Path().glob(pattern)) if any(char in pattern for char in "*?[]") else [Path(pattern)]
        paths.extend(path for path in matched if path.is_file())
    return paths


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def page_number_from_id(page_id: str) -> int:
    match = re.search(r"P(\d+)$", str(page_id), flags=re.IGNORECASE)
    return int(match.group(1)) if match else 1


def apply_preset(plan: dict, preset: dict) -> None:
    panels = plan.get("panels", [])
    for index, panel in enumerate(panels):
        layout = dict(preset["panels"][min(index, len(preset["panels"]) - 1)])
        panel["layout"] = layout
        panel["panel_role"] = layout.get("role", "")
        panel["shot_type"] = layout.get("shot_type", "")
    plan["layout_style"] = preset["name"]
    plan["reading_flow"] = preset["reading_flow"]
    plan["visual_priority"] = preset["visual_priority"]
    page = plan.setdefault("page", {})
    page.setdefault("safe_margin", 48)
    page.setdefault("paper_border", 0)
    plan["layout_updated"] = datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
