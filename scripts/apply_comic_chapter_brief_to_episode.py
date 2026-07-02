import argparse
import json
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode-plan", required=True)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--expand-pages", action="store_true")
    args = parser.parse_args()

    episode_plan_path = Path(args.episode_plan)
    brief_path = Path(args.brief)
    episode = read_json(episode_plan_path)
    brief = read_json(brief_path)

    beats_by_page = {int(item["page_number"]): item for item in brief.get("page_beats", [])}
    if args.expand_pages:
        ensure_pages_for_beats(episode, brief, beats_by_page)

    pages_updated = 0
    for index, page in enumerate(episode.get("pages", []), start=1):
        beat = beats_by_page.get(index)
        if not beat:
            continue
        pages_updated += 1

        page["status"] = "brief_applied_needs_panel_close_reading"
        page["source_excerpt"] = beat.get("source_excerpt", "")
        page["summary"] = beat.get("summary", page.get("summary", ""))
        page["panel_intent"] = beat.get("panel_intent", [])
        page["close_reading_required"] = True

        for panel_index, panel in enumerate(page.get("panels", []), start=1):
            intent = beat.get("panel_intent", [])
            panel["title"] = f"{beat.get('title', page.get('title', 'Page'))} / panel {panel_index}"
            panel["caption"] = ""
            panel["dialogue"] = []
            panel["prompt"] = (
                f"Draft panel {panel_index} for {brief.get('chapter_title')}. "
                f"{intent[min(panel_index - 1, len(intent) - 1)] if intent else beat.get('summary', '')} "
                "Use the source excerpt in the page plan for close reading; ancient Chinese mythic fantasy comic, no text."
            )

    episode["updated"] = datetime.now().strftime("%Y-%m-%d")
    episode["skeleton"] = True
    episode["brief_applied"] = True
    episode["close_reading_required"] = True
    episode["chapter_brief"] = str(brief_path)
    episode["source_excerpt_char_count"] = brief.get("excerpt_char_count")
    episode["adaptation_status"] = "chapter_brief_applied_needs_human_panel_rewrite"

    output_path = Path(args.output) if args.output else episode_plan_path
    output_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "ok": True,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "episode_plan": str(output_path),
        "brief": str(brief_path),
        "pages_updated": pages_updated,
        "episode_pages": len(episode.get("pages", [])),
        "brief_pages_available": len(beats_by_page),
        "adaptation_status": episode["adaptation_status"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ensure_pages_for_beats(episode: dict, brief: dict, beats_by_page: dict[int, dict]) -> None:
    pages = episode.setdefault("pages", [])
    existing_by_number = {}
    for page in pages:
        number = page_number(page.get("page_id", ""))
        if number:
            existing_by_number[number] = page

    for number in sorted(beats_by_page):
        if number in existing_by_number:
            continue
        page_id = f"{episode.get('episode_id', brief.get('episode_id', 'SSJ_COMIC_EPXX'))}_P{number:03d}"
        beat = beats_by_page[number]
        pages.append(
            {
                "page_id": page_id,
                "status": "brief_applied_needs_panel_close_reading",
                "beat_ids": [],
                "title": beat.get("title", f"Page {number:02d}"),
                "summary": beat.get("summary", ""),
                "panels": [
                    {
                        "title": f"{beat.get('title', page_id)} / panel {panel_index}",
                        "reference_alias": "",
                        "caption": "",
                        "dialogue": [],
                        "prompt": "",
                    }
                    for panel_index in range(1, 5)
                ],
            }
        )

    pages.sort(key=lambda page: page_number(page.get("page_id", "")) or 9999)


def page_number(page_id: str) -> int | None:
    import re

    match = re.search(r"_P(\d+)$", str(page_id))
    return int(match.group(1)) if match else None


if __name__ == "__main__":
    raise SystemExit(main())
