import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
from image_provider import generate_from_workflow, normalize_backend

WORKSPACE = Path(os.getenv("COMIC_PIPELINE_WORKSPACE") or PACKAGE_ROOT)
COMFY_OUTPUT_ROOT = Path(os.getenv("COMIC_PIPELINE_COMFY_OUTPUT_ROOT") or (WORKSPACE / "output"))
OUTPUT_ROOT = Path(os.getenv("COMIC_PIPELINE_OUTPUT_ROOT") or (COMFY_OUTPUT_ROOT / "ComicPipeline"))
MANIFESTS = Path(os.getenv("COMIC_PIPELINE_MANIFEST_DIR") or (WORKSPACE / "manifests"))
SCRIPTS = WORKSPACE / "scripts"
WORKFLOWS = WORKSPACE / "workflows" / "comic"
DEFAULT_COMFY_URL = os.getenv("COMIC_PIPELINE_COMFY_URL", "http://127.0.0.1:8188")
DEFAULT_IMAGE_BACKEND = normalize_backend()
DEFAULT_NOVEL = os.getenv("COMIC_PIPELINE_NOVEL_PATH") or str(WORKSPACE / "novel.txt")
DEFAULT_PAGES = int(os.getenv("COMIC_PIPELINE_DEFAULT_PAGES", "8") or "8")
DEFAULT_ENCODING = os.getenv("COMIC_PIPELINE_ENCODING", "gb18030")

os.environ.setdefault("COMIC_PIPELINE_WORKSPACE", str(WORKSPACE))
os.environ.setdefault("COMIC_PIPELINE_COMFY_OUTPUT_ROOT", str(COMFY_OUTPUT_ROOT))
os.environ.setdefault("COMIC_PIPELINE_OUTPUT_ROOT", str(OUTPUT_ROOT))

STAGES = [
    "preflight",
    "comfy_health",
    "anchor_assets",
    "anchor_gate",
    "chapter_brief",
    "apply_brief",
    "page_plans",
    "refine_plans",
    "workflows",
    "draft_review",
    "draft_qa",
    "generate_panels",
    "assemble_pages",
    "status_report",
    "lettering_qa",
    "consistency_qa",
    "image_health_qa",
]


def main() -> int:
    args = parse_args()
    started = datetime.now().isoformat(timespec="seconds")
    context = build_context(args)
    result = {
        "updated": started,
        "completed": False,
        "blocked": False,
        "waiting": False,
        "waiting_reason": "",
        "waiting_detail": None,
        "partial": False,
        "dry_run": bool(args.dry_run),
        "generate_images": bool(args.generate_images and not args.skip_image_generation),
        "image_backend": args.image_backend,
        "workspace": str(WORKSPACE),
        "comfy_url": args.comfy_url,
        "episode_number": context.get("episode_number"),
        "episode_id": context.get("episode_id"),
        "episode_title": context.get("episode_title"),
        "episode_plan": str(context["episode_plan_path"]),
        "paths": {key: str(value) for key, value in context["paths"].items()},
        "stage_order": selected_stages(args),
        "stages": [],
        "summary": {},
    }

    try:
        for stage_name in STAGES:
            if stage_name not in result["stage_order"]:
                continue
            stage = run_stage(stage_name, args, context, result)
            result["stages"].append(stage)
            if stage["status"] == "failed":
                result["blocked"] = True
                break
            if stage.get("stop_pipeline"):
                if stage["status"] == "waiting":
                    result["waiting"] = True
                else:
                    result["blocked"] = True
                break

        result["summary"] = summarize_pipeline(result)
        result["completed"] = (
            not result["blocked"]
            and not result["waiting"]
            and result["summary"]["failed"] == 0
            and result["summary"]["blocked"] == 0
            and result["summary"].get("waiting", 0) == 0
            and (args.dry_run or result["summary"].get("waiting_for_upstream", 0) == 0)
            and result["summary"].get("partial", 0) == 0
        )
        if any(stage["status"] == "blocked" for stage in result["stages"]):
            result["blocked"] = True
            result["completed"] = False
        if any(stage["status"] == "waiting" for stage in result["stages"]):
            result["waiting"] = True
            result["completed"] = False
            waiting_stage = next((stage for stage in result["stages"] if stage["status"] == "waiting"), {})
            result["waiting_reason"] = waiting_stage.get("waiting_reason", "waiting")
            result["waiting_detail"] = waiting_stage.get("waiting_detail")
        if any(stage["status"] == "partial" for stage in result["stages"]):
            result["partial"] = True
            result["completed"] = False
    finally:
        result_path = Path(args.result_path) if args.result_path else context["paths"]["pipeline_result"]
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result["finished"] = datetime.now().isoformat(timespec="seconds")
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        result_path.write_text(payload, encoding="utf-8")
        safe_print(payload)

    partial_success = (
        result.get("partial")
        and not result["blocked"]
        and not result["waiting"]
        and result["summary"].get("failed", 0) == 0
        and result["summary"].get("blocked", 0) == 0
    )
    return 0 if result["completed"] or partial_success or args.dry_run else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or validate the longform comic episode pipeline.")
    parser.add_argument("--episode-number", type=int, default=0)
    parser.add_argument("--episode-plan", default="")
    parser.add_argument("--novel", default=DEFAULT_NOVEL)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    parser.add_argument("--image-backend", choices=["direct_api", "comfyui"], default=DEFAULT_IMAGE_BACKEND)
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    parser.add_argument("--excerpt-chars", type=int, default=3600)
    parser.add_argument("--encoding", default=DEFAULT_ENCODING)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--generate-images", action="store_true")
    parser.add_argument("--skip-image-generation", action="store_true")
    parser.add_argument("--create-chapter-brief", action="store_true")
    parser.add_argument("--apply-chapter-brief", action="store_true")
    parser.add_argument("--expand-pages", action="store_true")
    parser.add_argument("--refine-page-plans", action="store_true")
    parser.add_argument("--overwrite-page-plans", action="store_true")
    parser.add_argument("--assemble-pages", action="store_true")
    parser.add_argument("--auto-image-size", dest="auto_image_size", action="store_true", default=True)
    parser.add_argument("--no-auto-image-size", dest="auto_image_size", action="store_false")
    parser.add_argument("--run-lettering-qa", action="store_true")
    parser.add_argument("--run-consistency-qa", action="store_true")
    parser.add_argument("--run-image-health-qa", action="store_true")
    parser.add_argument("--check-comfy-health", action="store_true")
    parser.add_argument("--allow-anchor-missing", action="store_true")
    parser.add_argument("--allow-draft-warnings", action="store_true")
    parser.add_argument("--only-stage", default="")
    parser.add_argument("--from-stage", default="")
    parser.add_argument("--until-stage", default="")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--max-panels", type=int, default=0)
    parser.add_argument("--retry-count", type=int, default=0)
    parser.add_argument("--cooldown-seconds", type=int, default=240)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--max-idle-polls", type=int, default=120)
    parser.add_argument("--max-prompt-polls", type=int, default=240)
    parser.add_argument("--generation-context", default="")
    parser.add_argument("--run-label", default="pipeline")
    parser.add_argument("--result-path", default="")
    return parser.parse_args()


