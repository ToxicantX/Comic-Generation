import argparse
import json
import re
from pathlib import Path


MAX_SEED = 2**64 - 1


def local_workflow_options(config: dict) -> dict:
    """Map the global env-shaped config to the local workflow builder."""
    return {
        "checkpoint": str(config.get("COMIC_PIPELINE_COMFY_CHECKPOINT") or "").strip(),
        "lora_name": str(config.get("COMIC_PIPELINE_COMFY_LORA_NAME") or "").strip(),
        "lora_strength_model": float(config.get("COMIC_PIPELINE_COMFY_LORA_STRENGTH_MODEL") or 1.0),
        "lora_strength_clip": float(config.get("COMIC_PIPELINE_COMFY_LORA_STRENGTH_CLIP") or 1.0),
        "controlnet_name": str(config.get("COMIC_PIPELINE_COMFY_CONTROLNET_NAME") or "").strip(),
        "control_strength": float(config.get("COMIC_PIPELINE_COMFY_CONTROLNET_STRENGTH") or 1.0),
        "control_start": float(config.get("COMIC_PIPELINE_COMFY_CONTROLNET_START") or 0.0),
        "control_end": float(config.get("COMIC_PIPELINE_COMFY_CONTROLNET_END") or 1.0),
        "steps": int(config.get("COMIC_PIPELINE_COMFY_STEPS") or 28),
        "cfg": float(config.get("COMIC_PIPELINE_COMFY_CFG") or 7.0),
        "sampler_name": str(config.get("COMIC_PIPELINE_COMFY_SAMPLER") or "dpmpp_2m").strip(),
        "scheduler": str(config.get("COMIC_PIPELINE_COMFY_SCHEDULER") or "karras").strip(),
    }


def parse_image_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*", str(value or ""), re.IGNORECASE)
    if not match:
        raise ValueError("image_size must use WIDTHxHEIGHT format")
    width, height = (int(match.group(1)), int(match.group(2)))
    if width < 64 or height < 64 or width % 8 or height % 8:
        raise ValueError("image dimensions must be at least 64 and divisible by 8")
    return width, height


def build_local_image_workflow(
    *,
    prompt: str,
    negative_prompt: str,
    filename_prefix: str,
    checkpoint: str,
    image_size: str = "1024x1536",
    seed: int = 0,
    steps: int = 28,
    cfg: float = 7.0,
    sampler_name: str = "dpmpp_2m",
    scheduler: str = "karras",
    denoise: float = 1.0,
    lora_name: str = "",
    lora_strength_model: float = 1.0,
    lora_strength_clip: float = 1.0,
    controlnet_name: str = "",
    control_image: str = "",
    control_source: str = "",
    control_strength: float = 1.0,
    control_start: float = 0.0,
    control_end: float = 1.0,
    client_id: str = "codex-comic-local",
) -> dict:
    prompt = str(prompt or "").strip()
    checkpoint = str(checkpoint or "").strip()
    filename_prefix = str(filename_prefix or "").strip()
    lora_name = str(lora_name or "").strip()
    controlnet_name = str(controlnet_name or "").strip()
    control_image = str(control_image or "").strip()
    sampler_name = str(sampler_name or "").strip()
    scheduler = str(scheduler or "").strip()

    if not prompt:
        raise ValueError("prompt is required")
    if not checkpoint:
        raise ValueError("checkpoint is required")
    if not filename_prefix:
        raise ValueError("filename_prefix is required")
    if not sampler_name or not scheduler:
        raise ValueError("sampler_name and scheduler are required")
    if not 0 <= int(seed) <= MAX_SEED:
        raise ValueError("seed is outside the ComfyUI range")
    if int(steps) < 1:
        raise ValueError("steps must be at least 1")
    if float(cfg) <= 0:
        raise ValueError("cfg must be greater than 0")
    if not 0 <= float(denoise) <= 1:
        raise ValueError("denoise must be between 0 and 1")
    if bool(controlnet_name) != bool(control_image):
        raise ValueError("controlnet_name and control_image must be configured together")
    if controlnet_name:
        if float(control_strength) < 0:
            raise ValueError("control_strength must not be negative")
        if not 0 <= float(control_start) < float(control_end) <= 1:
            raise ValueError("ControlNet start and end must satisfy 0 <= start < end <= 1")

    width, height = parse_image_size(image_size)
    graph = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
            "_meta": {"title": "Checkpoint"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["1", 1]},
            "_meta": {"title": "Positive Prompt", "comic_pipeline_role": "positive_prompt"},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": str(negative_prompt or "").strip(), "clip": ["1", 1]},
            "_meta": {"title": "Negative Prompt", "comic_pipeline_role": "negative_prompt"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "_meta": {"title": "Canvas"},
        },
        "9": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed),
                "steps": int(steps),
                "cfg": float(cfg),
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": float(denoise),
                "model": ["1", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
            "_meta": {"title": "Sampler"},
        },
        "10": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["9", 0], "vae": ["1", 2]},
            "_meta": {"title": "Decode"},
        },
        "11": {
            "class_type": "SaveImage",
            "inputs": {"images": ["10", 0], "filename_prefix": filename_prefix},
            "_meta": {"title": "Save Comic Image"},
        },
    }

    if lora_name:
        graph["2"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "lora_name": lora_name,
                "strength_model": float(lora_strength_model),
                "strength_clip": float(lora_strength_clip),
            },
            "_meta": {"title": "LoRA"},
        }
        graph["3"]["inputs"]["clip"] = ["2", 1]
        graph["4"]["inputs"]["clip"] = ["2", 1]
        graph["9"]["inputs"]["model"] = ["2", 0]

    if controlnet_name:
        graph["6"] = {
            "class_type": "LoadImage",
            "inputs": {"image": control_image},
            "_meta": {
                "title": "Control Image",
                "comic_pipeline_reference_path": str(control_source or ""),
            },
        }
        graph["7"] = {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": controlnet_name},
            "_meta": {"title": "ControlNet"},
        }
        graph["8"] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["3", 0],
                "negative": ["4", 0],
                "control_net": ["7", 0],
                "image": ["6", 0],
                "strength": float(control_strength),
                "start_percent": float(control_start),
                "end_percent": float(control_end),
            },
            "_meta": {"title": "Apply ControlNet"},
        }
        graph["9"]["inputs"]["positive"] = ["8", 0]
        graph["9"]["inputs"]["negative"] = ["8", 1]

    return {"client_id": str(client_id or "codex-comic-local"), "prompt": graph}


def required_node_types(workflow: dict) -> set[str]:
    return {
        str(node.get("class_type"))
        for node in (workflow.get("prompt") or {}).values()
        if isinstance(node, dict) and node.get("class_type")
    }


def set_workflow_prompts(workflow: dict, prompt: str, negative_prompt: str) -> bool:
    changed = False
    for node in (workflow.get("prompt") or {}).values():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        role = (node.get("_meta") or {}).get("comic_pipeline_role")
        if role == "positive_prompt":
            node.setdefault("inputs", {})["text"] = str(prompt or "").strip()
            changed = True
        elif role == "negative_prompt":
            node.setdefault("inputs", {})["text"] = str(negative_prompt or "").strip()
            changed = True
    return changed


def write_local_workflow(request_path: str | Path, output_path: str | Path) -> Path:
    request = json.loads(Path(request_path).read_text(encoding="utf-8-sig"))
    workflow = build_local_image_workflow(**request)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a ComfyUI API-format comic workflow from JSON request data.")
    parser.add_argument("--request-path", required=True)
    parser.add_argument("--output-path", required=True)
    args = parser.parse_args()
    write_local_workflow(args.request_path, args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
