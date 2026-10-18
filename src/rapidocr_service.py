"""Local CPU-only RapidOCR bridge. All installed files and caches live on G:."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

PYTHON = Path(r"G:\LocalCodex\tools\rapidocr-mcp-venv\Scripts\python.exe")
TEMP = Path(r"G:\LocalCodex\tmp\rapidocr")
WORKER = Path(__file__).resolve().parent / "tools" / "rapidocr_bridge.py"
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MARKER = "MYCODEX_RAPIDOCR_JSON:"


def recognize(image_path: str, query: str = "", match_mode: str = "contains",
              min_confidence: float = 0.35, limit: int = 80,
              expected_sha256: str | None = None,
              expected_size: tuple[int, int] | None = None) -> dict:
    path = Path(image_path).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        raise ValueError("OCR only accepts an existing supported image file.")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 50 MiB OCR limit.")
    if match_mode not in {"contains", "exact"}:
        raise ValueError("match_mode must be contains or exact.")
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("query must be text of at most 200 characters.")
    if isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float)) or not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 120:
        raise ValueError("limit must be between 1 and 120.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError("The image changed after its snapshot was captured; take a fresh snapshot.")

    TEMP.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"TEMP": str(TEMP), "TMP": str(TEMP), "PYTHONUTF8": "1", "CUDA_VISIBLE_DEVICES": ""})
    payload = {
        "image_path": str(path), "expected_sha256": digest,
        "expected_size": list(expected_size) if expected_size else None,
        "query": query, "match_mode": match_mode,
        "min_confidence": float(min_confidence), "limit": limit,
    }
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(PYTHON), "-I", str(WORKER)], input=json.dumps(payload, ensure_ascii=True),
            text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=45, cwd=str(TEMP), env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("RapidOCR exceeded its 45 second CPU limit.") from exc
    if completed.returncode:
        detail = completed.stderr.strip()[-1200:] or completed.stdout.strip()[-1200:]
        raise RuntimeError("RapidOCR worker failed: " + detail)
    rows = [line[len(MARKER):] for line in completed.stdout.splitlines() if line.startswith(MARKER)]
    if not rows:
        detail = completed.stderr.strip()[-1200:] or completed.stdout.strip()[-1200:]
        raise RuntimeError("RapidOCR returned no structured result: " + detail)
    result = json.loads(rows[-1])
    if not result.get("ok"):
        raise RuntimeError("RapidOCR: " + str(result.get("error", "unknown error"))[:1200])
    result.pop("ok", None)
    result["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result["engine"] = "RapidOCR 3.10.0 / ONNX Runtime CPUExecutionProvider"
    result["source_sha256"] = digest
    return result


SYMBOLS = {"plus", "circled_plus", "ellipsis_horizontal", "ellipsis_vertical"}


def find_symbol(image_path: str, symbol: str, region: list[int] | None = None,
                min_score: float = 0.75, expected_sha256: str | None = None,
                expected_size: tuple[int, int] | None = None) -> dict:
    """Find common geometric UI glyphs on CPU; return original-image bounds only."""
    path = Path(image_path).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        raise ValueError("Symbol search only accepts an existing supported image file.")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 50 MiB symbol-search limit.")
    if symbol not in SYMBOLS:
        raise ValueError("Unsupported geometric symbol. Supported: " + ", ".join(sorted(SYMBOLS)))
    if isinstance(min_score, bool) or not isinstance(min_score, (int, float)) or not math.isfinite(min_score) or not 0.2 <= min_score <= 1:
        raise ValueError("min_score must be between 0.2 and 1.")
    if region is not None and (not isinstance(region, list) or len(region) != 4 or any(type(v) is not int for v in region)):
        raise ValueError("region must be four integer original-image pixel bounds.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError("The image changed after its snapshot was captured; take a fresh snapshot.")
    TEMP.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"TEMP": str(TEMP), "TMP": str(TEMP), "PYTHONUTF8": "1", "CUDA_VISIBLE_DEVICES": ""})
    payload = {"operation": "find_symbol", "image_path": str(path), "expected_sha256": digest,
               "expected_size": list(expected_size) if expected_size else None,
               "symbol": symbol, "region": region, "min_score": float(min_score)}
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(PYTHON), "-I", str(WORKER)], input=json.dumps(payload, ensure_ascii=True),
            text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=30, cwd=str(TEMP), env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("CPU symbol search exceeded its 30 second limit.") from exc
    if completed.returncode:
        detail = completed.stderr.strip()[-1200:] or completed.stdout.strip()[-1200:]
        raise RuntimeError("CPU symbol worker failed: " + detail)
    rows = [line[len(MARKER):] for line in completed.stdout.splitlines() if line.startswith(MARKER)]
    if not rows:
        detail = completed.stderr.strip()[-1200:] or completed.stdout.strip()[-1200:]
        raise RuntimeError("CPU symbol search returned no structured result: " + detail)
    result = json.loads(rows[-1])
    if not result.get("ok"):
        raise RuntimeError("CPU symbol search: " + str(result.get("error", "unknown error"))[:1200])
    result.pop("ok", None)
    result["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result["engine"] = "OpenCV CPU geometric glyph matcher"
    result["source_sha256"] = digest
    return result


def find_template(image_path: str, template_path: str, threshold: float = 0.92,
                  expected_sha256: str | None = None,
                  expected_size: tuple[int, int] | None = None) -> dict:
    """Run snapshot-bound CPU template matching in the pinned G: Python environment."""
    path = Path(image_path).expanduser().resolve(strict=True)
    template = Path(template_path).expanduser().resolve(strict=True)
    jobs = Path(r"G:\LocalCodex\android-ui-jobs").resolve()
    if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        raise ValueError("Template matching requires a supported screenshot image.")
    if not template.is_file() or not template.is_relative_to(jobs) or template.suffix.lower() != ".png":
        raise ValueError("Use a PNG icon template saved under G:/LocalCodex/android-ui-jobs.")
    if path.stat().st_size > MAX_IMAGE_BYTES or template.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("Screenshot or icon template exceeds the supported size limit.")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0.75 <= threshold <= 1:
        raise ValueError("threshold must be between 0.75 and 1.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    template_digest = hashlib.sha256(template.read_bytes()).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError("The screenshot changed after its snapshot was captured; take a fresh snapshot.")
    TEMP.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"TEMP": str(TEMP), "TMP": str(TEMP), "PYTHONUTF8": "1", "CUDA_VISIBLE_DEVICES": ""})
    payload = {"operation": "find_template", "image_path": str(path),
               "expected_sha256": digest, "expected_size": list(expected_size) if expected_size else None,
               "template_path": str(template), "template_sha256": template_digest,
               "threshold": float(threshold)}
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(PYTHON), "-I", str(WORKER)], input=json.dumps(payload, ensure_ascii=True),
            text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=30, cwd=str(TEMP), env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("CPU template matching exceeded its 30 second limit.") from exc
    if completed.returncode:
        detail = completed.stderr.strip()[-1200:] or completed.stdout.strip()[-1200:]
        raise RuntimeError("CPU template worker failed: " + detail)
    rows = [line[len(MARKER):] for line in completed.stdout.splitlines() if line.startswith(MARKER)]
    if not rows:
        detail = completed.stderr.strip()[-1200:] or completed.stdout.strip()[-1200:]
        raise RuntimeError("CPU template matcher returned no structured result: " + detail)
    result = json.loads(rows[-1])
    if not result.get("ok"):
        raise RuntimeError("CPU template matcher: " + str(result.get("error", "unknown error"))[:1200])
    result.pop("ok", None)
    result["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result["engine"] = "OpenCV CPU template matcher / pinned G: Python"
    result["source_sha256"] = digest
    return result
