import json
import os
import re
import subprocess
import time
from html import escape
from pathlib import Path
from urllib.parse import quote


def _read_env_file(path: Path) -> dict:
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _package_root() -> Path:
    node_dir = Path(__file__).resolve().parent
    pointer = node_dir / "comic_pipeline_root.txt"
    if pointer.is_file():
        pointed = Path(pointer.read_text(encoding="utf-8-sig", errors="replace").strip().strip('"'))
        if pointed.is_dir():
            return pointed
    candidate = node_dir.parent
    if (candidate / "config").is_dir() and (candidate / "scripts").is_dir():
        return candidate
    return node_dir


PACKAGE_ROOT = _package_root()
_CONFIG = _read_env_file(PACKAGE_ROOT / "config" / ".env")


def _config_value(name: str, default: str = "") -> str:
    return os.getenv(name) or _CONFIG.get(name) or default


DEFAULT_WORKSPACE = _config_value("COMIC_PIPELINE_WORKSPACE", str(PACKAGE_ROOT))
DEFAULT_COMFY_URL = _config_value("COMIC_PIPELINE_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
DEFAULT_NOVEL = _config_value("COMIC_PIPELINE_NOVEL_PATH", str(Path(DEFAULT_WORKSPACE) / "novel.txt"))
DEFAULT_COMFY_OUTPUT_ROOT = Path(_config_value("COMIC_PIPELINE_COMFY_OUTPUT_ROOT", r"G:\ComfyUI\output"))
DEFAULT_OUTPUT_ROOT = Path(
    _config_value("COMIC_PIPELINE_OUTPUT_ROOT", str(DEFAULT_COMFY_OUTPUT_ROOT / "ComicPipeline"))
)
DEFAULT_PAGES = int(_config_value("COMIC_PIPELINE_DEFAULT_PAGES", "8") or "8")
DEFAULT_ENCODING = _config_value("COMIC_PIPELINE_ENCODING", "gb18030")
WEB_DIRECTORY = None

try:
    import nodes

    _FRONTEND_WEB_DIR = Path(__file__).with_name("comic_episode_pipeline_web.disabled")
    if _FRONTEND_WEB_DIR.is_dir():
        nodes.EXTENSION_WEB_DIRS["comic_episode_pipeline_node"] = str(_FRONTEND_WEB_DIR)
except Exception:
    pass


class ComicEpisodePipeline:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "episode_number": ("INT", {"default": 3, "min": 1, "max": 999, "step": 1}),
                "mode": (
                    [
                        "health_qa",
                        "assemble_qa",
                        "dry_run",
                        "generate_one_panel_background",
                        "generate_safe_batch_background",
                    ],
                    {"default": "health_qa"},
                ),
            },
            "optional": {
                "workspace_path": ("STRING", {"default": DEFAULT_WORKSPACE}),
                "comfy_url": ("STRING", {"default": DEFAULT_COMFY_URL}),
                "max_panels": ("STRING", {"default": "1"}),
                "max_batches": ("STRING", {"default": "1"}),
                "allow_generation": ("BOOLEAN", {"default": False}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 30, "max": 21600, "step": 30}),
                "run_label": ("STRING", {"default": "comfy_blueprint"}),
                "result_path": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("result_json_path", "summary_json", "stdout_tail")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()

    def run(
        self,
        episode_number,
        mode,
        workspace_path=DEFAULT_WORKSPACE,
        comfy_url=DEFAULT_COMFY_URL,
        max_panels=1,
        max_batches=1,
        allow_generation=False,
        timeout_seconds=1800,
        run_label="comfy_blueprint",
        result_path="",
    ):
        workspace = _workspace_path(workspace_path)
        episode_number = int(episode_number)
        mode = str(mode or "health_qa")
        run_label = _safe_token(run_label or "comfy_blueprint")
        result = _result_path(workspace, episode_number, mode, run_label, result_path)

        if mode in {"generate_one_panel_background", "generate_safe_batch_background"}:
            if not _truthy(allow_generation):
                raise ValueError(
                    "Generation modes require allow_generation=true. "
                    "Use health_qa or assemble_qa for safe UI tests."
                )
            if mode == "generate_one_panel_background":
                max_panels = 1
                max_batches = 1
            summary, stdout_tail = _start_generation_background(
                workspace=workspace,
                episode_number=episode_number,
                comfy_url=comfy_url,
                max_panels=int(max_panels),
                max_batches=int(max_batches),
                run_label=run_label,
                result_path=result,
            )
            return (str(result), json.dumps(summary, ensure_ascii=False, indent=2), stdout_tail)

        command = _foreground_command(
            workspace=workspace,
            episode_number=episode_number,
            mode=mode,
            comfy_url=comfy_url,
            run_label=run_label,
            result_path=result,
        )
        completed = _run_command(command, workspace, int(timeout_seconds))
        stdout_tail = _tail_text(completed.stdout)
        stderr_tail = _tail_text(completed.stderr)
        summary = _summary_from_result(result)
        summary.update(
            {
                "mode": mode,
                "episode_number": episode_number,
                "result_path": str(result),
                "exit_code": completed.returncode,
            }
        )
        if stderr_tail:
            summary["stderr_tail"] = stderr_tail
        if completed.returncode != 0:
            raise RuntimeError(
                "Comic episode pipeline failed with exit code "
                f"{completed.returncode}.\nSTDOUT:\n{stdout_tail}\nSTDERR:\n{stderr_tail}"
            )
        return (str(result), json.dumps(summary, ensure_ascii=False, indent=2), stdout_tail)


class ComicNovelSource:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "workspace_path": ("STRING", {"default": DEFAULT_WORKSPACE}),
                "novel_path": ("STRING", {"default": DEFAULT_NOVEL}),
                "episode_number": ("INT", {"default": 3, "min": 1, "max": 999, "step": 1}),
            },
            "optional": {
                "pages": ("INT", {"default": DEFAULT_PAGES, "min": 1, "max": 64, "step": 1}),
                "excerpt_chars": ("INT", {"default": 3600, "min": 500, "max": 20000, "step": 100}),
                "encoding": ("STRING", {"default": DEFAULT_ENCODING}),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("source_json", "episode_number", "summary_json")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()

    def run(self, workspace_path, novel_path, episode_number, pages=DEFAULT_PAGES, excerpt_chars=3600, encoding=DEFAULT_ENCODING):
        workspace = _workspace_path(workspace_path)
        novel = Path(str(novel_path or "").strip().strip('"'))
        if not novel.is_file():
            raise ValueError(f"novel_path does not exist: {novel}")
        episode_number = int(episode_number)
        episode_plan = _episode_plan_path(workspace, episode_number)
        data = {
            "workspace_path": str(workspace),
            "novel_path": str(novel),
            "episode_number": episode_number,
            "episode_plan_path": str(episode_plan),
            "pages": int(pages),
            "excerpt_chars": int(excerpt_chars),
            "encoding": str(encoding or DEFAULT_ENCODING),
        }
        summary = dict(data)
        summary["episode_plan_exists"] = episode_plan.is_file()
        return (json.dumps(data, ensure_ascii=False), episode_number, json.dumps(summary, ensure_ascii=False, indent=2))


class ComicAIBreakdown:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_json": ("STRING", {"forceInput": True}),
                "action": (
                    [
                        "draft_from_novel",
                        "refresh_draft_review",
                        "rebuild_page_plans",
                        "rebuild_workflows",
                    ],
                    {"default": "draft_from_novel"},
                ),
            },
            "optional": {
                "force": ("BOOLEAN", {"default": False}),
                "overwrite_page_plans": ("BOOLEAN", {"default": False}),
                "refine_page_plans": ("BOOLEAN", {"default": True}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 30, "max": 21600, "step": 30}),
                "run_label": ("STRING", {"default": "ui_breakdown"}),
                "result_path": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("draft_result_json", "draft_qa_json", "review_markdown", "summary_json")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()

    def run(
        self,
        source_json,
        action,
        force=False,
        overwrite_page_plans=False,
        refine_page_plans=True,
        timeout_seconds=1800,
        run_label="ui_breakdown",
        result_path="",
    ):
        source = _json_input(source_json, "source_json")
        workspace = _workspace_path(source.get("workspace_path", DEFAULT_WORKSPACE))
        episode_number = int(source["episode_number"])
        result = _result_path(workspace, episode_number, str(action), _safe_token(run_label), result_path)
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_script(workspace, "run_comic_episode_pipeline.ps1")),
            "-EpisodeNumber",
            str(episode_number),
            "-NovelPath",
            str(source.get("novel_path", "")),
            "-Pages",
            str(source.get("pages", 8)),
            "-ExcerptChars",
            str(source.get("excerpt_chars", 3600)),
            "-Encoding",
            str(source.get("encoding", "gb18030")),
            "-SkipImageGeneration",
            "-AllowDraftWarnings",
            "-RunLabel",
            _safe_token(run_label),
            "-ResultPath",
            str(result),
        ]
        if force:
            command.append("-Force")
        if overwrite_page_plans:
            command.append("-OverwritePagePlans")
        if refine_page_plans:
            command.append("-RefinePagePlans")
        if action == "draft_from_novel":
            command += ["-CreateChapterBrief", "-ApplyChapterBrief", "-FromStage", "chapter_brief", "-UntilStage", "draft_qa"]
        elif action == "refresh_draft_review":
            command += ["-OnlyStage", "draft_review,draft_qa"]
        elif action == "rebuild_page_plans":
            command += ["-OnlyStage", "page_plans,refine_plans,draft_review,draft_qa"]
        elif action == "rebuild_workflows":
            command += ["-OnlyStage", "workflows,draft_review,draft_qa"]
        else:
            raise ValueError(f"Unsupported breakdown action: {action}")
        completed = _run_command(command, workspace, int(timeout_seconds))
        if completed.returncode != 0:
            raise RuntimeError(_command_error("Comic AI breakdown failed", completed))
        paths = _episode_paths(workspace, episode_number)
        summary = _summary_from_result(result)
        summary.update(
            {
                "action": action,
                "episode_number": episode_number,
                "pipeline_result": str(result),
                "draft_qa_json": str(paths["draft_qa_json"]),
                "review_markdown": str(paths["draft_review_md"]),
            }
        )
        return (
            str(result),
            str(paths["draft_qa_json"]),
            str(paths["draft_review_md"]),
            json.dumps(summary, ensure_ascii=False, indent=2),
        )


class ComicFlowSwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "stage_name": ("STRING", {"default": "人工审核通过"}),
                "note": ("STRING", {"multiline": True, "default": "审核确认后打开此开关。"}),
                "workspace_path": ("STRING", {"default": DEFAULT_WORKSPACE}),
                "output_json": ("STRING", {"default": ""}),
                "auto_run_on_open": ("BOOLEAN", {"default": True}),
                "confirm_before_auto_run": ("BOOLEAN", {"default": False}),
                "auto_run_delay_ms": ("INT", {"default": 500, "min": 0, "max": 10000, "step": 100}),
            },
        }

    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("enabled", "switch_json", "summary_json")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()

    def run(
        self,
        enabled,
        stage_name="人工审核通过",
        note="审核确认后打开此开关。",
        workspace_path=DEFAULT_WORKSPACE,
        output_json="",
        auto_run_on_open=True,
        confirm_before_auto_run=False,
        auto_run_delay_ms=500,
    ):
        workspace = _workspace_path(workspace_path)
        is_enabled = _truthy(enabled)
        stage = str(stage_name or "flow_switch")
        summary = {
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stage_name": stage,
            "enabled": is_enabled,
            "status": "open" if is_enabled else "waiting",
            "note": str(note or ""),
            "next_action": "continue downstream stage" if is_enabled else "open this switch after review",
            "auto_run_on_open": _truthy(auto_run_on_open),
            "confirm_before_auto_run": _truthy(confirm_before_auto_run),
            "auto_run_delay_ms": int(auto_run_delay_ms or 0),
        }
        raw_output = str(output_json or "").strip().strip('"')
        if raw_output:
            output = Path(raw_output)
            if not output.is_absolute():
                output = workspace / output
        else:
            output = workspace / "manifests" / f"comfy_flow_switch_{_safe_token(stage)}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return (is_enabled, json.dumps(summary, ensure_ascii=False, indent=2), json.dumps(summary, ensure_ascii=False, indent=2))