def build_context(args: argparse.Namespace) -> dict:
    episode_plan_path = Path(args.episode_plan) if args.episode_plan else None
    if not episode_plan_path and args.episode_number:
        episode_plan_path = MANIFESTS / f"ssj_comic_episode{args.episode_number:02d}_pages.json"
    if not episode_plan_path:
        raise SystemExit("--episode-plan or --episode-number is required.")

    episode = read_json(episode_plan_path) if episode_plan_path.is_file() else {}
    episode_number = args.episode_number or infer_episode_number(episode, episode_plan_path)
    plan_stem = episode_plan_path.stem.removesuffix("_pages")
    is_legacy_plan = plan_stem.startswith("ssj_comic_episode")
    if episode_number and is_legacy_plan:
        long_stem = f"ssj_comic_episode{episode_number:02d}"
        short_stem = f"ssj_comic_ep{episode_number:02d}"
    else:
        safe_id = safe_stem(plan_stem or episode.get("episode_id") or episode_plan_path.stem)
        long_stem = safe_id
        short_stem = safe_id

    episode_id = episode.get("episode_id") or (f"SSJ_COMIC_EP{episode_number:02d}" if episode_number else "")
    review_root = OUTPUT_ROOT / "review_packages"
    paths = {
        "chapter_brief": MANIFESTS / f"{short_stem}_chapter_brief.json",
        "page_plan_result": MANIFESTS / f"{long_stem}_page_plan_create_result.json",
        "page_refine_result": MANIFESTS / f"{long_stem}_page_plan_refine_result.json",
        "workflow_create_result": MANIFESTS / f"{long_stem}_workflow_create_result.json",
        "draft_review_json": MANIFESTS / f"{long_stem}_draft_review.json",
        "draft_review_md": review_root / f"{episode_id}_draft_review.md",
        "draft_qa_json": MANIFESTS / f"{long_stem}_draft_qa.json",
        "draft_qa_md": review_root / f"{episode_id}_draft_qa.md",
        "health": MANIFESTS / "comic_pipeline_health.json",
        "recovery_result": MANIFESTS / f"{long_stem}_recovery_run.json",
        "status_json": MANIFESTS / f"{long_stem}_status.json",
        "status_md": review_root / f"{episode_id}_status.md",
        "lettering_qa_json": MANIFESTS / f"{long_stem}_lettering_qa.json",
        "lettering_qa_md": review_root / f"{episode_id}_lettering_qa.md",
        "consistency_qa_json": MANIFESTS / f"{long_stem}_consistency_qa.json",
        "consistency_qa_md": review_root / f"{episode_id}_consistency_qa.md",
        "image_health_qa_json": MANIFESTS / f"{long_stem}_image_health_qa.json",
        "image_health_qa_md": review_root / f"{episode_id}_image_health_qa.md",
        "pipeline_result": MANIFESTS / f"{long_stem}_pipeline_run.json",
    }
    return {
        "episode": episode,
        "episode_plan_path": episode_plan_path,
        "episode_number": episode_number,
        "episode_id": episode_id,
        "episode_title": episode.get("episode_title", ""),
        "long_stem": long_stem,
        "short_stem": short_stem,
        "generation_context_path": Path(args.generation_context) if args.generation_context else None,
        "paths": paths,
    }


def selected_stages(args: argparse.Namespace) -> list[str]:
    if args.only_stage:
        requested = [item.strip() for item in args.only_stage.split(",") if item.strip()]
        unknown = [item for item in requested if item not in STAGES]
        if unknown:
            raise SystemExit(f"Unknown stage(s): {', '.join(unknown)}")
        requested_set = set(requested)
        return [stage for stage in STAGES if stage in requested_set]

    if args.from_stage and args.from_stage not in STAGES:
        raise SystemExit(f"Unknown --from-stage: {args.from_stage}")
    if args.until_stage and args.until_stage not in STAGES:
        raise SystemExit(f"Unknown --until-stage: {args.until_stage}")
    start = STAGES.index(args.from_stage) if args.from_stage else 0
    end = STAGES.index(args.until_stage) if args.until_stage else len(STAGES) - 1
    if start > end:
        raise SystemExit("--from-stage must come before --until-stage.")

    stages = STAGES[start : end + 1]
    if not args.create_chapter_brief and "chapter_brief" in stages:
        pass
    if not args.apply_chapter_brief and "apply_brief" in stages:
        pass
    return stages


def run_stage(stage_name: str, args: argparse.Namespace, context: dict, pipeline_result: dict) -> dict:
    handlers = {
        "preflight": stage_preflight,
        "anchor_assets": stage_anchor_assets,
        "anchor_gate": stage_anchor_gate,
        "chapter_brief": stage_chapter_brief,
        "apply_brief": stage_apply_brief,
        "page_plans": stage_page_plans,
        "refine_plans": stage_refine_plans,
        "workflows": stage_workflows,
        "draft_review": stage_draft_review,
        "draft_qa": stage_draft_qa,
        "comfy_health": stage_comfy_health,
        "generate_panels": stage_generate_panels,
        "assemble_pages": stage_assemble_pages,
        "status_report": stage_status_report,
        "lettering_qa": stage_lettering_qa,
        "consistency_qa": stage_consistency_qa,
        "image_health_qa": stage_image_health_qa,
    }
    return handlers[stage_name](args, context, pipeline_result)


def base_stage(name: str) -> dict:
    return {
        "name": name,
        "status": "pending",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": "",
        "message": "",
        "inputs": {},
        "outputs": {},
        "command": [],
        "exit_code": None,
        "stdout_tail": [],
        "stderr_tail": [],
    }


def finish(stage: dict, status: str, message: str = "", **extra) -> dict:
    stage["status"] = status
    stage["message"] = message
    stage["finished"] = datetime.now().isoformat(timespec="seconds")
    stage.update(extra)
    return stage


