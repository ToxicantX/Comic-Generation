import argparse
import base64
import io
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image


SUPPORTED_BACKENDS = {"direct_api", "comfyui"}


def normalize_backend(value: str | None = None) -> str:
    backend = str(value or os.getenv("COMIC_PIPELINE_IMAGE_BACKEND") or "direct_api").strip().lower()
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError("COMIC_PIPELINE_IMAGE_BACKEND must be direct_api or comfyui")
    return backend


def read_env(path: str | Path | None) -> dict:
    candidate = Path(path) if path else None
    if not candidate or not candidate.is_file():
        return {}
    values = {}
    for line in candidate.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def image_config(inputs: dict, env_path: str | Path | None = None) -> dict:
    configured_path = env_path or os.getenv("COMIC_PIPELINE_IMAGE_ENV_PATH") or inputs.get("api_key_env_path")
    values = read_env(resolve_path(configured_path)) if configured_path else {}
    return {
        "api_key": (
            str(inputs.get("api_key") or "").strip()
            or os.getenv("COMIC_PIPELINE_IMAGE_API_KEY", "").strip()
            or values.get("OPENAI_API_KEY", "").strip()
            or os.getenv("OPENAI_API_KEY", "").strip()
        ),
        "base_url": (
            str(inputs.get("base_url") or "").strip()
            or os.getenv("COMIC_PIPELINE_IMAGE_BASE_URL", "").strip()
            or values.get("OPENAI_BASE_URL", "").strip()
            or os.getenv("OPENAI_BASE_URL", "").strip()
            or "https://api.openai.com"
        ).rstrip("/"),
        "env_path": str(configured_path or ""),
    }