class ComicHumanApprovalGate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "draft_qa_json": ("STRING", {"forceInput": True}),
                "approve": ("BOOLEAN", {"forceInput": True}),
            },
            "optional": {
                "page_ids": ("STRING", {"default": ""}),
                "reviewer": ("STRING", {"default": "human_reviewer"}),
                "note": ("STRING", {"multiline": True, "default": "人工审核草稿通过后，在流程开关中打开审核通过。"}),
                "output_json": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("approved", "approval_json", "summary_json")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()

    def run(self, draft_qa_json, approve, page_ids="", reviewer="human_reviewer", note="", output_json=""):
        qa_path = Path(str(draft_qa_json or "").strip().strip('"'))
        if not qa_path.is_file():
            raise ValueError(f"draft_qa_json does not exist: {qa_path}")
        workspace = _infer_workspace_from_path(qa_path)
        qa = _read_json(qa_path)
        episode_number = _episode_number_from_id(qa.get("episode_id") or qa_path.name)
        output = Path(str(output_json or "").strip().strip('"')) if output_json else (
            workspace / "manifests" / f"ssj_comic_episode{episode_number:02d}_human_approval.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        if not _truthy(approve):
            approval = {
                "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "qa_json": str(qa_path),
                "episode_id": qa.get("episode_id"),
                "approved": False,
                "approval_status": "waiting_for_human_review",
                "reviewer": reviewer,
                "note": note,
                "next_action": "review draft markdown and open the approval switch",
            }
            output.write_text(json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8")
            return (False, str(output), json.dumps(approval, ensure_ascii=False, indent=2))

        selected_pages = str(page_ids or "").strip()
        if not selected_pages:
            selected_pages = ",".join(page.get("page_id", "") for page in qa.get("pages", []) if page.get("page_id"))
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_script(workspace, "approve_comic_episode_draft.ps1")),
            "-QaJson",
            str(qa_path),
            "-PageIds",
            selected_pages,
            "-OutputJson",
            str(output),
            "-Reviewer",
            str(reviewer or "human_reviewer"),
            "-Note",
            str(note or "人工审核草稿通过后，在流程开关中打开审核通过。"),
        ]
        completed = _run_command(command, workspace, 300)
        if completed.returncode != 0:
            raise RuntimeError(_command_error("Comic human approval failed", completed))
        approval = _read_json(output)
        approval["approved"] = approval.get("summary", {}).get("blocked", 1) == 0
        output.write_text(json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8")
        return (bool(approval["approved"]), str(output), json.dumps(approval, ensure_ascii=False, indent=2))


class ComicGenerateBatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "approved": ("BOOLEAN", {"forceInput": True}),
                "approval_json": ("STRING", {"forceInput": True}),
                "allow_generation": ("BOOLEAN", {"forceInput": True}),
                "episode_number": ("INT", {"forceInput": True}),
            },
            "optional": {
                "workspace_path": ("STRING", {"default": DEFAULT_WORKSPACE}),
                "comfy_url": ("STRING", {"default": DEFAULT_COMFY_URL}),
                "max_panels": ("STRING", {"default": "1"}),
                "max_batches": ("STRING", {"default": "1"}),
                "run_label": ("STRING", {"default": "ui_generate"}),
                "result_path": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("generation_result_json", "summary_json")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()

    def run(
        self,
        approved,
        approval_json,
        allow_generation,
        episode_number=3,
        workspace_path=DEFAULT_WORKSPACE,
        comfy_url=DEFAULT_COMFY_URL,
        max_panels=1,
        max_batches=1,
        run_label="ui_generate",
        result_path="",
    ):
        max_panels, max_batches, run_label, result_path = _repair_generate_batch_widgets(
            max_panels=max_panels,
            max_batches=max_batches,
            run_label=run_label,
            result_path=result_path,
        )
        workspace = _workspace_path(workspace_path)
        episode_number = _int_value(episode_number, "episode_number", minimum=1, maximum=999)
        result = _result_path(workspace, episode_number, "generate_batch", _safe_token(run_label), result_path)
        if not _truthy(approved):
            summary = _write_waiting_result(
                result,
                stage="generate_batch",
                episode_number=episode_number,
                waiting_reason="approval_switch_closed",
                next_action="review the draft, then open the approval switch",
            )
            return (str(result), json.dumps(summary, ensure_ascii=False, indent=2))
        if not _truthy(allow_generation):
            summary = _write_waiting_result(
                result,
                stage="generate_batch",
                episode_number=episode_number,
                waiting_reason="generation_switch_closed",
                next_action="open the generation switch after draft approval",
            )
            return (str(result), json.dumps(summary, ensure_ascii=False, indent=2))
        approval_path = Path(str(approval_json or "").strip().strip('"'))
        if not approval_path.is_file():
            raise ValueError(f"approval_json does not exist: {approval_path}")
        approval = _read_json(approval_path)
        if approval.get("approved") is not True and approval.get("summary", {}).get("blocked", 1) != 0:
            raise ValueError("Generation is blocked: approval_json does not prove approval.")
        episode_number = _int_value(
            episode_number or _episode_number_from_id(approval.get("episode_id") or "0"),
            "episode_number",
            minimum=1,
            maximum=999,
        )
        summary, _ = _start_generation_background(
            workspace=workspace,
            episode_number=episode_number,
            comfy_url=comfy_url,
            max_panels=_int_value(max_panels, "max_panels", minimum=1, maximum=32),
            max_batches=_int_value(max_batches, "max_batches", minimum=1, maximum=32),
            run_label=_safe_token(run_label),
            result_path=result,
        )
        return (str(result), json.dumps(summary, ensure_ascii=False, indent=2))


class ComicPageReviewQA:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "episode_number": ("INT", {"forceInput": True}),
                "review_action": (
                    ["assemble_and_qa", "qa_only", "status_only"],
                    {"default": "assemble_and_qa"},
                ),
                "review_enabled": ("BOOLEAN", {"forceInput": True}),
            },
            "optional": {
                "workspace_path": ("STRING", {"default": DEFAULT_WORKSPACE}),
                "comfy_url": ("STRING", {"default": DEFAULT_COMFY_URL}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 30, "max": 21600, "step": 30}),
                "run_label": ("STRING", {"default": "ui_page_review"}),
                "result_path": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("review_result_json", "status_json", "preview_html", "summary_json")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()

    def run(
        self,
        episode_number,
        review_action,
        workspace_path=DEFAULT_WORKSPACE,
        comfy_url=DEFAULT_COMFY_URL,
        timeout_seconds=1800,
        run_label="ui_page_review",
        result_path="",
        review_enabled=False,
    ):
        workspace = _workspace_path(workspace_path)
        episode_number = int(episode_number)
        result = _result_path(workspace, episode_number, review_action, _safe_token(run_label), result_path)
        paths = _episode_paths(workspace, episode_number)
        if not _truthy(review_enabled):
            summary = _write_waiting_result(
                result,
                stage="page_review_qa",
                episode_number=episode_number,
                waiting_reason="review_switch_closed",
                next_action="open the page review switch after generation finishes",
            )
            preview = _build_episode_preview(workspace, episode_number, review_result_path=result)
            summary.update({"preview_html": preview["html_path"], "preview_url": preview["url"]})
            result.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            return (
                str(result),
                str(paths["status_json"]),
                preview["url"],
                json.dumps(summary, ensure_ascii=False, indent=2),
            )
        only_stage = "status_report"
        extra = []
        if review_action == "assemble_and_qa":
            only_stage = "assemble_pages,status_report,lettering_qa,consistency_qa,image_health_qa"
            extra = ["-SkipImageGeneration", "-AssemblePages", "-RunLetteringQa", "-RunConsistencyQa", "-RunImageHealthQa"]
        elif review_action == "qa_only":
            only_stage = "status_report,lettering_qa,consistency_qa,image_health_qa"
            extra = ["-RunLetteringQa", "-RunConsistencyQa", "-RunImageHealthQa"]
        elif review_action == "status_only":
            only_stage = "status_report"
        else:
            raise ValueError(f"Unsupported review_action: {review_action}")
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_script(workspace, "run_comic_episode_pipeline.ps1")),
            "-EpisodeNumber",
            str(episode_number),
            "-ComfyUrl",
            str(comfy_url),
            "-OnlyStage",
            only_stage,
            "-RunLabel",
            _safe_token(run_label),
            "-ResultPath",
            str(result),
        ] + extra
        completed = _run_command(command, workspace, int(timeout_seconds))
        summary = _summary_from_result(result)
        summary.update({"review_action": review_action, "episode_number": episode_number})
        if completed.returncode != 0:
            summary.update(
                {
                    "completed": False,
                    "blocked": True,
                    "waiting": True,
                    "waiting_reason": "page_review_blocked",
                    "next_action": "review and fix the QA report, then rerun page review before entering next episode",
                    "exit_code": completed.returncode,
                    "stdout_tail": _tail_text(completed.stdout),
                    "stderr_tail": _tail_text(completed.stderr),
                }
            )
        preview = _build_episode_preview(workspace, episode_number, review_result_path=result)
        try:
            review_result = _read_json(result) if result.is_file() else {}
        except Exception:
            review_result = {}
        if isinstance(review_result, dict):
            review_result["preview_html"] = preview["html_path"]
            review_result["preview_url"] = preview["url"]
            result.write_text(json.dumps(review_result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.update({"preview_html": preview["html_path"], "preview_url": preview["url"]})
        return (
            str(result),
            str(paths["status_json"]),
            preview["url"],
            json.dumps(summary, ensure_ascii=False, indent=2),
        )


class ComicNextEpisode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "current_episode_number": ("INT", {"forceInput": True}),
                "review_result_json": ("STRING", {"forceInput": True}),
                "create_skeleton_if_missing": ("BOOLEAN", {"default": True}),
                "continue_enabled": ("BOOLEAN", {"forceInput": True}),
            },
            "optional": {
                "workspace_path": ("STRING", {"default": DEFAULT_WORKSPACE}),
                "pages": ("INT", {"default": DEFAULT_PAGES, "min": 1, "max": 64, "step": 1}),
                "result_path": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "STRING")
    RETURN_NAMES = ("next_episode_number", "next_source_json", "summary_json")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return time.time()

    def run(
        self,
        current_episode_number,
        review_result_json,
        create_skeleton_if_missing=True,
        workspace_path=DEFAULT_WORKSPACE,
        pages=DEFAULT_PAGES,
        result_path="",
        continue_enabled=False,
    ):
        workspace = _workspace_path(workspace_path)
        next_episode = int(current_episode_number) + 1
        next_plan = _episode_plan_path(workspace, next_episode)
        result = _result_path(workspace, next_episode, "next_episode", "ui_next_episode", result_path)
        review_gate = _review_gate_status(review_result_json)
        created = False
        if not _truthy(continue_enabled):
            source = {
                "workspace_path": str(workspace),
                "novel_path": DEFAULT_NOVEL,
                "episode_number": next_episode,
                "episode_plan_path": str(next_plan),
                "pages": int(pages),
                "excerpt_chars": 3600,
                "encoding": DEFAULT_ENCODING,
            }
            summary = _write_waiting_result(
                result,
                stage="next_episode",
                episode_number=next_episode,
                waiting_reason="next_episode_switch_closed",
                next_action="open the next episode switch after page QA passes",
                extra={
                    "next_episode_plan": str(next_plan),
                    "next_episode_plan_exists": next_plan.is_file(),
                    "review_gate": review_gate,
                },
            )
            return (next_episode, json.dumps(source, ensure_ascii=False), json.dumps(summary, ensure_ascii=False, indent=2))
        if not review_gate["passed"]:
            source = {
                "workspace_path": str(workspace),
                "novel_path": DEFAULT_NOVEL,
                "episode_number": next_episode,
                "episode_plan_path": str(next_plan),
                "pages": int(pages),
                "excerpt_chars": 3600,
                "encoding": DEFAULT_ENCODING,
            }
            summary = _write_waiting_result(
                result,
                stage="next_episode",
                episode_number=next_episode,
                waiting_reason=review_gate["waiting_reason"],
                next_action=review_gate["next_action"],
                extra={
                    "blocked": True,
                    "next_episode_plan": str(next_plan),
                    "next_episode_plan_exists": next_plan.is_file(),
                    "review_gate": review_gate,
                },
            )
            return (next_episode, json.dumps(source, ensure_ascii=False), json.dumps(summary, ensure_ascii=False, indent=2))
        if _truthy(create_skeleton_if_missing) and not next_plan.is_file():
            command = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(_script(workspace, "create_comic_episode_skeletons_from_series.ps1")),
                "-StartEpisodeNumber",
                str(next_episode),
                "-EpisodeCount",
                "1",
                "-PagesPerEpisode",
                str(int(pages)),
                "-ResultPath",
                str(result),
            ]
            completed = _run_command(command, workspace, 300)
            if completed.returncode != 0:
                raise RuntimeError(_command_error("Next episode skeleton creation failed", completed))
            created = True
        source = {
            "workspace_path": str(workspace),
            "novel_path": DEFAULT_NOVEL,
            "episode_number": next_episode,
            "episode_plan_path": str(next_plan),
            "pages": int(pages),
            "excerpt_chars": 3600,
            "encoding": DEFAULT_ENCODING,
        }
        summary = {
            "next_episode_number": next_episode,
            "next_episode_plan": str(next_plan),
            "next_episode_plan_exists": next_plan.is_file(),
            "created_skeleton": created,
            "result_path": str(result),
        }
        return (next_episode, json.dumps(source, ensure_ascii=False), json.dumps(summary, ensure_ascii=False, indent=2))