def stage_preflight(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("preflight")
    required_scripts = [
        "create_comic_chapter_brief.ps1",
        "apply_comic_chapter_brief_to_episode.ps1",
        "create_comic_page_plans.ps1",
        "refine_comic_episode_page_plans.ps1",
        "create_comic_episode_workflows_from_page_plans.ps1",
        "build_comic_episode_draft_review.ps1",
        "build_comic_episode_draft_qa.ps1",
        "test_comic_pipeline_health.ps1",
        "run_comic_episode_recovery.ps1",
        "build_comic_page_from_panels.ps1",
        "build_comic_status_report.ps1",
        "build_comic_lettering_qa.py",
        "build_comic_image_health_qa.py",
    ]
    missing_scripts = [name for name in required_scripts if not (SCRIPTS / name).is_file()]
    checks = {
        "episode_plan_exists": context["episode_plan_path"].is_file(),
        "novel_exists": resolve_novel_path(args.novel).is_file(),
        "missing_scripts": missing_scripts,
    }
    stage["outputs"] = checks
    if missing_scripts:
        return finish(stage, "failed", "Required pipeline scripts are missing.")
    if not checks["episode_plan_exists"]:
        return finish(stage, "failed", "Episode plan does not exist.")
    return finish(stage, "passed", "Pipeline inputs and script entrypoints are present.")


def stage_anchor_assets(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("anchor_assets")
    state = reference_alias_state(context)
    missing_files = state["missing_reference_files"]
    candidates = state["anchor_workflow_candidates"]
    stage["outputs"] = {
        "missing_reference_files": missing_files,
        "anchor_workflow_candidates": candidates,
    }
    if not missing_files:
        return finish(stage, "skipped_existing", "All referenced anchor files already exist.")
    without_candidates = [item for item in missing_files if item["alias"] not in candidates]
    if without_candidates:
        return finish(stage, "blocked", "Some missing anchors do not have matching image workflows.", blocks_image_generation=True)
    if args.skip_image_generation or not args.generate_images:
        return finish(stage, "skipped_disabled", "Anchor generation was not requested.", blocks_image_generation=True)
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: missing anchor workflows would be submitted before panels.", blocks_image_generation=True)

    if args.image_backend == "direct_api":
        runs = []
        for item in missing_files:
            alias = item["alias"]
            workflow = Path(candidates[alias]["workflow"])
            output = Path(item["path"])
            run = {
                "alias": alias,
                "workflow": str(workflow),
                "expected_path": str(output),
                "backend": "direct_api",
                "completed": False,
                "error": "",
            }
            try:
                generated = generate_from_workflow(
                    workflow,
                    output,
                    env_path=os.getenv("COMIC_PIPELINE_IMAGE_ENV_PATH") or None,
                )
                run["result"] = generated
                run["completed"] = bool(generated.get("completed") and output.is_file())
                if not run["completed"]:
                    run["error"] = "Direct image provider did not create the expected anchor file."
            except Exception as exc:
                run["error"] = str(exc)
            runs.append(run)
            if not run["completed"]:
                stage["runs"] = runs
                return finish(stage, "failed", run["error"] or "Anchor generation failed.")
        stage["runs"] = runs
        return finish(stage, "passed", "Missing anchor workflows completed with the direct image API.")

    existing_jobs = find_existing_anchor_jobs(args.comfy_url, missing_files)
    if existing_jobs:
        stage["outputs"]["existing_anchor_jobs"] = existing_jobs
        return finish(
            stage,
            "waiting",
            "One or more missing anchor workflows are already queued or running in ComfyUI; resume after they finish.",
            blocks_image_generation=True,
            stop_pipeline=True,
        )

    runs = []
    for item in missing_files:
        alias = item["alias"]
        workflow = candidates[alias]["workflow"]
        result_path = MANIFESTS / "anchor_runs" / f"{safe_stem(alias)}_anchor_run.json"
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPTS / "run_image_workflow_and_wait.ps1"),
            "-WorkflowPath",
            workflow,
            "-ShotId",
            alias,
            "-ResultPath",
            str(result_path),
            "-PollSeconds",
            "5",
            "-MaxPolls",
            str(args.max_prompt_polls),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        runs.append(
            {
                "alias": alias,
                "workflow": workflow,
                "expected_path": item["path"],
                "result_path": str(result_path),
                "exit_code": completed.returncode,
                "file_exists_after": Path(item["path"]).is_file(),
                "stdout_tail": tail_lines(completed.stdout),
                "stderr_tail": tail_lines(completed.stderr),
            }
        )
        if completed.returncode != 0 or not Path(item["path"]).is_file():
            stage["runs"] = runs
            return finish(stage, "failed", "Anchor workflow failed or did not create the expected file.")
    stage["runs"] = runs
    return finish(stage, "passed", "Missing anchor workflows completed.")


def stage_anchor_gate(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("anchor_gate")
    episode = read_json(context["episode_plan_path"])
    state = reference_alias_state(context)
    unknown_aliases = state["unknown_aliases"]
    missing_files = state["missing_reference_files"]

    stage["outputs"] = {
        "used_reference_aliases": state["used_reference_aliases"],
        "unknown_aliases": unknown_aliases,
        "missing_reference_files": missing_files,
        "episode_anchor_gate": episode.get("anchor_gate", {}),
    }
    if unknown_aliases or missing_files:
        status = "passed" if args.allow_anchor_missing else "blocked"
        message = "Reference anchor aliases are not ready for image submission."
        return finish(stage, status, message, blocks_image_generation=True)
    return finish(stage, "passed", "All used reference aliases resolve to existing files.")


def stage_chapter_brief(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("chapter_brief")
    output = context["paths"]["chapter_brief"]
    stage["outputs"] = {"brief": str(output)}
    if not args.create_chapter_brief:
        status = "skipped_existing" if output.is_file() else "skipped_disabled"
        return finish(stage, status, "Chapter brief generation was not requested.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: chapter brief command was not executed.")
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "create_comic_chapter_brief.ps1"),
        "-EpisodeNumber",
        str(context["episode_number"]),
        "-NovelPath",
        str(resolve_novel_path(args.novel)),
        "-OutputPath",
        str(output),
        "-Encoding",
        args.encoding,
        "-ExcerptChars",
        str(args.excerpt_chars),
        "-Pages",
        str(args.pages),
    ]
    return run_command_stage(stage, cmd, output)


def stage_apply_brief(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("apply_brief")
    brief = context["paths"]["chapter_brief"]
    stage["inputs"] = {"brief": str(brief), "episode_plan": str(context["episode_plan_path"])}
    if not args.apply_chapter_brief:
        return finish(stage, "skipped_disabled", "Applying chapter brief was not requested.")
    if not brief.is_file():
        return finish(stage, "failed", "Chapter brief is required before applying it.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: apply brief command was not executed.")
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "apply_comic_chapter_brief_to_episode.ps1"),
        "-EpisodePlanPath",
        str(context["episode_plan_path"]),
        "-BriefPath",
        str(brief),
    ]
    if args.expand_pages:
        cmd.append("-ExpandPages")
    return run_command_stage(stage, cmd, context["episode_plan_path"])


def stage_page_plans(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("page_plans")
    output = context["paths"]["page_plan_result"]
    stage["outputs"] = {"page_plan_result": str(output)}
    if output.is_file() and not args.force and not args.overwrite_page_plans and page_plan_result_complete(output):
        return finish(stage, "skipped_existing", "Existing page plan result is complete.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: page plan command was not executed.")
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "create_comic_page_plans.ps1"),
        "-EpisodePlanPath",
        str(context["episode_plan_path"]),
        "-OutputDir",
        str(MANIFESTS),
        "-ResultPath",
        str(output),
    ]
    if args.force or args.overwrite_page_plans:
        cmd.append("-OverwriteExisting")
    return run_command_stage(stage, cmd, output)