def image_api_url(base_url: str, endpoint: str) -> str:
    base = str(base_url or "").rstrip("/")
    for suffix in ("/images/generations", "/images/edits"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    versioned_base = base if base.endswith("/v1") else f"{base}/v1"
    return f"{versioned_base}/{endpoint.lstrip('/')}"


def resolve_path(value: str | Path) -> Path:
    path = Path(str(value).strip().strip('"'))
    if path.is_file() or path.is_absolute():
        return path
    workspace = Path(os.getenv("COMIC_PIPELINE_WORKSPACE") or Path(__file__).resolve().parents[1])
    return workspace / path


def workflow_image_inputs(workflow: dict) -> dict:
    for node in (workflow.get("prompt") or {}).values():
        if isinstance(node, dict) and node.get("class_type") == "OpenAICompatibleImageGenerate":
            inputs = node.get("inputs") or {}
            if not isinstance(inputs, dict):
                break
            return dict(inputs)
    raise ValueError("workflow does not contain OpenAICompatibleImageGenerate")


def reference_paths(value: str) -> list[Path]:
    paths = []
    seen = set()
    for item in str(value or "").replace(";", "\n").splitlines():
        raw = item.strip().strip('"')
        if not raw:
            continue
        path = resolve_path(raw)
        normalized = str(path).lower()
        if normalized in seen:
            continue
        if not path.is_file():
            raise ValueError(f"reference image path does not exist: {raw}")
        seen.add(normalized)
        paths.append(path)
    if len(paths) > 16:
        raise ValueError("reference_image_paths supports at most 16 images")
    return paths


def should_fallback_from_edits(status: int, error_text: str) -> bool:
    if status in {404, 405}:
        return True
    if status not in {400, 415, 422}:
        return False
    text = str(error_text or "").lower()
    return "edit" in text and any(token in text for token in ("unsupported", "not supported", "unknown endpoint"))


def generate_from_workflow(
    workflow_path: str | Path,
    output_path: str | Path,
    *,
    env_path: str | Path | None = None,
    prompt_suffix: str = "",
    timeout: int = 600,
) -> dict:
    workflow_path = Path(workflow_path)
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".png":
        raise ValueError("direct image output path must be a PNG file")
    workflow = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
    inputs = workflow_image_inputs(workflow)
    config = image_config(inputs, env_path)
    if not config["api_key"]:
        raise ValueError("image API key is not configured")

    prompt = str(inputs.get("prompt") or "").strip()
    negative_prompt = str(inputs.get("negative_prompt") or "").strip()
    if negative_prompt:
        prompt += "\n\nAvoid: " + negative_prompt
    if prompt_suffix.strip():
        prompt += prompt_suffix
    request = {
        "model": str(inputs.get("model") or os.getenv("COMIC_PIPELINE_IMAGE_MODEL") or "gpt-image-2").strip(),
        "prompt": prompt,
        "size": str(inputs.get("size") or "1024x1536"),
        "quality": str(inputs.get("quality") or os.getenv("COMIC_PIPELINE_IMAGE_QUALITY") or "auto"),
        "n": 1,
        "response_format": "b64_json",
    }
    references = reference_paths(str(inputs.get("reference_image_paths") or ""))
    image_bytes, attempts = request_image(config, request, references, timeout)
    save_image(image_bytes, output_path)
    return {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "completed": True,
        "backend": "direct_api",
        "workflow_path": str(workflow_path),
        "output_path": str(output_path),
        "model": request["model"],
        "size": request["size"],
        "quality": request["quality"],
        "reference_count": len(references),
        "attempts": attempts,
    }


def request_image(config: dict, payload: dict, references: list[Path], timeout: int) -> tuple[bytes, list[dict]]:
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Accept": "application/json",
        "User-Agent": "ComicPipeline/2.0",
    }
    attempts = []
    response = None
    if references:
        response = post_multipart_with_rate_limit_retry(
            image_api_url(config["base_url"], "images/edits"),
            headers,
            payload,
            references,
            timeout,
            attempts,
            "multipart_edits",
        )
        if should_retry_edit_without_response_format(response[0], error_text(response[2])):
            fallback = dict(payload)
            fallback.pop("response_format", None)
            response = post_multipart_with_rate_limit_retry(
                image_api_url(config["base_url"], "images/edits"),
                headers,
                fallback,
                references,
                timeout,
                attempts,
                "multipart_edits_default",
            )
        if should_fallback_from_edits(response[0], error_text(response[2])):
            response = None

    if response is None:
        response = post_json_with_rate_limit_retry(
            image_api_url(config["base_url"], "images/generations"),
            headers,
            payload,
            timeout,
            attempts,
            "json_generation",
        )
        if should_retry_without_response_format(response[0], error_text(response[2])):
            fallback = dict(payload)
            fallback.pop("response_format", None)
            response = post_json_with_rate_limit_retry(
                image_api_url(config["base_url"], "images/generations"),
                headers,
                fallback,
                timeout,
                attempts,
                "json_generation_default",
            )

    status, _, body = response
    if status >= 400:
        raise RuntimeError(f"Image API error {status}: {error_text(body)}; attempts={attempts[-4:]}")
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Image API response was not JSON") from exc
    image_bytes = extract_image_bytes(data, timeout)
    if not image_bytes:
        raise RuntimeError(f"Image API response did not include usable image data: {response_shape(data)}")
    return image_bytes, attempts


def post_json_with_rate_limit_retry(
    url: str,
    headers: dict,
    payload: dict,
    timeout: int,
    attempts: list[dict],
    name: str,
) -> tuple[int, dict, bytes]:
    response = post_json(url, headers, payload, timeout)
    attempts.append(attempt_record(name, response))
    if response[0] != 429:
        return response
    time.sleep(rate_limit_delay(response[1]))
    response = post_json(url, headers, payload, timeout)
    attempts.append(attempt_record(f"{name}_rate_limit_retry", response))
    return response


def post_multipart_with_rate_limit_retry(
    url: str,
    headers: dict,
    payload: dict,
    references: list[Path],
    timeout: int,
    attempts: list[dict],
    name: str,
) -> tuple[int, dict, bytes]:
    response = post_multipart(url, headers, payload, references, timeout)
    attempts.append(attempt_record(name, response))
    if response[0] != 429:
        return response
    time.sleep(rate_limit_delay(response[1]))
    response = post_multipart(url, headers, payload, references, timeout)
    attempts.append(attempt_record(f"{name}_rate_limit_retry", response))
    return response


def rate_limit_delay(headers: dict) -> int:
    retry_after = str(headers.get("Retry-After") or headers.get("retry-after") or "").strip()
    try:
        return max(1, min(300, int(float(retry_after)) + 1))
    except (TypeError, ValueError):
        return 65