class ComicPipelineConfig:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "workspace_path": ("STRING", {"default": DEFAULT_WORKSPACE}),
                "api_key_env_path": (
                    "STRING",
                    {"default": _config_value("COMIC_PIPELINE_IMAGE_ENV_PATH", str(PACKAGE_ROOT / "config" / "image.env"))},
                ),
                "show_key_presence_only": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("config_json", "summary")
    FUNCTION = "run"
    CATEGORY = "comic/pipeline"
    OUTPUT_NODE = True

    def run(self, workspace_path=DEFAULT_WORKSPACE, api_key_env_path="", show_key_presence_only=True):
        workspace = _workspace_path(workspace_path)
        image_env = Path(str(api_key_env_path or "").strip().strip('"'))
        image_values = _read_env_file(image_env)
        key_present = any(
            bool(str(image_values.get(name, "")).strip())
            for name in ("OPENAI_API_KEY", "API_KEY", "API_KEYS")
        )
        config = {
            "package_root": str(PACKAGE_ROOT),
            "workspace_path": str(workspace),
            "config_path": str(PACKAGE_ROOT / "config" / ".env"),
            "image_env_path": str(image_env),
            "image_api_key_configured": key_present,
            "image_base_url_configured": bool(str(image_values.get("OPENAI_BASE_URL") or image_values.get("BASE_URL") or "").strip()),
            "comfy_url": DEFAULT_COMFY_URL,
            "comfy_output_root": str(DEFAULT_COMFY_OUTPUT_ROOT),
            "output_root": str(DEFAULT_OUTPUT_ROOT),
            "novel_path": DEFAULT_NOVEL,
            "default_pages": DEFAULT_PAGES,
            "encoding": DEFAULT_ENCODING,
            "secrets_policy": "workflow stores api_key_env_path only; plaintext keys stay in config/image.env",
        }
        if not _truthy(show_key_presence_only):
            config["image_env_keys"] = sorted(image_values.keys())
        return (json.dumps(config, ensure_ascii=False, indent=2), f"配置已读取；图片 API Key 已配置: {key_present}")


NODE_CLASS_MAPPINGS = {
    "ComicPipelineConfig": ComicPipelineConfig,
    "ComicEpisodePipeline": ComicEpisodePipeline,
    "ComicNovelSource": ComicNovelSource,
    "ComicAIBreakdown": ComicAIBreakdown,
    "ComicFlowSwitch": ComicFlowSwitch,
    "ComicHumanApprovalGate": ComicHumanApprovalGate,
    "ComicGenerateBatch": ComicGenerateBatch,
    "ComicPageReviewQA": ComicPageReviewQA,
    "ComicNextEpisode": ComicNextEpisode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ComicPipelineConfig": "漫画流水线配置",
    "ComicEpisodePipeline": "Comic Episode Pipeline",
    "ComicNovelSource": "Comic Novel Source",
    "ComicAIBreakdown": "Comic AI Breakdown",
    "ComicFlowSwitch": "流程开关",
    "ComicHumanApprovalGate": "Comic Human Approval Gate",
    "ComicGenerateBatch": "Comic Generate Batch",
    "ComicPageReviewQA": "Comic Page Review QA",
    "ComicNextEpisode": "Comic Next Episode",
}


def _workspace_path(value: str) -> Path:
    path = Path(str(value or DEFAULT_WORKSPACE).strip().strip('"'))
    if not path.is_dir():
        raise ValueError(f"workspace_path does not exist: {path}")
    return path


def _script(workspace: Path, name: str) -> Path:
    path = workspace / "scripts" / name
    if not path.is_file():
        raise ValueError(f"Required script does not exist: {path}")
    return path


def _episode_plan_path(workspace: Path, episode_number: int) -> Path:
    return workspace / "manifests" / f"ssj_comic_episode{int(episode_number):02d}_pages.json"


def _episode_paths(workspace: Path, episode_number: int) -> dict:
    episode_number = int(episode_number)
    long_stem = f"ssj_comic_episode{episode_number:02d}"
    episode_id = f"SSJ_COMIC_EP{episode_number:02d}"
    review_root = DEFAULT_OUTPUT_ROOT / "review_packages"
    manifests = workspace / "manifests"
    return {
        "chapter_brief_json": manifests / f"ssj_comic_ep{episode_number:02d}_chapter_brief.json",
        "full_chapter_brief_json": manifests / f"ssj_comic_ep{episode_number:02d}_full_chapter_brief.json",
        "episode_plan": manifests / f"{long_stem}_pages.json",
        "draft_review_json": manifests / f"{long_stem}_draft_review.json",
        "draft_review_md": review_root / f"{episode_id}_draft_review.md",
        "draft_qa_json": manifests / f"{long_stem}_draft_qa.json",
        "draft_qa_md": review_root / f"{episode_id}_draft_qa.md",
        "human_approval_json": manifests / f"{long_stem}_human_approval.json",
        "status_json": manifests / f"{long_stem}_status.json",
        "status_md": review_root / f"{episode_id}_status.md",
        "lettering_qa_json": manifests / f"{long_stem}_lettering_qa.json",
        "consistency_qa_json": manifests / f"{long_stem}_consistency_qa.json",
        "image_health_qa_json": manifests / f"{long_stem}_image_health_qa.json",
    }


def _result_path(workspace: Path, episode_number: int, mode: str, run_label: str, result_path: str) -> Path:
    raw = str(result_path or "").strip().strip('"')
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = workspace / path
    else:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = (
            workspace
            / "manifests"
            / f"comfy_node_ep{episode_number:02d}_{run_label}_{_safe_token(mode)}_{timestamp}.json"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _json_input(value: str, name: str) -> dict:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        path = Path(text.strip('"'))
        if path.is_file():
            return _read_json(path)
        raise


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_waiting_result(
    path: Path,
    stage: str,
    episode_number: int,
    waiting_reason: str,
    next_action: str,
    extra: dict | None = None,
) -> dict:
    summary = {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "completed": True,
        "blocked": False,
        "waiting": True,
        "stage": stage,
        "episode_number": int(episode_number),
        "waiting_reason": waiting_reason,
        "next_action": next_action,
        "result_path": str(path),
    }
    if extra:
        summary.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _review_gate_status(review_result_json: str) -> dict:
    raw = str(review_result_json or "").strip().strip('"')
    if not raw:
        return {
            "passed": False,
            "waiting_reason": "page_review_missing",
            "next_action": "run page review before entering next episode",
            "review_result_json": raw,
        }
    path = Path(raw)
    if not path.is_file():
        return {
            "passed": False,
            "waiting_reason": "page_review_missing",
            "next_action": "run page review before entering next episode",
            "review_result_json": str(path),
        }
    review = _read_json(path)
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    blocked_count = int(summary.get("blocked") or 0)
    failed_count = int(summary.get("failed") or 0)
    passed = (
        review.get("completed") is True
        and review.get("blocked") is not True
        and review.get("waiting") is not True
        and blocked_count == 0
        and failed_count == 0
    )
    if passed:
        return {
            "passed": True,
            "waiting_reason": "",
            "next_action": "page review passed; next episode may be created",
            "review_result_json": str(path),
        }
    return {
        "passed": False,
        "waiting_reason": "page_review_not_passed",
        "next_action": "review and fix page QA issues, then rerun page review before entering next episode",
        "review_result_json": str(path),
        "completed": review.get("completed"),
        "blocked": review.get("blocked"),
        "waiting": review.get("waiting"),
        "summary": summary,
    }


def _build_episode_preview(workspace: Path, episode_number: int, review_result_path: Path | None = None) -> dict:
    paths = _episode_paths(workspace, episode_number)
    status = _read_json_if_exists(paths["status_json"])
    lettering = _read_json_if_exists(paths["lettering_qa_json"])
    image_health = _read_json_if_exists(paths["image_health_qa_json"])
    consistency = _read_json_if_exists(paths["consistency_qa_json"])
    chapter_brief = _read_json_if_exists(paths["chapter_brief_json"])
    full_chapter_brief = _read_json_if_exists(paths["full_chapter_brief_json"])
    episode_plan = _read_json_if_exists(paths["episode_plan"])
    draft_review = _read_json_if_exists(paths["draft_review_json"])
    draft_qa = _read_json_if_exists(paths["draft_qa_json"])
    human_approval = _read_first_json(
        [
            paths["human_approval_json"],
            workspace / "manifests" / "comfy_modular_human_approval.json",
        ]
    )
    generation_result = _read_json_if_exists(workspace / "manifests" / "comfy_modular_generation.json")
    next_result = _read_json_if_exists(workspace / "manifests" / "comfy_modular_next_episode.json")

    episode_id = (
        status.get("episode_id")
        or draft_review.get("episode_id")
        or draft_qa.get("episode_id")
        or episode_plan.get("episode_id")
        or chapter_brief.get("episode_id")
        or full_chapter_brief.get("episode_id")
        or lettering.get("episode_id")
        or image_health.get("episode_id")
        or consistency.get("episode_id")
        or f"SSJ_COMIC_EP{int(episode_number):02d}"
    )
    episode_title = (
        status.get("episode_title")
        or draft_review.get("episode_title")
        or episode_plan.get("episode_title")
        or chapter_brief.get("chapter_title")
        or full_chapter_brief.get("chapter_title")
        or lettering.get("episode_title")
        or image_health.get("episode_title")
        or consistency.get("episode_title")
        or f"Episode {int(episode_number):02d}"
    )

    preview_dir = _preview_static_dir()
    preview_dir.mkdir(parents=True, exist_ok=True)
    html_path = preview_dir / f"episode{int(episode_number):02d}.html"
    latest_path = preview_dir / "latest.html"

    status_pages = status.get("pages") if isinstance(status.get("pages"), list) else []
    lettering_pages = _index_by_page_id(lettering.get("pages"))
    image_pages = _index_by_page_id(image_health.get("pages"))
    consistency_pages = _index_by_page_id(consistency.get("pages"))
    status_summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    lettering_summary = lettering.get("summary") if isinstance(lettering.get("summary"), dict) else {}
    image_summary = image_health.get("summary") if isinstance(image_health.get("summary"), dict) else {}
    consistency_summary = consistency.get("summary") if isinstance(consistency.get("summary"), dict) else {}
    control_context = _preview_control_context(workspace, episode_number, status_summary)

    contact_sheet = consistency.get("contact_sheet") if isinstance(consistency.get("contact_sheet"), str) else ""
    review_result = _read_json_if_exists(review_result_path) if review_result_path else {}
    review_result_summary = review_result.get("summary") if isinstance(review_result.get("summary"), dict) else {}
    passed = (
        bool(lettering_summary.get("passed", False))
        and bool(image_summary.get("passed", False))
        and bool(consistency_summary.get("passed", False))
        and not bool(review_result.get("waiting", False))
    )
    if review_result_summary:
        passed = passed and int(review_result_summary.get("blocked") or 0) == 0 and int(review_result_summary.get("failed") or 0) == 0

    body = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<link rel="icon" href="data:,">',
        f"<title>{escape(str(episode_title))} 预览</title>",
        "<style>",
        _preview_css(),
        "</style>",
        "</head>",
        "<body>",
        '<main class="ops-shell">',
        '<header class="topbar">',
        '<div class="title-block">',
        f'<p class="eyebrow">{escape(str(episode_id))}</p>',
        f"<h1>{escape(str(episode_title))}</h1>",
        f'<p class="muted">更新时间：{escape(str(status.get("updated") or draft_review.get("updated") or time.strftime("%Y-%m-%dT%H:%M:%S")))}</p>',
        "</div>",
        '<div class="top-actions">',
        f'<span class="overall {"pass" if passed else "block"}">{"页面审核通过" if passed else "页面审核未通过"}</span>',
        '<a class="open-comfy" href="/" target="_blank" rel="noreferrer">打开 ComfyUI</a>',
        "</div>",
        "</header>",
        '<div class="ops-layout">',
        _stage_rail_html(
            episode_number=episode_number,
            draft_qa=draft_qa,
            human_approval=human_approval,
            generation_result=generation_result,
            status_summary=status_summary,
            review_passed=passed,
            next_result=next_result,
        ),
        '<section class="workspace">',
        _control_panel_html(),
        _status_strip_html(status_summary, lettering_summary, image_summary, consistency_summary),
        '<section class="content-grid">',
        _review_workspace_html(
            chapter_brief=chapter_brief,
            full_chapter_brief=full_chapter_brief,
            episode_plan=episode_plan,
            draft_review=draft_review,
            draft_qa=draft_qa,
            human_approval=human_approval,
            draft_review_md=paths["draft_review_md"],
            draft_qa_md=paths["draft_qa_md"],
        ),
        '<aside class="review-pane" aria-label="漫画结果预览">',
        '<section class="pane pane-tight">',
        "<h2>结果预览</h2>",
        f'<p class="muted">页面图 {escape(str(status_summary.get("complete_pages", len(status_pages))))} / {escape(str(status_summary.get("total_pages", len(status_pages))))}，分镜图 {escape(str(status_summary.get("generated_panels", 0)))} / {escape(str(status_summary.get("total_panels", 0)))}</p>',
        "</section>",
        _review_checklist_html(lettering_summary, image_summary, consistency_summary, passed),
    ]

    if contact_sheet:
        body.extend(
            [
                '<section class="pane pane-tight">',
                "<h2>一致性总览</h2>",
                f'<a class="contact" href="{_image_url(contact_sheet)}" target="_blank" rel="noreferrer">',
                f'<img src="{_image_url(contact_sheet)}" alt="一致性审核联系表">',
                "</a>",
                "</section>",
            ]
        )

    body.append(_preview_navigation_html(status_pages, lettering_pages, image_pages, consistency_pages))
    body.extend(["</aside>", "</section>", "</section>", "</div>"])
    context_json = json.dumps(control_context, ensure_ascii=False).replace("</", "<\\/")
    body.extend(
        [
            "</main>",
            "<script>",
            f"window.COMIC_PIPELINE_CONTEXT = {context_json};",
            _control_script(),
            "</script>",
            "</body>",
            "</html>",
        ]
    )

    html = "\n".join(body)
    html_path.write_text(html, encoding="utf-8")
    latest_path.write_text(html, encoding="utf-8")
    return {
        "html_path": str(html_path),
        "latest_html_path": str(latest_path),
        "url": _preview_url(html_path),
        "latest_url": _preview_url(latest_path),
    }