def stage_refine_plans(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("refine_plans")
    output = context["paths"]["page_refine_result"]
    input_path = context["paths"]["page_plan_result"]
    stage["inputs"] = {"page_plan_result": str(input_path)}
    stage["outputs"] = {"page_refine_result": str(output)}
    if not args.refine_page_plans:
        return finish(stage, "skipped_disabled", "Page plan refinement was not requested.")
    if not input_path.is_file():
        if args.dry_run:
            return finish(stage, "would_wait_for_input", "Dry run: refinement waits for page plan output.")
        return finish(stage, "failed", "Page plan result is required before refinement.")
    if output.is_file() and not args.force:
        return finish(stage, "skipped_existing", "Existing page refinement result was kept.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: refine command was not executed.")
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "refine_comic_episode_page_plans.ps1"),
        "-PagePlanCreateResultPath",
        str(input_path),
        "-ResultPath",
        str(output),
    ]
    if args.max_pages > 0:
        cmd += ["-MaxPages", str(args.max_pages)]
    return run_command_stage(stage, cmd, output)


def stage_workflows(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("workflows")
    output = context["paths"]["workflow_create_result"]
    input_path = context["paths"]["page_plan_result"]
    stage["inputs"] = {"page_plan_result": str(input_path)}
    stage["outputs"] = {"workflow_create_result": str(output)}
    if not input_path.is_file():
        if args.dry_run:
            return finish(stage, "would_wait_for_input", "Dry run: workflow generation waits for page plan output.")
        return finish(stage, "failed", "Page plan result is required before workflow generation.")
    if output.is_file() and not args.force and workflow_create_result_complete(output, input_path):
        return finish(stage, "skipped_existing", "Existing workflow create result is complete.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: workflow generation command was not executed.")
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "create_comic_episode_workflows_from_page_plans.ps1"),
        "-PagePlanCreateResultPath",
        str(input_path),
        "-EpisodePlanPath",
        str(context["episode_plan_path"]),
        "-WorkflowDir",
        str(WORKFLOWS),
        "-ResultPath",
        str(output),
        "-UseFallbackPrompts",
    ]
    if args.auto_image_size:
        cmd.append("-AutoImageSize")
    if args.max_pages > 0:
        cmd += ["-MaxPages", str(args.max_pages)]
    return run_command_stage(stage, cmd, output)


def stage_draft_review(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("draft_review")
    output = context["paths"]["draft_review_json"]
    stage["outputs"] = {"draft_review_json": str(output), "draft_review_md": str(context["paths"]["draft_review_md"])}
    required = [context["paths"]["page_plan_result"], context["paths"]["workflow_create_result"]]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        if args.dry_run:
            return finish(stage, "would_wait_for_input", "Dry run: draft review waits for upstream outputs.", missing_inputs=missing)
        return finish(stage, "failed", "Draft review inputs are missing.", missing_inputs=missing)
    if output.is_file() and not args.force:
        return finish(stage, "skipped_existing", "Existing draft review was kept.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: draft review command was not executed.")
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "build_comic_episode_draft_review.ps1"),
        "-EpisodePlanPath",
        str(context["episode_plan_path"]),
        "-PagePlanCreateResultPath",
        str(context["paths"]["page_plan_result"]),
        "-WorkflowCreateResultPath",
        str(context["paths"]["workflow_create_result"]),
        "-OutputJson",
        str(output),
        "-OutputMarkdown",
        str(context["paths"]["draft_review_md"]),
    ]
    return run_command_stage(stage, cmd, output)


def stage_draft_qa(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("draft_qa")
    output = context["paths"]["draft_qa_json"]
    review = context["paths"]["draft_review_json"]
    stage["inputs"] = {"draft_review": str(review)}
    stage["outputs"] = {"draft_qa_json": str(output), "draft_qa_md": str(context["paths"]["draft_qa_md"])}
    if not review.is_file():
        if args.dry_run:
            return finish(stage, "would_wait_for_input", "Dry run: draft QA waits for draft review output.")
        return finish(stage, "failed", "Draft review is required before QA.")
    if not output.is_file() or args.force:
        if args.dry_run:
            return finish(stage, "would_run", "Dry run: draft QA command was not executed.")
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPTS / "build_comic_episode_draft_qa.ps1"),
            "-DraftReviewPath",
            str(review),
            "-EpisodePlanPath",
            str(context["episode_plan_path"]),
            "-OutputJson",
            str(output),
            "-OutputMarkdown",
            str(context["paths"]["draft_qa_md"]),
        ]
        stage = run_command_stage(stage, cmd, output)
        if stage["status"] == "failed":
            return stage
    else:
        stage["status"] = "skipped_existing"
        stage["message"] = "Existing draft QA was kept."

    qa = read_json(output) if output.is_file() else {}
    summary = qa.get("summary", {})
    stage["qa_summary"] = summary
    blocked = int(summary.get("blocked", 0) or 0)
    warnings = int(summary.get("warnings", 0) or 0)
    if blocked > 0:
        return finish(stage, "blocked", "Draft QA has blocked panels.", blocks_image_generation=True)
    if warnings > 0 and not args.allow_draft_warnings:
        return finish(stage, "blocked", "Draft QA has warnings that need review.", blocks_image_generation=True)
    return finish(stage, "passed" if stage["status"] != "skipped_existing" else "skipped_existing", "Draft QA gate passed.")


def stage_comfy_health(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("comfy_health")
    if args.image_backend != "comfyui":
        return finish(
            stage,
            "skipped_not_required",
            "ComfyUI health check is not required for the direct API backend.",
            backend=args.image_backend,
        )
    should_run = args.check_comfy_health or (args.generate_images and not args.skip_image_generation)
    if not should_run:
        return finish(stage, "skipped_disabled", "ComfyUI health check is only required before image generation.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: ComfyUI health check was not executed.")
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "test_comic_pipeline_health.ps1"),
        "-ComfyUrl",
        args.comfy_url,
        "-ResultPath",
        str(context["paths"]["health"]),
    ]
    stage = run_command_stage(stage, cmd, context["paths"]["health"])
    if stage["status"] == "failed":
        return stage
    health = read_json(context["paths"]["health"]) if context["paths"]["health"].is_file() else {}
    stage["health_summary"] = {"reachable": bool(health.get("reachable")), "error": health.get("error")}
    return finish(stage, "passed" if health.get("reachable") else "failed", "ComfyUI is reachable." if health.get("reachable") else "ComfyUI is not reachable.")