def post_json(url: str, headers: dict, payload: dict, timeout: int) -> tuple[int, dict, bytes]:
    request_headers = dict(headers)
    request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    return open_request(request, timeout)


def post_multipart(
    url: str,
    headers: dict,
    payload: dict,
    references: list[Path],
    timeout: int,
) -> tuple[int, dict, bytes]:
    boundary = f"comic-pipeline-{uuid.uuid4().hex}"
    chunks = []
    for key, value in payload.items():
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
            str(value).encode("utf-8"),
            b"\r\n",
        ])
    for path in references:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            path.read_bytes(),
            b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    request_headers = dict(headers)
    request_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    request = urllib.request.Request(url, data=b"".join(chunks), headers=request_headers, method="POST")
    return open_request(request, timeout)


def open_request(request: urllib.request.Request, timeout: int) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            return status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), dict(exc.headers or {}), exc.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"image API is unreachable: {exc.reason}") from exc


def should_retry_without_response_format(status: int, message: str) -> bool:
    if status not in {400, 415, 422}:
        return False
    text = str(message or "").lower()
    return any(token in text for token in ("response_format", "b64_json", "unsupported content type"))


def should_retry_edit_without_response_format(status: int, message: str) -> bool:
    if status not in {400, 415, 422}:
        return False
    text = str(message or "").lower()
    return "response_format" in text or "b64_json" in text


def attempt_record(name: str, response: tuple[int, dict, bytes]) -> dict:
    return {"name": name, "status": response[0], "error": error_text(response[2])[:240] if response[0] >= 400 else ""}


def error_text(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or error.get("code") or "")[:500]
        if isinstance(error, str):
            return error[:500]
    return response_shape(data)


def extract_image_bytes(data, timeout: int) -> bytes:
    for candidate in image_candidates(data):
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        value = candidate.strip()
        if value.startswith("data:image/"):
            value = value.split(",", 1)[-1]
        if value.startswith(("http://", "https://")):
            request = urllib.request.Request(value, headers={"User-Agent": "ComicPipeline/2.0"})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read()
            except (urllib.error.URLError, TimeoutError):
                continue
        try:
            decoded = base64.b64decode(value + "=" * (-len(value) % 4), validate=False)
        except (ValueError, TypeError):
            continue
        if decoded.startswith((b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8", b"BM")):
            return decoded
    return b""


def image_candidates(data):
    if isinstance(data, dict):
        for key in ("b64_json", "base64", "b64", "image", "image_base64", "url", "image_url"):
            yield data.get(key)
        for key in ("data", "output", "outputs", "images", "content", "result"):
            yield from image_candidates(data.get(key))
    elif isinstance(data, list):
        for item in data:
            yield from image_candidates(item)
    elif isinstance(data, str):
        yield data


def response_shape(data) -> str:
    if isinstance(data, dict):
        return f"top_keys={sorted(str(key) for key in data)[:12]}"
    if isinstance(data, list):
        return f"list_len={len(data)}"
    return f"type={type(data).__name__}"


def save_image(image_bytes: bytes, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.convert("RGB").save(temporary, format="PNG")
        temporary.replace(output_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one OpenAI-compatible image workflow directly.")
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--result-path", default="")
    parser.add_argument("--env-path", default="")
    parser.add_argument("--prompt-suffix-file", default="")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    result_path = Path(args.result_path) if args.result_path else None
    try:
        suffix = Path(args.prompt_suffix_file).read_text(encoding="utf-8-sig") if args.prompt_suffix_file else ""
        result = generate_from_workflow(
            args.workflow_path,
            args.output_path,
            env_path=args.env_path or None,
            prompt_suffix=suffix,
            timeout=max(1, args.timeout),
        )
        exit_code = 0
    except Exception as exc:
        result = {
            "updated": datetime.now().isoformat(timespec="seconds"),
            "completed": False,
            "backend": "direct_api",
            "workflow_path": args.workflow_path,
            "output_path": args.output_path,
            "error": str(exc),
        }
        exit_code = 1
    if result_path:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