def _preview_navigation_html(status_pages: list, lettering_pages: dict, image_pages: dict, consistency_pages: dict) -> str:
    rows = ['<section class="pane pane-tight preview-nav">', "<h2>页面导航</h2>", '<div class="preview-list">']
    for page in status_pages:
        page_id = str(page.get("page_id") or "")
        image_page = image_pages.get(page_id, {})
        lettering_page = lettering_pages.get(page_id, {})
        consistency_page = consistency_pages.get(page_id, {})
        page_issues = _list_items(page.get("missing_panels")) + _list_items(image_page.get("issues")) + _list_items(
            lettering_page.get("issues")
        )
        panel_issues = _panel_issue_count(consistency_page)
        page_status = "pass" if not page_issues and panel_issues == 0 and page.get("status") == "complete" else "block"
        page_image = str(page.get("page_image") or image_page.get("page_image", {}).get("path") or "")
        rows.extend(
            [
                f'<a class="preview-page-link {page_status}" href="{_image_url(page_image)}" target="_blank" rel="noreferrer">',
                f'<img src="{_image_url(page_image)}" alt="{escape(page_id)}">',
                "<span>",
                f"<strong>{escape(page_id.split('_')[-1])}</strong>",
                f"<small>{escape(str(page.get('title') or page_id))}</small>",
                "</span>",
                f'<b class="badge {page_status}">{"OK" if page_status == "pass" else "处理"}</b>',
                "</a>",
            ]
        )
        panels = page.get("panels") if isinstance(page.get("panels"), list) else []
        consistency_panels = _index_by_panel_id(consistency_page.get("panels"))
        rows.append('<div class="mini-panel-grid">')
        for panel in panels:
            panel_id = str(panel.get("panel_id") or "")
            consistency_panel = consistency_panels.get(panel_id, {})
            panel_image = str(panel.get("used_panel_path") or panel.get("expected_panel_path") or consistency_panel.get("panel_image") or "")
            issues = _list_items(consistency_panel.get("issues"))
            warnings = _list_items(consistency_panel.get("warnings"))
            panel_status = "block" if issues else ("warn" if warnings else "pass")
            rows.extend(
                [
                    f'<a class="mini-panel {panel_status}" href="{_image_url(panel_image)}" target="_blank" rel="noreferrer">',
                    f'<img src="{_image_url(panel_image)}" alt="{escape(panel_id)}">',
                    "</a>",
                ]
            )
        rows.append("</div>")
    rows.extend(["</div>", "</section>"])
    return "\n".join(rows)


def _output_preview_dir() -> Path:
    return DEFAULT_OUTPUT_ROOT


def _read_json_if_exists(path: Path | None) -> dict:
    if path and Path(path).is_file():
        return _read_json(Path(path))
    return {}


def _read_first_json(paths: list[Path]) -> dict:
    for path in paths:
        data = _read_json_if_exists(path)
        if data:
            return data
    return {}