def generate_panels_direct(args: argparse.Namespace, context: dict) -> dict:
    result_path = context["paths"]["recovery_result"]
    result = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "backend": "direct_api",
        "completed": False,
        "partial": False,
        "waiting": False,
        "jobs_discovered": 0,
        "jobs_selected": 0,
        "jobs_deferred": 0,
        "jobs_attempted": [],
        "pages_assembled": [],
        "error": "",
    }
    try:
        create_result_path = context["paths"]["workflow_create_result"]
        if not create_result_path.is_file():
            raise ValueError(f"Workflow create result is missing: {create_result_path}")
        create_result = read_json(create_result_path)
        jobs = []
        for run in create_result.get("runs", []):
            workflow_result_path = Path(str(run.get("workflow_result_path") or ""))
            if not workflow_result_path.is_file():
                continue
            workflow_result = read_json(workflow_result_path)
            page_id = str(run.get("page_id") or workflow_result.get("page_id") or "")
            for entry in workflow_result.get("created", []):
                workflow_path = Path(str(entry.get("workflow") or ""))
                output_path = Path(str(entry.get("expected_panel_path") or ""))
                if not workflow_path.is_file() or not str(entry.get("expected_panel_path") or ""):
                    continue
                if output_path.is_file():
                    continue
                jobs.append({
                    "page_id": page_id,
                    "panel_id": str(entry.get("panel_id") or ""),
                    "workflow_path": workflow_path,
                    "output_path": output_path,
                    "workflow_result_path": workflow_result_path,
                })
        result["jobs_discovered"] = len(jobs)
        if args.max_panels > 0:
            jobs = jobs[:args.max_panels]
        result["jobs_selected"] = len(jobs)
        result["jobs_deferred"] = max(0, result["jobs_discovered"] - len(jobs))

        prompt_suffix = ""
        generation_context_path = context.get("generation_context_path")
        if generation_context_path and Path(generation_context_path).is_file():
            generation_context = read_json(Path(generation_context_path))
            prompt_suffix = str(generation_context.get("prompt_block") or "")

        for job in jobs:
            attempt = {
                "page_id": job["page_id"],
                "panel_id": job["panel_id"],
                "workflow_path": str(job["workflow_path"]),
                "workflow_result_path": str(job["workflow_result_path"]),
                "expected_panel_path": str(job["output_path"]),
                "completed": False,
                "error": "",
            }
            try:
                attempt["result"] = generate_from_workflow(
                    job["workflow_path"],
                    job["output_path"],
                    env_path=os.getenv("COMIC_PIPELINE_IMAGE_ENV_PATH") or None,
                    prompt_suffix=prompt_suffix,
                )
                attempt["completed"] = True
            except Exception as exc:
                attempt["error"] = str(exc)
                error_lower = attempt["error"].lower()
                if "429" in error_lower or "rate limit" in error_lower:
                    attempt["waiting_reason"] = "rate_limit"
                elif any(token in error_lower for token in ("502", "503", "504", "unreachable", "temporarily unavailable")):
                    attempt["waiting_reason"] = "upstream_error"
            result["jobs_attempted"].append(attempt)

        failed = [item for item in result["jobs_attempted"] if not item["completed"]]
        completed = [item for item in result["jobs_attempted"] if item["completed"]]
        waiting = [item for item in failed if item.get("waiting_reason")]
        result["waiting"] = bool(waiting)
        result["partial"] = bool(completed and (failed or result["jobs_deferred"]))
        result["completed"] = not failed and not result["jobs_deferred"]
        if waiting:
            result["waiting_reason"] = waiting[0]["waiting_reason"]
        elif result["jobs_deferred"]:
            result["deferred_reason"] = "max_panels"
        if failed and not waiting:
            result["error"] = f"{len(failed)} panel(s) failed"
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def stage_generate_panels(args: argparse.Namespace, context: dict, pipeline_result: dict) -> dict:
    stage = base_stage("generate_panels")
    stage["outputs"] = {
        "recovery_result": str(context["paths"]["recovery_result"]),
        "generation_context": str(context["generation_context_path"] or ""),
    }
    if args.skip_image_generation or not args.generate_images:
        return finish(stage, "skipped_disabled", "Image generation was not requested.")
    gate_blocks = [
        item["name"]
        for item in pipeline_result.get("stages", [])
        if item.get("blocks_image_generation") and item.get("status") in {"blocked", "waiting", "failed"}
    ]
    if gate_blocks:
        return finish(stage, "blocked", "Image generation is blocked by earlier gates.", blocking_stages=gate_blocks, stop_pipeline=True)
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: image generation/recovery command was not executed.")
    if args.image_backend == "direct_api":
        recovery = generate_panels_direct(args, context)
        stage["outputs"]["backend"] = "direct_api"
        stage["recovery_summary"] = recovery_summary(recovery)
        if recovery.get("waiting"):
            return finish(
                stage,
                "waiting",
                "Direct image generation is waiting for the upstream image API.",
                waiting_reason=recovery.get("waiting_reason") or "upstream_image_api",
                waiting_detail=recovery,
                stop_pipeline=True,
            )
        if recovery.get("completed"):
            return finish(stage, "passed", "Direct image generation completed.")
        if recovery.get("partial"):
            return finish(stage, "partial", "Direct image generation completed partially.")
        return finish(stage, "failed", recovery.get("error") or "Direct image generation failed.")
    queue_state = comfy_queue_state(args.comfy_url)
    stage["outputs"]["queue_state_before_generation"] = queue_state
    if queue_state.get("running", 0) > 0 or queue_state.get("pending", 0) > 0:
        return finish(
            stage,
            "waiting",
            "ComfyUI queue is busy; resume generation after the queue is idle.",
            waiting_reason="queue_busy",
            waiting_detail=queue_state,
            stop_pipeline=True,
        )
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "run_comic_episode_recovery.ps1"),
        "-EpisodePlanPath",
        str(context["episode_plan_path"]),
        "-StatusPath",
        str(context["paths"]["status_json"]),
        "-StatusMarkdownPath",
        str(context["paths"]["status_md"]),
        "-ComfyUrl",
        args.comfy_url,
        "-ResultPath",
        str(context["paths"]["recovery_result"]),
        "-MaxPanels",
        str(args.max_panels),
        "-RetryCount",
        str(args.retry_count),
        "-CooldownSeconds",
        str(args.cooldown_seconds),
        "-PollSeconds",
        str(args.poll_seconds),
        "-MaxIdlePolls",
        str(args.max_idle_polls),
        "-MaxPromptPolls",
        str(args.max_prompt_polls),
    ]
    if context["generation_context_path"]:
        cmd += ["-GenerationContextPath", str(context["generation_context_path"])]
    stage["command"] = cmd
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    stage["exit_code"] = completed.returncode
    stage["stdout_tail"] = tail_lines(completed.stdout, limit=30)
    stage["stderr_tail"] = tail_lines(completed.stderr, limit=30)
    result_path = context["paths"]["recovery_result"]
    if not result_path.is_file():
        return finish(stage, "failed", f"Expected recovery result was not created: {result_path}")
    recovery = read_json(result_path)
    stage["recovery_summary"] = recovery_summary(recovery)
    if recovery_is_waiting(recovery):
        waiting_reason, waiting_detail = waiting_reason_from_recovery(recovery)
        return finish(
            stage,
            "waiting",
            "Panel recovery is waiting for ComfyUI or upstream image API limits.",
            waiting_reason=waiting_reason,
            waiting_detail=waiting_detail,
            stop_pipeline=True,
        )
    if completed.returncode == 0:
        return finish(stage, "passed", "Panel recovery batch completed.")
    return finish(stage, "failed", "Panel recovery failed. Inspect the recovery manifest and per-panel run manifests.")


def stage_assemble_pages(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("assemble_pages")
    if not args.assemble_pages and not args.generate_images:
        return finish(stage, "skipped_disabled", "Page assembly was not requested.")
    workflow_result = context["paths"]["workflow_create_result"]
    if not workflow_result.is_file():
        if args.dry_run:
            return finish(stage, "would_wait_for_input", "Dry run: page assembly waits for workflow outputs.")
        return finish(stage, "failed", "Workflow create result is required before page assembly.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: page assembly commands were not executed.")
    runs = []
    failed_runs = []
    waiting_runs = []
    create_result = read_json(workflow_result)
    for run in create_result.get("runs", []):
        plan_path = Path(run.get("plan_path", ""))
        workflow_path = Path(run.get("workflow_result_path", ""))
        manifest_path = assembly_manifest_path_for_plan(plan_path)
        if not plan_path.is_file() or not workflow_path.is_file():
            record = {
                "page_id": run.get("page_id"),
                "status": "waiting_missing_input",
                "plan_path": str(plan_path),
                "workflow_result_path": str(workflow_path),
                "assembly_manifest": str(manifest_path),
            }
            runs.append(record)
            waiting_runs.append(record)
            continue
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPTS / "build_comic_page_from_panels.ps1"),
            "-PlanPath",
            str(plan_path),
            "-WorkflowResultPath",
            str(workflow_path),
            "-ManifestPath",
            str(manifest_path),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assembly = read_json(manifest_path) if manifest_path.is_file() else {}
        missing_panels = [panel.get("panel_id", "") for panel in assembly.get("panels", []) if not panel.get("exists", False)]
        if assembly and assembly.get("ok") is True:
            run_status = "passed"
        elif assembly and missing_panels:
            run_status = "waiting_missing_panels"
        else:
            run_status = "failed"
        record = {
            "page_id": run.get("page_id"),
            "status": run_status,
            "exit_code": completed.returncode,
            "assembly_manifest": str(manifest_path),
            "assembly_ok": assembly.get("ok") if assembly else None,
            "lettering_items": count_lettering_items(assembly),
            "missing_panels": missing_panels,
            "stdout_line_count": len(completed.stdout.splitlines()),
            "stderr_tail": tail_lines(completed.stderr, limit=20),
        }
        runs.append(record)
        if run_status == "failed":
            failed_runs.append(record)
        elif run_status.startswith("waiting"):
            waiting_runs.append(record)
    stage["runs"] = runs
    if failed_runs:
        return finish(stage, "failed", "At least one page assembly failed.", failed_runs=len(failed_runs))
    if waiting_runs:
        return finish(
            stage,
            "partial",
            "Page assembly produced reviewable pages with placeholders; remaining panels are still missing.",
            partial=True,
            placeholder_runs=len(waiting_runs),
        )
    return finish(stage, "passed", "Page assembly completed.")


def stage_status_report(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("status_report")
    output = context["paths"]["status_json"]
    stage["outputs"] = {"status_json": str(output), "status_md": str(context["paths"]["status_md"])}
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: status report command was not executed.")
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS / "build_comic_status_report.ps1"),
        "-EpisodePlanPath",
        str(context["episode_plan_path"]),
        "-OutputJson",
        str(output),
        "-OutputMarkdown",
        str(context["paths"]["status_md"]),
    ]
    stage = run_command_stage(stage, cmd, output)
    if output.is_file():
        status = read_json(output)
        stage["status_summary"] = status.get("summary", {})
    return stage