def _read_text_excerpt(path: Path, max_chars: int = 6000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n\n..."
    return text


def _stage_rail_html(
    episode_number: int,
    draft_qa: dict,
    human_approval: dict,
    generation_result: dict,
    status_summary: dict,
    review_passed: bool,
    next_result: dict,
) -> str:
    approved_panels = _summary_value(draft_qa, "approved_to_submit", 0)
    total_panels = _summary_value(draft_qa, "panels", status_summary.get("total_panels", 0))
    generated_panels = status_summary.get("generated_panels", 0)
    page_total = status_summary.get("total_pages", 0)
    complete_pages = status_summary.get("complete_pages", 0)
    steps = [
        ("小说选择", "ready", f"第 {int(episode_number):02d} 章"),
        ("AI拆解", "pass" if draft_qa else "warn", f"{approved_panels}/{total_panels} 分镜可提交" if draft_qa else "等待运行"),
        ("草稿审核", "pass" if human_approval.get("approved") is True else "warn", "已通过" if human_approval.get("approved") is True else "待人工确认"),
        ("生成漫画", "pass" if int(generated_panels or 0) > 0 else ("warn" if generation_result else "idle"), f"{generated_panels}/{status_summary.get('total_panels', 0)} 分镜"),
        ("页面审核", "pass" if review_passed else ("warn" if complete_pages else "idle"), f"{complete_pages}/{page_total} 页面"),
        ("下一章", "pass" if next_result.get("next_episode_number") else "idle", f"EP{int(next_result.get('next_episode_number') or int(episode_number) + 1):02d}"),
    ]
    rows = ['<aside class="stage-rail" aria-label="漫画流水线阶段">', "<h2>流程蓝图</h2>"]
    for index, (label, state, detail) in enumerate(steps, start=1):
        rows.extend(
            [
                f'<div class="stage-step {escape(state)}">',
                f'<span class="stage-index">{index}</span>',
                "<span>",
                f"<strong>{escape(label)}</strong>",
                f"<small>{escape(str(detail))}</small>",
                "</span>",
                "</div>",
            ]
        )
    rows.append("</aside>")
    return "\n".join(rows)


def _summary_value(data: dict, key: str, fallback=0):
    summary = data.get("summary") if isinstance(data, dict) and isinstance(data.get("summary"), dict) else {}
    return summary.get(key, fallback)


def _first_value(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _review_checklist_html(lettering_summary: dict, image_summary: dict, consistency_summary: dict, passed: bool) -> str:
    rows = [
        ("文字 QA", bool(lettering_summary.get("passed")), f"问题 {lettering_summary.get('issues', 0)}"),
        ("图片健康", bool(image_summary.get("passed")), f"问题 {image_summary.get('issues', 0)}"),
        ("一致性", bool(consistency_summary.get("passed")), f"阻塞 {consistency_summary.get('blocked', 0)}"),
        ("页面审核", bool(passed), "可进入下一章" if passed else "继续处理"),
    ]
    body = []
    for label, ok, detail in rows:
        body.append(
            "\n".join(
                [
                    f'<div class="check-row {"pass" if ok else "warn"}">',
                    f'<span class="check-mark">{"OK" if ok else "!"}</span>',
                    "<span>",
                    f"<strong>{escape(label)}</strong>",
                    f"<small>{escape(str(detail))}</small>",
                    "</span>",
                    "</div>",
                ]
            )
        )
    return "\n".join(
        [
            '<section class="pane pane-tight checklist">',
            "<h2>审核清单</h2>",
            "\n".join(body),
            "</section>",
        ]
    )


def _status_strip_html(status_summary: dict, lettering_summary: dict, image_summary: dict, consistency_summary: dict) -> str:
    items = [
        ("页面", status_summary.get("complete_pages", status_summary.get("total_pages", 0)), f"/ {status_summary.get('total_pages', 0)}"),
        ("分镜", status_summary.get("generated_panels", 0), f"/ {status_summary.get('total_panels', 0)}"),
        ("文字", "通过" if lettering_summary.get("passed") else "未过", f"问题 {lettering_summary.get('issues', 0)}"),
        ("图片", "通过" if image_summary.get("passed") else "未过", f"问题 {image_summary.get('issues', 0)}"),
        ("一致性", "通过" if consistency_summary.get("passed") else "阻塞", f"{consistency_summary.get('blocked', 0)} 阻塞"),
    ]
    cells = []
    for label, value, detail in items:
        cells.append(
            "\n".join(
                [
                    '<div class="status-cell">',
                    f"<span>{escape(str(label))}</span>",
                    f"<strong>{escape(str(value))}</strong>",
                    f"<small>{escape(str(detail))}</small>",
                    "</div>",
                ]
            )
        )
    return '<section class="status-strip">' + "\n".join(cells) + "</section>"


def _review_workspace_html(
    chapter_brief: dict,
    full_chapter_brief: dict,
    episode_plan: dict,
    draft_review: dict,
    draft_qa: dict,
    human_approval: dict,
    draft_review_md: Path,
    draft_qa_md: Path,
) -> str:
    return "\n".join(
        [
            '<section class="workbench">',
            '<div class="workbench-head">',
            "<div>",
            "<h2>审核工作区</h2>",
            '<p class="muted">默认处理 Panel 明细；章节、页面、原文和 QA 在同一工作区内切换。</p>',
            "</div>",
            '<div class="segmented" role="tablist" aria-label="审核视图">',
            '<button type="button" class="active" data-tab-target="panelDetail">Panel 明细</button>',
            '<button type="button" data-tab-target="chapterSummary">章节摘要</button>',
            '<button type="button" data-tab-target="pageStoryboard">页面分镜</button>',
            '<button type="button" data-tab-target="sourceExcerpt">原文摘录</button>',
            '<button type="button" data-tab-target="qaView">QA</button>',
            "</div>",
            "</div>",
            '<div id="panelDetail" class="tab-panel active">',
            _panel_detail_html(episode_plan, draft_review, draft_qa),
            "</div>",
            '<div id="chapterSummary" class="tab-panel">',
            _breakdown_overview_html(chapter_brief, full_chapter_brief, episode_plan, draft_review, wrap=False),
            "</div>",
            '<div id="pageStoryboard" class="tab-panel">',
            _page_breakdown_html(chapter_brief, full_chapter_brief, episode_plan, draft_review, draft_qa, wrap=False),
            "</div>",
            '<div id="sourceExcerpt" class="tab-panel">',
            _raw_breakdown_html(draft_review_md, draft_qa_md, wrap=False),
            "</div>",
            '<div id="qaView" class="tab-panel">',
            _draft_qa_html(draft_qa, human_approval, wrap=False),
            "</div>",
            "</section>",
        ]
    )


def _panel_detail_html(episode_plan: dict, draft_review: dict, draft_qa: dict) -> str:
    plan_pages = _safe_list(episode_plan.get("pages"))
    review_pages = _safe_list(draft_review.get("pages"))
    qa_pages = _index_by_page_id(_safe_list(draft_qa.get("pages")))
    pages = review_pages or plan_pages
    rows = []
    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        page_id = str(page.get("page_id") or f"P{page_index:03d}")
        qa_panels = _index_by_panel_id(_safe_list(qa_pages.get(page_id, {}).get("panels")))
        panels = _safe_list(page.get("panels"))
        for panel_index, panel in enumerate(panels, start=1):
            if not isinstance(panel, dict):
                continue
            panel_id = str(panel.get("panel_id") or f"{page_id}_PANEL{panel_index:02d}")
            qa = qa_panels.get(panel_id, {})
            caption = str(panel.get("caption") or "")
            dialogue = _dialogue_text(panel.get("dialogue"))
            prompt = str(panel.get("prompt") or panel.get("full_prompt") or "")
            reference = str(panel.get("reference_alias") or qa.get("reference_alias") or "-")
            status = str(qa.get("approval_status") or "draft")
            issues = _list_items(qa.get("issues"))
            warnings = _list_items(qa.get("warnings"))
            state_class = "block" if issues else ("warn" if warnings else "pass")
            rows.extend(
                [
                    f'<tr class="{state_class}">',
                    f'<td class="mono">{escape(page_id.split("_")[-1])}<br><b>{escape(str(panel.get("order") or panel_index))}</b></td>',
                    "<td>",
                    f'<strong>{escape(str(panel.get("title") or panel_id))}</strong>',
                    f'<span>{escape(caption) if caption else "Caption: none"}</span>',
                    f'<span>{escape(dialogue) if dialogue else "Dialogue: none"}</span>',
                    f'<details><summary>展开 Prompt</summary><pre>{escape(prompt)}</pre></details>',
                    "</td>",
                    f'<td class="mono">{escape(reference)}</td>',
                    f'<td><span class="badge {state_class}">{escape(status)}</span></td>',
                    "</tr>",
                ]
            )
    if not rows:
        return '<div class="empty">还没有 Panel 明细。先运行“AI拆解”。</div>'
    return "\n".join(
        [
            '<div class="table-tools">',
            "<strong>Panel 明细</strong>",
            '<span class="muted">逐条审核 caption、dialogue、reference 和 prompt。</span>',
            "</div>",
            '<div class="detail-table-wrap">',
            '<table class="detail-table">',
            "<thead><tr><th>页 / 序号</th><th>画面与文案</th><th>参考</th><th>状态</th></tr></thead>",
            "<tbody>",
            "\n".join(rows),
            "</tbody></table>",
            "</div>",
        ]
    )


def _breakdown_overview_html(chapter_brief: dict, full_chapter_brief: dict, episode_plan: dict, draft_review: dict, wrap: bool = True) -> str:
    title = _first_value(full_chapter_brief.get("chapter_title"), chapter_brief.get("chapter_title"), episode_plan.get("episode_title"), draft_review.get("episode_title"), "未生成章节摘要")
    source_volume = _first_value(full_chapter_brief.get("source_volume"), chapter_brief.get("source_volume"), episode_plan.get("source_volume"))
    adaptation_status = _first_value(full_chapter_brief.get("adaptation_status"), chapter_brief.get("adaptation_status"), episode_plan.get("adaptation_status"), draft_review.get("adaptation_status"))
    visual_cues = _first_value(full_chapter_brief.get("visual_cues"), chapter_brief.get("visual_cues"), [])
    visual_cues = visual_cues if isinstance(visual_cues, list) else []
    cue_tags = []
    for cue in visual_cues[:18]:
        if isinstance(cue, dict):
            cue_tags.append(f'<span class="tag">{escape(str(cue.get("cue", "")))} <small>{escape(str(cue.get("count", "")))}</small></span>')
        else:
            cue_tags.append(f'<span class="tag">{escape(str(cue))}</span>')
    source_excerpt = _first_value(full_chapter_brief.get("source_excerpt"), chapter_brief.get("source_excerpt"))
    source_excerpt = _truncate_text(str(source_excerpt), 1800)
    return "\n".join(
        [
            '<section class="pane breakdown-hero">' if wrap else '<div class="breakdown-hero">',
            '<div class="pane-title-row">',
            "<div>",
            '<p class="eyebrow">AI拆解</p>',
            f"<h2>{escape(str(title))}</h2>",
            f'<p class="muted">{escape(str(source_volume))} · {escape(str(adaptation_status))}</p>',
            "</div>",
            f'<span class="badge {"warn" if "needs" in str(adaptation_status) or "blocked" in str(adaptation_status) else "pass"}">{"需人工审阅" if "needs" in str(adaptation_status) or "blocked" in str(adaptation_status) else "可进入审核"}</span>',
            "</div>",
            '<div class="overview-grid">',
            _info_tile("章节字数", _first_value(full_chapter_brief.get("chapter_char_count"), chapter_brief.get("chapter_char_count"), "-")),
            _info_tile("摘录字数", _first_value(full_chapter_brief.get("excerpt_char_count"), chapter_brief.get("excerpt_char_count"), "-")),
            _info_tile("页面数", len(_safe_list(_first_value(full_chapter_brief.get("page_beats"), chapter_brief.get("page_beats")))) or len(_safe_list(episode_plan.get("pages"))) or "-"),
            _info_tile("草稿页数", len(_safe_list(draft_review.get("pages"))) or "-"),
            "</div>",
            '<div class="tag-row">' + ("".join(cue_tags) if cue_tags else '<span class="tag muted-tag">暂无视觉关键词</span>') + "</div>",
            "<h3>原文摘录</h3>",
            f'<div class="text-excerpt">{escape(source_excerpt) if source_excerpt else "暂无摘录。请先运行 AI拆解。"}</div>',
            "</section>" if wrap else "</div>",
        ]
    )


def _page_breakdown_html(chapter_brief: dict, full_chapter_brief: dict, episode_plan: dict, draft_review: dict, draft_qa: dict, wrap: bool = True) -> str:
    brief_pages = _safe_list((full_chapter_brief or chapter_brief).get("page_beats"))
    plan_pages = _safe_list(episode_plan.get("pages"))
    review_pages = _index_by_page_id(_safe_list(draft_review.get("pages")))
    qa_pages = _index_by_page_id(_safe_list(draft_qa.get("pages")))
    page_rows = []
    max_pages = max(len(brief_pages), len(plan_pages), len(review_pages), len(qa_pages))
    for index in range(max_pages):
        plan_page = plan_pages[index] if index < len(plan_pages) and isinstance(plan_pages[index], dict) else {}
        brief_page = brief_pages[index] if index < len(brief_pages) and isinstance(brief_pages[index], dict) else {}
        page_id = str(plan_page.get("page_id") or f"SSJ_COMIC_EP_P{index + 1:03d}")
        review_page = review_pages.get(page_id, {})
        qa_page = qa_pages.get(page_id, {})
        title = review_page.get("title") or plan_page.get("title") or brief_page.get("title") or page_id
        summary = review_page.get("summary") or plan_page.get("summary") or brief_page.get("summary") or ""
        source_excerpt = review_page.get("source_excerpt") or plan_page.get("source_excerpt") or brief_page.get("source_excerpt") or ""
        detected_characters = _safe_list(review_page.get("detected_characters"))
        detected_locations = _safe_list(review_page.get("detected_locations"))
        panels = _safe_list(review_page.get("panels")) or _safe_list(plan_page.get("panels"))
        qa_panels = _index_by_panel_id(_safe_list(qa_page.get("panels")))
        page_rows.append(
            "\n".join(
                [
                    '<article class="breakdown-page">',
                    '<div class="page-breakdown-head">',
                    "<div>",
                    f"<h3>{escape(str(title))}</h3>",
                    f'<p class="muted">{escape(page_id)} · {escape(str(plan_page.get("status") or review_page.get("adaptation_status") or ""))}</p>',
                    "</div>",
                    f'<span class="badge {"warn" if review_page.get("needs_human_review") else "pass"}">{"需审" if review_page.get("needs_human_review") else "草稿"}</span>',
                    "</div>",
                    f'<p class="summary-text">{escape(_truncate_text(str(summary), 360)) if summary else "暂无页面摘要。"}</p>',
                    _tag_group("角色", detected_characters),
                    _tag_group("地点", detected_locations),
                    _panel_table_html(panels, qa_panels),
                    "<details>",
                    "<summary>查看本页原文摘录</summary>",
                    f'<div class="text-excerpt compact">{escape(_truncate_text(str(source_excerpt), 1600)) if source_excerpt else "暂无原文摘录。"}</div>',
                    "</details>",
                    "</article>",
                ]
            )
        )
    if not page_rows:
        page_rows.append('<div class="empty">还没有页面分镜数据。先运行 Web 控制台里的“运行 2. AI拆解”。</div>')
    return "\n".join(
        [
            '<section class="pane">' if wrap else '<div>',
            '<div class="pane-title-row">',
            "<h2>页面分镜</h2>",
            f'<span class="count-pill">{max_pages} 页</span>',
            "</div>",
            '<div class="page-breakdown-list">',
            "\n".join(page_rows),
            "</div>",
            "</section>" if wrap else "</div>",
        ]
    )


def _panel_table_html(panels: list, qa_panels: dict) -> str:
    if not panels:
        return '<div class="empty small">暂无 panel 拆解。</div>'
    rows = [
        '<div class="panel-table">',
        '<div class="panel-row panel-head"><span>Panel</span><span>画面 / 文案</span><span>参考</span><span>状态</span></div>',
    ]
    for index, panel in enumerate(panels, start=1):
        if not isinstance(panel, dict):
            continue
        panel_id = str(panel.get("panel_id") or f"PANEL{index:02d}")
        qa = qa_panels.get(panel_id, {})
        dialogue = _dialogue_text(panel.get("dialogue"))
        caption = str(panel.get("caption") or "")
        prompt = str(panel.get("prompt") or panel.get("full_prompt") or "")
        title = str(panel.get("title") or panel_id)
        status = str(qa.get("approval_status") or "draft")
        issues = _list_items(qa.get("issues"))
        warnings = _list_items(qa.get("warnings"))
        state_class = "block" if issues else ("warn" if warnings else "pass")
        rows.extend(
            [
                f'<div class="panel-row {state_class}">',
                f'<span class="mono">{escape(str(panel.get("order") or index))}</span>',
                "<span>",
                f"<strong>{escape(title)}</strong>",
                f'<small>{escape(caption) if caption else "Caption: none"}</small>',
                f'<small>{escape(dialogue) if dialogue else "Dialogue: none"}</small>',
                f'<details><summary>Prompt</summary><pre>{escape(prompt)}</pre></details>',
                "</span>",
                f'<span class="mono">{escape(str(panel.get("reference_alias") or qa.get("reference_alias") or "-"))}</span>',
                f'<span><b class="badge {state_class}">{escape(status)}</b></span>',
                "</div>",
            ]
        )
    rows.append("</div>")
    return "\n".join(rows)


def _draft_qa_html(draft_qa: dict, human_approval: dict, wrap: bool = True) -> str:
    summary = draft_qa.get("summary") if isinstance(draft_qa.get("summary"), dict) else {}
    approved = summary.get("approved_to_submit", 0)
    warnings = summary.get("warnings", 0)
    blocked = summary.get("blocked", 0)
    approval_text = "草稿已人工通过" if human_approval.get("approved") is True else "等待人工草稿审核"
    return "\n".join(
        [
            '<section class="pane qa-pane">' if wrap else '<div class="qa-pane">',
            '<div class="pane-title-row">',
            "<h2>草稿 QA</h2>",
            f'<span class="badge {"pass" if human_approval.get("approved") is True else "warn"}">{approval_text}</span>',
            "</div>",
            '<div class="overview-grid qa-grid">',
            _info_tile("可提交", approved),
            _info_tile("警告", warnings),
            _info_tile("阻塞", blocked),
            _info_tile("页面", summary.get("pages", "-")),
            "</div>",
            _id_list_html("已通过 Panel", _safe_list(draft_qa.get("approved_panel_ids")), "pass"),
            _id_list_html("警告 Panel", _safe_list(draft_qa.get("warning_panel_ids")), "warn"),
            _id_list_html("阻塞 Panel", _safe_list(draft_qa.get("blocked_panel_ids")), "block"),
            "</section>" if wrap else "</div>",
        ]
    )


def _raw_breakdown_html(draft_review_md: Path, draft_qa_md: Path, wrap: bool = True) -> str:
    review_text = _read_text_excerpt(draft_review_md)
    qa_text = _read_text_excerpt(draft_qa_md)
    if not review_text and not qa_text:
        return '<section class="pane"><h2>原始审核文件</h2><div class="empty">暂无 Markdown 审核文件。</div></section>' if wrap else '<div><h2>原始审核文件</h2><div class="empty">暂无 Markdown 审核文件。</div></div>'
    return "\n".join(
        [
            '<section class="pane raw-pane">' if wrap else '<div class="raw-pane">',
            "<h2>原始审核文件</h2>",
            "<details open>",
            "<summary>Draft Review Markdown</summary>",
            f"<pre>{escape(review_text) if review_text else '暂无 draft review。'}</pre>",
            "</details>",
            "<details>",
            "<summary>Draft QA Markdown</summary>",
            f"<pre>{escape(qa_text) if qa_text else '暂无 draft QA。'}</pre>",
            "</details>",
            "</section>" if wrap else "</div>",
        ]
    )


def _info_tile(label: str, value) -> str:
    return f'<div class="info-tile"><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong></div>'


def _tag_group(label: str, items: list) -> str:
    if not items:
        return ""
    tags = "".join(f'<span class="tag">{escape(str(item))}</span>' for item in items[:12])
    return f'<div class="inline-group"><b>{escape(label)}</b><span>{tags}</span></div>'


def _id_list_html(label: str, items: list, state: str) -> str:
    visible = items[:24]
    if not visible:
        return f'<div class="id-list"><strong>{escape(label)}</strong><span class="muted">无</span></div>'
    badges = "".join(f'<span class="mini-id {escape(state)}">{escape(str(item).split("_")[-1])}</span>' for item in visible)
    suffix = f'<span class="muted">+{len(items) - len(visible)}</span>' if len(items) > len(visible) else ""
    return f'<div class="id-list"><strong>{escape(label)}</strong><div>{badges}{suffix}</div></div>'


def _dialogue_text(value) -> str:
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return " / ".join(part for part in parts if part)
    return str(value or "")


def _safe_list(value) -> list:
    return value if isinstance(value, list) else []


def _truncate_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _preview_static_dir() -> Path:
    path = Path(__file__).with_name("comic_episode_pipeline_web.disabled") / "comic_previews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _preview_url(path: Path) -> str:
    relative = path.resolve().relative_to(_preview_static_dir().resolve()).as_posix()
    return f"{DEFAULT_COMFY_URL}/extensions/comic_episode_pipeline_node/comic_previews/{quote(relative)}"


def _image_url(path_value: str) -> str:
    raw = str(path_value or "").strip().strip('"')
    if not raw:
        return ""
    path = Path(raw)
    try:
        relative = path.resolve().relative_to(DEFAULT_COMFY_OUTPUT_ROOT.resolve())
        return (
            f"/view?filename={quote(relative.name)}"
            f"&subfolder={quote(str(relative.parent).replace(os.sep, '/'))}&type=output"
        )
    except Exception:
        return raw


def _index_by_page_id(items) -> dict:
    if not isinstance(items, list):
        return {}
    return {str(item.get("page_id")): item for item in items if isinstance(item, dict) and item.get("page_id")}


def _index_by_panel_id(items) -> dict:
    if not isinstance(items, list):
        return {}
    return {str(item.get("panel_id")): item for item in items if isinstance(item, dict) and item.get("panel_id")}


def _list_items(value) -> list:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value:
        return [str(value)]
    return []


def _flatten_panel_issues(page: dict) -> list:
    panels = page.get("panels") if isinstance(page, dict) else []
    if not isinstance(panels, list):
        return []
    issues = []
    for panel in panels:
        if isinstance(panel, dict):
            issues.extend(f"{panel.get('panel_id')}: {item}" for item in _list_items(panel.get("issues")))
    return issues


def _flatten_panel_warnings(page: dict) -> list:
    panels = page.get("panels") if isinstance(page, dict) else []
    if not isinstance(panels, list):
        return []
    warnings = []
    for panel in panels:
        if isinstance(panel, dict):
            warnings.extend(f"{panel.get('panel_id')}: {item}" for item in _list_items(panel.get("warnings")))
    return warnings


def _panel_issue_count(page: dict) -> int:
    return len(_flatten_panel_issues(page))


def _qa_line(label: str, issues, warnings) -> str:
    issue_items = _list_items(issues)
    warning_items = _list_items(warnings)
    status = "pass" if not issue_items else "block"
    detail = issue_items[:3] or warning_items[:3] or ["无问题"]
    return (
        f'<div class="qa-line {status}">'
        f"<strong>{escape(label)}</strong>"
        f"<span>{escape('；'.join(detail))}</span>"
        "</div>"
    )


def _preview_control_context(workspace: Path, episode_number: int, status_summary: dict) -> dict:
    return {
        "workspacePath": str(workspace),
        "novelPath": DEFAULT_NOVEL,
        "episodeNumber": int(episode_number),
        "pages": int(status_summary.get("total_pages") or status_summary.get("pages") or DEFAULT_PAGES),
        "excerptChars": 3600,
        "encoding": DEFAULT_ENCODING,
        "comfyUrl": DEFAULT_COMFY_URL,
        "maxPanels": "1",
        "maxBatches": "1",
        "resultPaths": {
            "breakdown": str(workspace / "manifests" / "comfy_modular_breakdown.json"),
            "approval": str(workspace / "manifests" / "comfy_modular_human_approval.json"),
            "generation": str(workspace / "manifests" / "comfy_modular_generation.json"),
            "review": str(workspace / "manifests" / "comfy_modular_page_review.json"),
            "next": str(workspace / "manifests" / "comfy_modular_next_episode.json"),
            "switchDraft": str(workspace / "manifests" / "comfy_switch_draft_approved.json"),
            "switchGeneration": str(workspace / "manifests" / "comfy_switch_allow_generation.json"),
            "switchReview": str(workspace / "manifests" / "comfy_switch_page_review.json"),
            "switchNext": str(workspace / "manifests" / "comfy_switch_next_episode.json"),
        },
    }


def _control_panel_html() -> str:
    return """
<section class="control" aria-label="漫画流水线控制台">
  <div class="actions">
    <button type="button" data-stage="breakdown">AI拆解</button>
    <button type="button" data-stage="approve">草稿通过</button>
    <button type="button" data-stage="generate" class="danger">生成漫画</button>
    <button type="button" data-stage="review">页面审核</button>
    <button type="button" data-stage="next">下一章</button>
    <button type="button" data-stage="refresh" class="secondary">刷新</button>
    <a class="open-comfy" href="/" target="_blank" rel="noreferrer">ComfyUI</a>
  </div>
  <details class="settings-drawer">
    <summary>运行设置</summary>
    <div class="runbar">
      <label class="grow">小说文件<input id="comicNovelPath" type="text"></label>
      <label>章节<input id="comicEpisodeNumber" type="number" min="1" max="999"></label>
      <label>页数<input id="comicPages" type="number" min="1" max="64"></label>
      <label>面板<input id="comicMaxPanels" type="number" min="1" max="32"></label>
      <label>批次<input id="comicMaxBatches" type="number" min="1" max="32"></label>
    </div>
  </details>
  <details class="log-drawer">
    <summary>系统运行日志</summary>
    <pre id="comicControlLog" class="control-log">就绪</pre>
  </details>
</section>
"""


def _metric_card(label: str, value, detail: str) -> str:
    return (
        '<div class="metric">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(str(value))}</strong>"
        f"<small>{escape(str(detail))}</small>"
        "</div>"
    )


def _preview_css() -> str:
    return """
:root {
  color-scheme: light;
  font-family: "JetBrains Mono", "Microsoft YaHei UI", "Microsoft YaHei", Consolas, monospace;
  background: #f7f3ea;
  color: #1c1c16;
  --bg: #f7f3ea;
  --surface: #fdf9f0;
  --surface-low: #f1eee5;
  --surface-high: #ece8df;
  --surface-code: #31302b;
  --text: #1c1c16;
  --muted: #554339;
  --muted-soft: #887367;
  --line: #ded6c8;
  --line-strong: #1c1c16;
  --accent: #c66a2b;
  --accent-dark: #954503;
  --error: #ba1a1a;
  --error-soft: #ffdad6;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--text); }
a { color: inherit; text-decoration-thickness: 1px; text-underline-offset: 3px; }
.ops-shell { min-height: 100vh; padding: 24px; background: var(--bg); }
.topbar { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; max-width: 1880px; margin: 0 auto 16px; padding-bottom: 16px; border-bottom: 1px solid var(--line-strong); }
.title-block { min-width: 0; }
.top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.ops-layout { display: grid; grid-template-columns: 248px minmax(0, 1fr); gap: 16px; max-width: 1920px; margin: 0 auto; align-items: start; }
.workspace { min-width: 0; }
.content-grid { display: grid; grid-template-columns: minmax(0, 1fr) 372px; gap: 16px; align-items: start; }
.breakdown-stack, .review-pane { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.eyebrow { margin: 0 0 6px; color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: 0; text-transform: uppercase; }
h1 { margin: 0; font-size: 24px; line-height: 1.25; font-weight: 700; letter-spacing: 0; overflow-wrap: anywhere; }
h2 { margin: 0; font-size: 16px; line-height: 1.35; font-weight: 700; letter-spacing: 0; }
h3 { margin: 0; font-size: 14px; line-height: 1.45; font-weight: 700; letter-spacing: 0; overflow-wrap: anywhere; }
.muted { color: var(--muted); margin: 4px 0 0; font-size: 12px; line-height: 1.55; }
.overall, .badge { display: inline-flex; align-items: center; justify-content: center; min-height: 26px; padding: 3px 8px; border-radius: 0; font-size: 12px; font-weight: 700; white-space: nowrap; text-transform: uppercase; letter-spacing: 0; }
.pass { background: var(--surface-low); color: var(--text); border: 1px solid var(--line-strong); }
.block { background: var(--error-soft); color: #93000a; border: 1px solid var(--error); }
.warn { background: #ffdbc9; color: #753400; border: 1px solid var(--accent); }
.idle, .ready { background: var(--surface); color: var(--muted); border: 1px solid var(--line); }
.stage-rail, .pane, .control, .metric { background: var(--surface); border: 1px solid var(--line); border-radius: 0; box-shadow: none; }
.stage-rail { position: sticky; top: 16px; padding: 12px; }
.stage-rail h2 { margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
.stage-step { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 8px; align-items: start; padding: 10px 8px; border: 1px solid transparent; border-left: 2px solid var(--line); border-radius: 0; background: transparent; }
.stage-step + .stage-step { margin-top: 4px; }
.stage-step.pass { border-color: var(--line); border-left-color: var(--line-strong); background: var(--surface-low); }
.stage-step.warn { border-color: #ffb68c; border-left-color: var(--accent); background: #ffdbc9; }
.stage-step.block { border-color: var(--error); border-left-color: var(--error); background: var(--error-soft); }
.stage-step.ready { border-color: var(--line); border-left-color: var(--accent); background: var(--surface); }
.stage-step strong, .stage-step small { display: block; min-width: 0; overflow-wrap: anywhere; }
.stage-step strong { font-size: 13px; line-height: 18px; }
.stage-step small { margin-top: 2px; color: var(--muted); font-size: 12px; line-height: 16px; }
.stage-index { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 0; background: var(--surface-high); border: 1px solid var(--line); font-size: 12px; font-weight: 700; color: var(--text); }
.metrics { display: none; }
.status-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0; overflow: hidden; margin-bottom: 12px; border: 1px solid var(--line); border-radius: 0; background: var(--line); }
.status-cell { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; min-height: 42px; padding: 7px 10px; background: var(--surface-low); border-right: 1px solid var(--line); }
.status-cell:last-child { border-right: 0; }
.status-cell span, .status-cell small { color: var(--muted); font-size: 11px; white-space: nowrap; text-transform: uppercase; letter-spacing: 0; }
.status-cell strong { font-size: 15px; line-height: 1.2; overflow-wrap: anywhere; }
.control { padding: 10px; margin: 0 0 12px; }
.control-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
.control-head h2 { margin-bottom: 4px; }
.open-comfy { display: inline-flex; align-items: center; min-height: 32px; padding: 0 10px; border-radius: 0; border: 1px solid var(--line-strong); color: var(--text); text-decoration: none; font-size: 13px; white-space: nowrap; background: transparent; }
.open-comfy:hover { background: var(--text); color: #fdf9f0; }
.runbar { display: grid; grid-template-columns: minmax(220px, 1fr) 72px 72px 72px 72px; gap: 8px; align-items: end; }
.runbar label { display: grid; gap: 4px; color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0; }
.runbar input { width: 100%; min-height: 32px; border: 1px solid var(--line); border-radius: 0; padding: 5px 8px; font: inherit; color: var(--text); background: var(--surface); }
.runbar input:focus, .control input:focus { outline: 1px solid var(--accent); outline-offset: 0; border-color: var(--accent); }
.control-grid { display: grid; grid-template-columns: minmax(280px, 2fr) repeat(4, minmax(80px, 1fr)); gap: 8px; }
.control label { display: grid; gap: 4px; color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0; }
.control input { width: 100%; min-height: 32px; border: 1px solid var(--line); border-radius: 0; padding: 5px 8px; font: inherit; color: var(--text); background: var(--surface); }
.actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.actions button { min-height: 32px; border: 1px solid var(--accent); background: transparent; color: var(--accent-dark); border-radius: 0; padding: 0 10px; font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; }
.actions button:hover { background: var(--accent); color: #fff; }
.actions button.secondary { background: transparent; color: var(--text); border-color: var(--line-strong); }
.actions button.secondary:hover { background: var(--text); color: #fdf9f0; }
.actions button.danger { color: #93000a; border-color: var(--error); }
.actions button.danger:hover { background: var(--error); color: #fff; }
.actions button:disabled { opacity: .55; cursor: progress; }
.settings-drawer, .log-drawer { margin-top: 8px; border-top: 1px solid var(--line); padding-top: 6px; }
.settings-drawer summary, .log-drawer summary { cursor: pointer; color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0; }
.settings-drawer .runbar { margin-top: 8px; }
.control-log { min-height: 38px; max-height: 160px; overflow: auto; background: var(--surface-code); color: #f4f0e7; border: 1px solid var(--line-strong); border-radius: 0; padding: 9px; margin: 8px 0 0; font-size: 12px; white-space: pre-wrap; }
.metric { padding: 10px; min-height: 74px; }
.metric span, .metric small { display: block; color: var(--muted); font-size: 12px; }
.metric strong { display: block; margin: 6px 0 2px; font-size: 21px; line-height: 1; overflow-wrap: anywhere; }
.pane { padding: 12px; min-width: 0; }
.pane-tight { padding: 10px; }
.pane-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.workbench { min-width: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 0; overflow: hidden; }
.workbench-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 12px; border-bottom: 1px solid var(--line); background: var(--surface-low); }
.segmented { display: flex; flex-wrap: wrap; gap: 0; padding: 0; border: 1px solid var(--line); border-radius: 0; background: var(--surface); }
.segmented button { min-height: 30px; border: 0; border-right: 1px solid var(--line); border-radius: 0; padding: 0 10px; background: transparent; color: var(--muted); font: inherit; font-size: 12px; cursor: pointer; }
.segmented button:last-child { border-right: 0; }
.segmented button:hover { background: var(--surface-high); color: var(--text); }
.segmented button.active { background: var(--text); color: #fdf9f0; }
.tab-panel { display: none; padding: 12px; }
.tab-panel.active { display: block; }
.table-tools { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.detail-table-wrap { max-height: calc(100vh - 260px); min-height: 560px; overflow: auto; border: 1px solid var(--line); border-radius: 0; background: var(--surface); }
.detail-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12px; }
.detail-table th { position: sticky; top: 0; z-index: 1; background: var(--surface-high); color: var(--muted); font-size: 11px; text-align: left; border-bottom: 1px solid var(--line); padding: 8px; text-transform: uppercase; letter-spacing: 0; }
.detail-table td { vertical-align: top; border-bottom: 1px solid var(--line); padding: 8px; overflow-wrap: anywhere; background: var(--surface); }
.detail-table th:nth-child(1), .detail-table td:nth-child(1) { width: 76px; }
.detail-table th:nth-child(3), .detail-table td:nth-child(3) { width: 170px; }
.detail-table th:nth-child(4), .detail-table td:nth-child(4) { width: 116px; }
.detail-table tr:hover td { background: var(--surface-low); }
.detail-table td strong, .detail-table td span { display: block; line-height: 1.5; }
.detail-table td span { color: var(--muted); }
.detail-table details { margin-top: 4px; }
.detail-table summary { cursor: pointer; color: var(--accent-dark); font-weight: 700; }
.detail-table pre { max-height: 220px; overflow: auto; white-space: pre-wrap; margin: 6px 0 0; padding: 8px; border-radius: 0; background: var(--surface-code); color: #f4f0e7; line-height: 1.5; }
.overview-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 12px 0; }
.info-tile { min-height: 58px; border: 1px solid var(--line); background: var(--surface-low); border-radius: 0; padding: 8px; }
.info-tile span { display: block; color: var(--muted); font-size: 12px; }
.info-tile strong { display: block; margin-top: 6px; font-size: 18px; line-height: 1; overflow-wrap: anywhere; }
.tag-row, .inline-group span { display: flex; flex-wrap: wrap; gap: 6px; }
.tag-row { margin: 10px 0 14px; }
.tag, .count-pill, .mini-id { display: inline-flex; align-items: center; min-height: 22px; padding: 2px 7px; border-radius: 0; border: 1px solid var(--line); background: var(--surface); color: var(--text); font-size: 12px; line-height: 16px; }
.tag small { margin-left: 4px; color: var(--muted); }
.muted-tag { color: var(--muted); }
.text-excerpt { padding: 10px; border: 1px solid var(--line); border-radius: 0; background: var(--surface-low); white-space: pre-wrap; line-height: 1.65; font-size: 13px; color: var(--text); max-height: 360px; overflow: auto; overflow-wrap: anywhere; }
.text-excerpt.compact { max-height: 240px; margin-top: 8px; }
.page-breakdown-list { display: flex; flex-direction: column; gap: 10px; }
.breakdown-page { border: 1px solid var(--line); border-radius: 0; padding: 10px; background: var(--surface); }
.page-breakdown-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.summary-text { margin: 0 0 8px; color: var(--text); line-height: 1.6; font-size: 13px; }
.inline-group { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 8px; align-items: start; margin: 6px 0; font-size: 12px; }
.inline-group b { color: var(--muted); }
.panel-table { margin-top: 10px; border: 1px solid var(--line); border-radius: 0; overflow: hidden; }
.panel-row { display: grid; grid-template-columns: 54px minmax(260px, 1fr) minmax(120px, 160px) 96px; gap: 8px; padding: 8px; border-top: 1px solid var(--line); align-items: start; font-size: 12px; background: var(--surface); }
.panel-row:first-child { border-top: 0; }
.panel-head { background: var(--surface-high); color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0; }
.panel-row strong, .panel-row small { display: block; overflow-wrap: anywhere; }
.panel-row small { color: var(--muted); line-height: 1.5; }
.panel-row details { margin-top: 4px; }
.panel-row summary, .raw-pane summary, .breakdown-page summary { cursor: pointer; color: var(--accent-dark); font-weight: 700; }
.panel-row pre, .raw-pane pre { max-height: 260px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; margin: 6px 0 0; padding: 8px; border-radius: 0; background: var(--surface-code); color: #f4f0e7; font-size: 12px; line-height: 1.55; }
.mono { font-family: "JetBrains Mono", Consolas, monospace; }
.qa-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.id-list { display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 8px; align-items: start; margin-top: 8px; font-size: 12px; }
.id-list strong { color: var(--muted); }
.id-list div { display: flex; flex-wrap: wrap; gap: 5px; }
.mini-id.pass { background: var(--surface); border-color: var(--line-strong); color: var(--text); }
.mini-id.warn { background: #ffdbc9; border-color: var(--accent); color: #753400; }
.mini-id.block { background: var(--error-soft); border-color: var(--error); color: #93000a; }
.raw-pane details + details { margin-top: 10px; }
.empty { padding: 12px; border: 1px dashed var(--line); border-radius: 0; color: var(--muted); background: var(--surface-low); font-size: 13px; }
.empty.small { padding: 8px; }
.contact { display: block; background: var(--surface); border: 1px solid var(--line); border-radius: 0; padding: 8px; margin-top: 10px; }
.contact img { display: block; width: 100%; height: auto; border-radius: 0; }
.review-pane { position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow: auto; }
.preview-nav h2, .checklist h2 { margin-bottom: 8px; }
.check-row { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 8px; align-items: center; padding: 7px 0; border-top: 1px solid var(--line); }
.check-row:first-of-type { border-top: 0; }
.check-mark { display: inline-flex; justify-content: center; align-items: center; width: 28px; min-height: 22px; border-radius: 0; font-size: 11px; font-weight: 800; background: var(--surface-low); }
.check-row strong, .check-row small { display: block; }
.check-row small { color: var(--muted); font-size: 12px; }
.preview-list { display: flex; flex-direction: column; gap: 8px; }
.preview-page-link { display: grid; grid-template-columns: 54px minmax(0, 1fr) auto; gap: 8px; align-items: center; text-decoration: none; padding: 6px; border: 1px solid var(--line); border-radius: 0; background: var(--surface); }
.preview-page-link:hover { border-color: var(--line-strong); background: var(--surface-low); }
.preview-page-link img { width: 54px; aspect-ratio: 2 / 3; object-fit: cover; border-radius: 0; background: var(--surface-code); }
.preview-page-link strong, .preview-page-link small { display: block; min-width: 0; overflow-wrap: anywhere; }
.preview-page-link small { color: var(--muted); font-size: 12px; line-height: 1.35; }
.mini-panel-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; margin: -4px 0 4px 62px; }
.mini-panel { display: block; border: 1px solid var(--line); border-radius: 0; overflow: hidden; background: var(--surface-low); }
.mini-panel:hover { border-color: var(--line-strong); }
.mini-panel img { display: block; width: 100%; aspect-ratio: 2 / 3; object-fit: cover; }
.pages { display: flex; flex-direction: column; gap: 10px; }
.review-page { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 10px; padding: 10px; border: 1px solid var(--line); border-radius: 0; background: var(--surface); }
.review-thumb { min-width: 0; }
.page-img { display: block; width: 100%; aspect-ratio: 2 / 3; object-fit: cover; background: var(--surface-code); border-radius: 0; }
.page-title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.qa-lines { display: grid; gap: 6px; margin: 10px 0; }
.qa-line { display: grid; grid-template-columns: 52px minmax(0, 1fr); gap: 6px; padding: 6px 8px; border-radius: 0; font-size: 12px; }
.qa-line strong { white-space: nowrap; }
.qa-line span { min-width: 0; overflow-wrap: anywhere; }
.panel-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.panel { display: block; text-decoration: none; border-radius: 0; overflow: hidden; background: var(--surface-low); border: 1px solid var(--line); }
.panel img { display: block; width: 100%; aspect-ratio: 2 / 3; object-fit: cover; }
.panel span { display: block; padding: 5px; font-size: 11px; color: var(--text); overflow-wrap: anywhere; }
@media (max-width: 1240px) {
  .ops-layout { grid-template-columns: 1fr; }
  .stage-rail { position: static; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
  .stage-rail h2 { grid-column: 1 / -1; margin-bottom: 4px; }
  .stage-step + .stage-step { margin-top: 0; }
  .content-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .ops-shell { padding: 12px; }
  .topbar { align-items: flex-start; flex-direction: column; }
  .control-head { flex-direction: column; }
  .runbar { grid-template-columns: 1fr 1fr; }
  .control-grid { grid-template-columns: 1fr; }
  .status-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .review-pane { position: static; max-height: none; overflow: visible; }
  .overview-grid, .qa-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stage-rail { grid-template-columns: 1fr; }
  .panel-row { grid-template-columns: 42px minmax(0, 1fr); }
  .workbench-head { flex-direction: column; }
  .detail-table-wrap { min-height: 420px; max-height: none; }
  .detail-table { min-width: 760px; }
  .panel-row > span:nth-child(3), .panel-row > span:nth-child(4) { grid-column: 2; }
  .review-page { grid-template-columns: 110px minmax(0, 1fr); }
  .panel-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 560px) {
  .status-strip, .overview-grid, .qa-grid { grid-template-columns: 1fr; }
  .review-page { grid-template-columns: 1fr; }
  .page-img { max-height: 520px; object-fit: contain; }
}
"""


def _control_script() -> str:
    return r"""
(function () {
  const context = window.COMIC_PIPELINE_CONTEXT || {};
  const $ = (id) => document.getElementById(id);
  const log = (message, data) => {
    const box = $("comicControlLog");
    const stamp = new Date().toLocaleTimeString();
    const detail = data ? "\n" + (typeof data === "string" ? data : JSON.stringify(data, null, 2)) : "";
    box.textContent = `[${stamp}] ${message}${detail}`;
  };
  const readConfig = () => ({
    workspacePath: context.workspacePath || "",
    novelPath: $("comicNovelPath").value.trim(),
    episodeNumber: Number($("comicEpisodeNumber").value || context.episodeNumber || 3),
    pages: Number($("comicPages").value || context.pages || 8),
    excerptChars: Number(context.excerptChars || 3600),
    encoding: context.encoding || "gb18030",
    comfyUrl: context.comfyUrl || location.origin,
    maxPanels: String($("comicMaxPanels").value || context.maxPanels || "1"),
    maxBatches: String($("comicMaxBatches").value || context.maxBatches || "1"),
    resultPaths: context.resultPaths || {}
  });
  const link = (node, output) => [String(node), output];
  const switchNode = (enabled, stageName, note, outputJson, confirm = false) => ({
    class_type: "ComicFlowSwitch",
    inputs: {
      enabled,
      stage_name: stageName,
      note,
      workspace_path: context.workspacePath,
      output_json: outputJson,
      auto_run_on_open: true,
      confirm_before_auto_run: confirm,
      auto_run_delay_ms: 500
    }
  });
  const buildPrompt = (stage) => {
    const cfg = readConfig();
    const paths = cfg.resultPaths;
    const approveDraft = ["approve", "generate", "review", "next"].includes(stage);
    const allowGeneration = stage === "generate";
    const allowReview = ["review", "next", "refresh"].includes(stage);
    const allowNext = stage === "next";
    return {
      "1": { class_type: "ComicNovelSource", inputs: { workspace_path: cfg.workspacePath, novel_path: cfg.novelPath, episode_number: cfg.episodeNumber, pages: cfg.pages, excerpt_chars: cfg.excerptChars, encoding: cfg.encoding } },
      "2": { class_type: "ComicAIBreakdown", inputs: { source_json: link(1, 0), action: "draft_from_novel", force: false, overwrite_page_plans: false, refine_page_plans: true, timeout_seconds: 1800, run_label: "ui_breakdown", result_path: paths.breakdown } },
      "7": switchNode(approveDraft, "草稿审核通过", "Web 控制台：人工确认草稿后打开。", paths.switchDraft),
      "3": { class_type: "ComicHumanApprovalGate", inputs: { draft_qa_json: link(2, 1), approve: link(7, 0), page_ids: "", reviewer: "web_console", note: "Web 控制台记录：草稿审核通过。", output_json: paths.approval } },
      "8": switchNode(allowGeneration, "确认生成漫画", "Web 控制台：确认消耗图像生成额度。", paths.switchGeneration, true),
      "4": { class_type: "ComicGenerateBatch", inputs: { approved: link(3, 0), approval_json: link(3, 1), allow_generation: link(8, 0), episode_number: link(1, 1), workspace_path: cfg.workspacePath, comfy_url: cfg.comfyUrl, max_panels: cfg.maxPanels, max_batches: cfg.maxBatches, run_label: "ui_generate", result_path: paths.generation } },
      "9": switchNode(allowReview, "启动页面审核QA", "Web 控制台：生成完成后执行页面组装和 QA。", paths.switchReview),
      "5": { class_type: "ComicPageReviewQA", inputs: { episode_number: link(1, 1), review_action: "assemble_and_qa", review_enabled: link(9, 0), workspace_path: cfg.workspacePath, comfy_url: cfg.comfyUrl, timeout_seconds: 1800, run_label: "ui_page_review", result_path: paths.review } },
      "10": switchNode(allowNext, "进入下一章循环", "Web 控制台：页面审核通过后创建下一章骨架。", paths.switchNext),
      "6": { class_type: "ComicNextEpisode", inputs: { current_episode_number: link(1, 1), review_result_json: link(5, 0), create_skeleton_if_missing: true, continue_enabled: link(10, 0), workspace_path: cfg.workspacePath, pages: cfg.pages, result_path: paths.next } }
    };
  };
  const queueStage = async (stage) => {
    if (stage === "generate") {
      const ok = window.confirm("确认开始真实图片生成？这可能消耗模型或接口额度。");
      if (!ok) return;
    }
    if (stage === "refresh") {
      window.location.reload();
      return;
    }
    const buttons = [...document.querySelectorAll("[data-stage]")];
    buttons.forEach((button) => (button.disabled = true));
    try {
      const body = { prompt: buildPrompt(stage), client_id: `comic-web-${Date.now()}` };
      log(`提交阶段：${stage}`, { episode: readConfig().episodeNumber, pages: readConfig().pages });
      const response = await fetch("/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const text = await response.text();
      let data;
      try { data = JSON.parse(text); } catch { data = text; }
      if (!response.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
      log("已提交到 ComfyUI 队列", data);
      window.setTimeout(() => window.location.reload(), 4000);
    } catch (error) {
      log("提交失败", error && error.message ? error.message : String(error));
    } finally {
      buttons.forEach((button) => (button.disabled = false));
    }
  };
  const init = () => {
    $("comicNovelPath").value = context.novelPath || "";
    $("comicEpisodeNumber").value = context.episodeNumber || 3;
    $("comicPages").value = context.pages || 8;
    $("comicMaxPanels").value = context.maxPanels || "1";
    $("comicMaxBatches").value = context.maxBatches || "1";
    document.querySelectorAll("[data-stage]").forEach((button) => {
      button.addEventListener("click", () => queueStage(button.dataset.stage));
    });
    document.querySelectorAll("[data-tab-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const target = button.dataset.tabTarget;
        document.querySelectorAll("[data-tab-target]").forEach((item) => item.classList.toggle("active", item === button));
        document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === target));
      });
    });
  };
  init();
})();
"""


def _infer_workspace_from_path(path: Path) -> Path:
    resolved = path.resolve()
    parts = list(resolved.parts)
    try:
        index = [part.lower() for part in parts].index("manifests")
        return Path(*parts[:index])
    except ValueError:
        return Path(DEFAULT_WORKSPACE)


def _episode_number_from_id(value: str) -> int:
    match = re.search(r"EP0*(\d+)|episode0*(\d+)", str(value), re.IGNORECASE)
    if not match:
        return 0
    return int(next(group for group in match.groups() if group))


def _int_value(value, name: str, minimum: int | None = None, maximum: int | None = None) -> int:
    text = str(value).strip()
    try:
        number = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {number}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {number}")
    return number


def _repair_generate_batch_widgets(max_panels, max_batches, run_label, result_path):
    # ComfyUI stores widgets by position. Linking an earlier widget on an old
    # canvas can shift values left and put run_label into max_batches.
    if not str(max_batches).strip().lstrip("-").isdigit() and str(run_label).strip():
        return max_panels, max_panels, str(max_batches), str(run_label)
    return max_panels, max_batches, run_label, result_path


def _command_error(prefix: str, completed: subprocess.CompletedProcess) -> str:
    stdout_tail = _tail_text(completed.stdout)
    stderr_tail = _tail_text(completed.stderr)
    return f"{prefix} with exit code {completed.returncode}.\nSTDOUT:\n{stdout_tail}\nSTDERR:\n{stderr_tail}"


def _foreground_command(
    workspace: Path,
    episode_number: int,
    mode: str,
    comfy_url: str,
    run_label: str,
    result_path: Path,
) -> list[str]:
    script = _script(workspace, "run_comic_episode_pipeline.ps1")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-EpisodeNumber",
        str(episode_number),
        "-ComfyUrl",
        str(comfy_url),
        "-RunLabel",
        run_label,
        "-ResultPath",
        str(result_path),
    ]
    if mode == "health_qa":
        command += [
            "-CheckComfyHealth",
            "-OnlyStage",
            "comfy_health,status_report,lettering_qa,consistency_qa,image_health_qa",
            "-RunLetteringQa",
            "-RunConsistencyQa",
            "-RunImageHealthQa",
        ]
    elif mode == "assemble_qa":
        command += [
            "-SkipImageGeneration",
            "-AssemblePages",
            "-OnlyStage",
            "assemble_pages,status_report,lettering_qa,consistency_qa,image_health_qa",
            "-RunLetteringQa",
            "-RunConsistencyQa",
            "-RunImageHealthQa",
        ]
    elif mode == "dry_run":
        command += ["-DryRun", "-SkipImageGeneration"]
    else:
        raise ValueError(f"Unsupported comic pipeline mode: {mode}")
    return command


def _start_generation_background(
    workspace: Path,
    episode_number: int,
    comfy_url: str,
    max_panels: int,
    max_batches: int,
    run_label: str,
    result_path: Path,
) -> tuple[dict, str]:
    script = _script(workspace, "run_comic_episode_auto_batches.ps1")
    logs = workspace / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    stdout_path = logs / f"comfy_node_{run_label}_ep{episode_number:02d}_{timestamp}_stdout.log"
    stderr_path = logs / f"comfy_node_{run_label}_ep{episode_number:02d}_{timestamp}_stderr.log"
    command_text = (
        "Start-Sleep -Seconds 3; "
        f"& '{_ps_quote(script)}' "
        f"-EpisodeNumber {episode_number} "
        f"-ComfyUrl '{_ps_quote(comfy_url)}' "
        f"-MaxPanelsPerBatch {max_panels} "
        f"-MaxBatches {max_batches} "
        "-PollSeconds 5 "
        "-MaxPolls 24 "
        "-RequiredIdlePolls 2 "
        "-IdleTimeoutRetries 1 "
        "-IdleRetrySeconds 30 "
        "-RateLimitRetries 1 "
        "-RateLimitRetrySeconds 60 "
        "-UpstreamErrorRetries 1 "
        "-UpstreamErrorRetrySeconds 60 "
        "-LongRunningQueueSeconds 300 "
        f"-RunLabel '{_ps_quote(run_label)}' "
        f"-ResultPath '{_ps_quote(result_path)}'"
    )
    env = _subprocess_env()
    with stdout_path.open("a", encoding="utf-8", errors="replace") as stdout_handle:
        with stderr_path.open("a", encoding="utf-8", errors="replace") as stderr_handle:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command_text],
                cwd=str(workspace),
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=env,
            )
    summary = {
        "mode": "generation_background",
        "episode_number": episode_number,
        "background_started": True,
        "process_id": proc.pid,
        "result_path": str(result_path),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "next_action": "wait_for_result_path_then_refresh_status",
    }
    return summary, f"Background generation process started: {proc.pid}"


def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess:
    env = _subprocess_env()
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, int(timeout_seconds)),
    )


def _subprocess_env() -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _summary_from_result(path: Path) -> dict:
    if not path.is_file():
        return {"result_exists": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"result_exists": True, "result_parse_error": str(exc)}
    summary = {
        "result_exists": True,
        "completed": data.get("completed"),
        "blocked": data.get("blocked"),
        "waiting": data.get("waiting"),
        "partial": data.get("partial"),
        "failed": data.get("failed"),
        "summary": data.get("summary"),
    }
    stages = data.get("stages")
    if isinstance(stages, list):
        summary["stages"] = [
            {"name": stage.get("name"), "status": stage.get("status")}
            for stage in stages
            if isinstance(stage, dict)
        ]
    return summary


def _tail_text(text: str, max_lines: int = 30, max_chars: int = 4000) -> str:
    if not text:
        return ""
    lines = text.splitlines()[-max_lines:]
    tail = "\n".join(lines)
    if len(tail) > max_chars:
        return tail[-max_chars:]
    return tail


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return token.strip("._-") or "run"


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _ps_quote(value) -> str:
    return str(value).replace("'", "''")