def stage_lettering_qa(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("lettering_qa")
    status_path = context["paths"]["status_json"]
    output = context["paths"]["lettering_qa_json"]
    stage["inputs"] = {"status_json": str(status_path)}
    stage["outputs"] = {"lettering_qa_json": str(output), "lettering_qa_md": str(context["paths"]["lettering_qa_md"])}
    if not status_path.is_file():
        return finish(stage, "skipped_missing_input", "Status report is required before lettering QA.")
    status = read_json(status_path)
    has_assemblies = any(Path(page.get("assembly_path") or "").is_file() for page in status.get("pages", []))
    allow_missing_assemblies = episode_is_incomplete(status)
    stage["inputs"]["allow_missing_assemblies"] = allow_missing_assemblies
    if not args.run_lettering_qa and not args.generate_images and not has_assemblies:
        return finish(stage, "skipped_disabled", "No page assemblies are available for lettering QA.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: lettering QA command was not executed.")
    cmd = [
        "python",
        str(SCRIPTS / "build_comic_lettering_qa.py"),
        str(status_path),
        str(output),
        str(context["paths"]["lettering_qa_md"]),
    ]
    if allow_missing_assemblies:
        cmd.append("--allow-missing-assemblies")
    stage = run_command_stage(stage, cmd, output)
    if output.is_file():
        qa = read_json(output)
        stage["lettering_summary"] = qa.get("summary", {})
        if not qa.get("summary", {}).get("passed", False):
            return finish(stage, "blocked", "Lettering QA found issues.")
        if int(qa.get("summary", {}).get("skipped_pages", 0) or 0) > 0:
            return finish(stage, "waiting", "Lettering QA passed for assembled pages; missing page assemblies are waiting for upstream generation.")
    return stage


def stage_consistency_qa(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("consistency_qa")
    status_path = context["paths"]["status_json"]
    output = context["paths"]["consistency_qa_json"]
    stage["inputs"] = {
        "status_json": str(status_path),
        "episode_plan": str(context["episode_plan_path"]),
    }
    stage["outputs"] = {
        "consistency_qa_json": str(output),
        "consistency_qa_md": str(context["paths"]["consistency_qa_md"]),
    }
    if not status_path.is_file():
        return finish(stage, "skipped_missing_input", "Status report is required before consistency QA.")
    if not args.run_consistency_qa and not args.generate_images:
        return finish(stage, "skipped_disabled", "Consistency QA was not requested.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: consistency QA command was not executed.")
    cmd = [
        "python",
        str(SCRIPTS / "build_comic_consistency_qa.py"),
        str(status_path),
        str(output),
        str(context["paths"]["consistency_qa_md"]),
        "--episode-plan",
        str(context["episode_plan_path"]),
    ]
    stage = run_command_stage(stage, cmd, output)
    if output.is_file():
        qa = read_json(output)
        stage["consistency_summary"] = qa.get("summary", {})
        if not qa.get("summary", {}).get("passed", False):
            return finish(stage, "blocked", "Consistency QA found reference-anchor issues.")
    return stage


def stage_image_health_qa(args: argparse.Namespace, context: dict, _: dict) -> dict:
    stage = base_stage("image_health_qa")
    status_path = context["paths"]["status_json"]
    output = context["paths"]["image_health_qa_json"]
    stage["inputs"] = {"status_json": str(status_path)}
    stage["outputs"] = {
        "image_health_qa_json": str(output),
        "image_health_qa_md": str(context["paths"]["image_health_qa_md"]),
    }
    if not status_path.is_file():
        return finish(stage, "skipped_missing_input", "Status report is required before image health QA.")
    if not args.run_image_health_qa and not args.generate_images:
        return finish(stage, "skipped_disabled", "Image health QA was not requested.")
    if args.dry_run:
        return finish(stage, "would_run", "Dry run: image health QA command was not executed.")
    cmd = [
        "python",
        str(SCRIPTS / "build_comic_image_health_qa.py"),
        str(status_path),
        str(output),
        str(context["paths"]["image_health_qa_md"]),
    ]
    stage = run_command_stage(stage, cmd, output)
    if output.is_file():
        qa = read_json(output)
        stage["image_health_summary"] = qa.get("summary", {})
        if not qa.get("summary", {}).get("passed", False):
            return finish(stage, "blocked", "Image health QA found unreadable, blank, or malformed image files.")
    return stage


def run_command_stage(stage: dict, cmd: list[str], expected_output: Path | None = None) -> dict:
    stage["command"] = cmd
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    stage["exit_code"] = completed.returncode
    stage["stdout_tail"] = tail_lines(completed.stdout)
    stage["stderr_tail"] = tail_lines(completed.stderr)
    if completed.returncode != 0:
        return finish(stage, "failed", "Command exited with a non-zero status.")
    if expected_output and not expected_output.is_file():
        return finish(stage, "failed", f"Expected output was not created: {expected_output}")
    return finish(stage, "passed", "Command completed.")


def discover_page_plan_paths(context: dict) -> list[Path]:
    result_path = context["paths"]["page_plan_result"]
    paths = []
    if result_path.is_file():
        result = read_json(result_path)
        paths.extend(Path(item.get("plan_path", "")) for item in result.get("created", []) if item.get("plan_path"))
    episode = context["episode"] or read_json(context["episode_plan_path"])
    for page in episode.get("pages", []):
        if page.get("plan"):
            paths.append(Path(page["plan"]))
        elif page.get("page_id"):
            paths.append(MANIFESTS / f"{str(page['page_id']).lower()}_plan.json")
    return unique_paths(paths)


def reference_alias_state(context: dict) -> dict:
    episode = read_json(context["episode_plan_path"])
    page_plan_paths = discover_page_plan_paths(context)
    aliases = episode.get("asset_aliases", {}) or {}
    used_aliases = set()

    for page in episode.get("pages", []):
        for panel in page.get("panels", []) or []:
            alias = panel.get("reference_alias")
            if alias:
                used_aliases.add(alias)

    for plan_path in page_plan_paths:
        if not plan_path.is_file():
            continue
        plan = read_json(plan_path)
        for panel in plan.get("panels", []):
            alias = panel.get("reference_alias")
            if alias:
                used_aliases.add(alias)

    unknown_aliases = []
    missing_files = []
    for alias in sorted(used_aliases):
        path = aliases.get(alias)
        if not path:
            unknown_aliases.append(alias)
        elif not Path(path).is_file():
            missing_files.append({"alias": alias, "path": path})

    return {
        "used_reference_aliases": sorted(used_aliases),
        "unknown_aliases": unknown_aliases,
        "missing_reference_files": missing_files,
        "anchor_workflow_candidates": find_anchor_workflow_candidates(missing_files),
    }


def find_anchor_workflow_candidates(missing_files: list[dict]) -> dict:
    expected_by_path = {normalize_path(item["path"]): item["alias"] for item in missing_files}
    candidates = {}
    for workflow in WORKSPACE.glob("workflows/*.json"):
        try:
            data = read_json(workflow)
        except Exception:
            continue
        expected = expected_output_from_workflow(data)
        alias = expected_by_path.get(normalize_path(expected)) if expected else None
        if alias:
            candidates[alias] = {"workflow": str(workflow), "expected_path": expected}
    return candidates


def find_existing_anchor_jobs(comfy_url: str, missing_files: list[dict]) -> list[dict]:
    try:
        queue = get_json(f"{comfy_url.rstrip('/')}/queue")
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return []

    missing_by_path = {normalize_path(item["path"]): item["alias"] for item in missing_files}
    jobs = []
    for state_name in ["queue_running", "queue_pending"]:
        for item in queue.get(state_name, []):
            if len(item) < 3:
                continue
            prompt_id = item[1]
            prompt_graph = item[2]
            expected_paths = expected_outputs_from_prompt_graph(prompt_graph)
            for expected_path in expected_paths:
                alias = missing_by_path.get(normalize_path(expected_path))
                if not alias:
                    continue
                extra = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
                jobs.append(
                    {
                        "alias": alias,
                        "queue_state": state_name,
                        "prompt_id": prompt_id,
                        "expected_path": expected_path,
                        "client_id": extra.get("client_id", ""),
                        "create_time": extra.get("create_time"),
                    }
                )
    return jobs


def comfy_queue_state(comfy_url: str) -> dict:
    try:
        queue = get_json(f"{comfy_url.rstrip('/')}/queue")
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"reachable": False, "running": 0, "pending": 0, "error": str(exc), "jobs": []}
    jobs = []
    for state_name in ["queue_running", "queue_pending"]:
        for item in queue.get(state_name, []):
            if len(item) < 2:
                continue
            jobs.append(
                {
                    "queue_state": state_name,
                    "prompt_id": item[1],
                    "client_id": item[3].get("client_id", "") if len(item) > 3 and isinstance(item[3], dict) else "",
                    "create_time": item[3].get("create_time") if len(item) > 3 and isinstance(item[3], dict) else None,
                    "age_seconds": queue_item_age_seconds(item[3]) if len(item) > 3 and isinstance(item[3], dict) else None,
                    "outputs": expected_outputs_from_prompt_graph(item[2]) if len(item) > 2 and isinstance(item[2], dict) else [],
                }
            )
    return {
        "reachable": True,
        "running": len(queue.get("queue_running", [])),
        "pending": len(queue.get("queue_pending", [])),
        "jobs": jobs,
    }


def queue_item_age_seconds(extra: dict) -> int | None:
    create_time = extra.get("create_time") if isinstance(extra, dict) else None
    if not create_time:
        return None
    try:
        return max(0, int(time.time() - (float(create_time) / 1000.0)))
    except (TypeError, ValueError):
        return None


def expected_outputs_from_prompt_graph(prompt_graph: dict) -> list[str]:
    paths = []
    for node in prompt_graph.values():
        if not isinstance(node, dict) or node.get("class_type") != "SaveImage":
            continue
        prefix = node.get("inputs", {}).get("filename_prefix")
        if prefix:
            paths.append(str(COMFY_OUTPUT_ROOT / f"{prefix}_00001_.png"))
    return paths


def expected_output_from_workflow(workflow: dict) -> str:
    for node in workflow.get("prompt", {}).values():
        if node.get("class_type") != "SaveImage":
            continue
        prefix = node.get("inputs", {}).get("filename_prefix")
        if prefix:
            return str(COMFY_OUTPUT_ROOT / f"{prefix}_00001_.png")
    return ""


def get_json(url: str) -> dict:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_path(value: str) -> str:
    return str(Path(value)).lower()


def page_plan_result_complete(path: Path) -> bool:
    try:
        result = read_json(path)
        items = result.get("created", [])
        return bool(items) and all(item.get("plan_path") and Path(item["plan_path"]).is_file() for item in items)
    except Exception:
        return False


def workflow_create_result_complete(path: Path, page_plan_result: Path) -> bool:
    try:
        workflow_result = read_json(path)
        page_result = read_json(page_plan_result)
        expected_pages = len([item for item in page_result.get("created", []) if item.get("plan_path")])
        runs = workflow_result.get("runs", [])
        return len(runs) >= expected_pages and all(run.get("exit_code") == 0 and Path(run.get("workflow_result_path", "")).is_file() for run in runs)
    except Exception:
        return False


def episode_is_incomplete(status: dict) -> bool:
    summary = status.get("summary", {})
    if int(summary.get("incomplete_pages", 0) or 0) > 0:
        return True
    if int(summary.get("missing_panels", 0) or 0) > 0:
        return True
    return any(page.get("status") != "complete" for page in status.get("pages", []))


def assembly_manifest_path_for_plan(plan_path: Path) -> Path:
    if plan_path.is_file():
        try:
            plan = read_json(plan_path)
            page_id = plan.get("page_id")
            if page_id:
                return MANIFESTS / f"{str(page_id).lower()}_assembly.json"
        except Exception:
            pass
    return MANIFESTS / f"{plan_path.stem.replace('_plan', '')}_assembly.json"


def recovery_summary(recovery: dict) -> dict:
    attempts = recovery.get("jobs_attempted", []) or []
    assemblies = recovery.get("pages_assembled", []) or []
    return {
        "completed": bool(recovery.get("completed")),
        "waiting": bool(recovery.get("waiting")),
        "error": recovery.get("error"),
        "jobs_discovered": int(recovery.get("jobs_discovered", 0) or 0),
        "jobs_selected": int(recovery.get("jobs_selected", len(attempts)) or 0),
        "jobs_deferred": int(recovery.get("jobs_deferred", 0) or 0),
        "jobs_attempted": len(attempts),
        "jobs_completed": len([item for item in attempts if item.get("completed")]),
        "jobs_skipped": len([item for item in attempts if item.get("skipped")]),
        "pages_assembled": len(assemblies),
        "assembly_waiting": len([item for item in assemblies if item.get("status") == "waiting_missing_panels"]),
        "assembly_failed": len([item for item in assemblies if item.get("status") == "failed"]),
        "waiting_for_panels": int(recovery.get("waiting_for_panels", 0) or 0),
        "waiting_rate_limit": int(recovery.get("waiting_rate_limit", 0) or 0),
        "waiting_upstream_error": int(recovery.get("waiting_upstream_error", 0) or 0),
    }


def recovery_is_waiting(recovery: dict) -> bool:
    if bool(recovery.get("waiting")):
        return True
    if int(recovery.get("waiting_for_panels", 0) or 0) > 0:
        return True
    if int(recovery.get("waiting_rate_limit", 0) or 0) > 0:
        return True
    if int(recovery.get("waiting_upstream_error", 0) or 0) > 0:
        return True
    if recovery.get("error") and "did not become idle" in str(recovery.get("error")):
        return True
    for attempt in recovery.get("jobs_attempted", []) or []:
        error = str(attempt.get("error") or "")
        if "did not become idle" in error:
            return True
    return False


def waiting_reason_from_recovery(recovery: dict) -> tuple[str, dict]:
    if int(recovery.get("waiting_rate_limit", 0) or 0) > 0:
        return "rate_limit", waiting_detail_from_attempts(recovery, "rate_limit")
    if int(recovery.get("waiting_upstream_error", 0) or 0) > 0:
        return "upstream_error", waiting_detail_from_attempts(recovery, "upstream_error")
    if int(recovery.get("waiting_for_panels", 0) or 0) > 0:
        missing_panels = []
        for assembly in recovery.get("pages_assembled", []) or []:
            for panel_id in assembly.get("missing_panels", []) or []:
                missing_panels.append(panel_id)
        return "waiting_for_panels", {"missing_panels": missing_panels}
    if recovery.get("error") and "did not become idle" in str(recovery.get("error")):
        return "idle_timeout", {"error": recovery.get("error")}
    for attempt in recovery.get("jobs_attempted", []) or []:
        error = str(attempt.get("error") or "")
        if "did not become idle" in error:
            return "idle_timeout", {
                "panel_id": attempt.get("panel_id"),
                "page_id": attempt.get("page_id"),
                "error": attempt.get("error"),
            }
    if bool(recovery.get("waiting")):
        return "waiting", {}
    return "", {}


def waiting_detail_from_attempts(recovery: dict, reason: str) -> dict:
    attempts = []
    for attempt in recovery.get("jobs_attempted", []) or []:
        if attempt.get("waiting_reason") != reason:
            continue
        last_errors = []
        for run in attempt.get("run_summary", {}).get("runs", []) or []:
            if run.get("last_error"):
                last_errors.append(run.get("last_error"))
        attempts.append(
            {
                "page_id": attempt.get("page_id"),
                "panel_id": attempt.get("panel_id"),
                "error": attempt.get("error"),
                "last_errors": last_errors,
            }
        )
    return {"attempts": attempts}


def count_lettering_items(assembly: dict) -> int:
    return sum(len(panel.get("lettering", []) or []) for panel in assembly.get("panels", []))


def summarize_pipeline(result: dict) -> dict:
    stages = result.get("stages", [])
    return {
        "stages": len(stages),
        "passed": len([stage for stage in stages if stage["status"] == "passed"]),
        "skipped": len([stage for stage in stages if stage["status"].startswith("skipped")]),
        "would_run": len([stage for stage in stages if stage["status"] == "would_run"]),
        "waiting_for_upstream": len([stage for stage in stages if stage["status"] == "would_wait_for_input"]),
        "waiting": len([stage for stage in stages if stage["status"] == "waiting"]),
        "partial": len([stage for stage in stages if stage["status"] == "partial"]),
        "blocked": len([stage for stage in stages if stage["status"] == "blocked"]),
        "failed": len([stage for stage in stages if stage["status"] == "failed"]),
    }


def infer_episode_number(episode: dict, path: Path) -> int:
    text = episode.get("episode_id", "") + " " + path.stem
    match = re.search(r"EP(?:ISODE)?0*(\d+)|episode0*(\d+)", text, re.IGNORECASE)
    if not match:
        return 0
    return int(next(group for group in match.groups() if group))


def safe_stem(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()


def resolve_novel_path(value: str) -> Path:
    path = Path(value) if value else Path(DEFAULT_NOVEL)
    if path.is_file():
        return path
    fallback = Path(DEFAULT_NOVEL)
    return fallback if fallback.is_file() else path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def tail_lines(text: str, limit: int = 80) -> list[str]:
    lines = text.splitlines()
    return lines[-limit:]


def safe_print(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.buffer.write(text.encode(encoding, errors="replace"))
    sys.stdout.buffer.write(b"\n")


def unique_paths(paths: list[Path]) -> list[Path]:
    seen = set()
    unique = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


if __name__ == "__main__":
    raise SystemExit(main())
