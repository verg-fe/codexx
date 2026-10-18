"""One-image RapidOCR worker; receives one JSON request on stdin and emits one JSON record."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import time

MARKER = "MYCODEX_RAPIDOCR_JSON:"
MODEL_FILES = (
    "PP-OCRv6_det_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "PP-OCRv6_rec_small.onnx",
)

SYMBOLS = {"plus", "circled_plus", "ellipsis_horizontal", "ellipsis_vertical"}


def emit(value):
    # ASCII escaping keeps Chinese safe even when isolated Windows Python defaults to a legacy code page.
    print(MARKER + json.dumps(value, ensure_ascii=True, separators=(",", ":")), flush=True)


def _symbol_score(gray, edge, cx, cy, radius, ring=False):
    import cv2
    import numpy as np
    h, w = gray.shape
    if radius < 5:
        return 0.0
    if ring:
        angles = np.linspace(0, 2 * np.pi, 72, endpoint=False)
        hits = 0
        for angle in angles:
            x = int(round(cx + radius * np.cos(angle)))
            y = int(round(cy + radius * np.sin(angle)))
            y0, y1 = max(0, y - 2), min(h, y + 3)
            x0, x1 = max(0, x - 2), min(w, x + 3)
            if y0 < y1 and x0 < x1 and int(edge[y0:y1, x0:x1].max()) > 0:
                hits += 1
        ring_score = hits / len(angles)
    else:
        ring_score = 0.0
    contrasts = []
    extent = max(5, int(radius * 0.36))
    inner = max(2, int(radius * 0.12))
    for axis in (0, 1):
        for t in range(-extent, extent + 1, max(1, int(radius / 15))):
            if abs(t) < inner:
                continue
            if axis == 0:
                x, y = cx + t, cy
                side = [(x, y - max(3, int(radius * .14))), (x, y + max(3, int(radius * .14)))]
            else:
                x, y = cx, cy + t
                side = [(x - max(3, int(radius * .14)), y), (x + max(3, int(radius * .14)), y)]
            if not (1 <= x < w - 1 and 1 <= y < h - 1):
                continue
            a, b = side
            if not (0 <= a[0] < w and 0 <= a[1] < h and 0 <= b[0] < w and 0 <= b[1] < h):
                continue
            center = float(gray[y - 1:y + 2, x - 1:x + 2].mean())
            surround = (float(gray[a[1] - 1:a[1] + 2, a[0] - 1:a[0] + 2].mean()) +
                        float(gray[b[1] - 1:b[1] + 2, b[0] - 1:b[0] + 2].mean())) / 2
            contrasts.append(min(1.0, abs(center - surround) / 128.0))
    cross_score = float(np.mean(contrasts)) if contrasts else 0.0
    return (0.38 * ring_score + 0.62 * cross_score) if ring else cross_score


def _find_geometric_symbol(gray, symbol, region, min_score):
    import cv2
    import numpy as np
    cv2.setNumThreads(2)
    cv2.ocl.setUseOpenCL(False)
    height, width = gray.shape
    if region is None:
        left, top, right, bottom = 0, 0, width, height
    else:
        left, top, right, bottom = region
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError("region must be inside the image in original-image pixels.")
    roi = gray[top:bottom, left:right]
    if min(roi.shape) < 24:
        raise ValueError("Symbol-search region is too small.")
    blur = cv2.medianBlur(roi, 5)
    edges = cv2.Canny(blur, 45, 135)
    candidates = []
    if symbol in {"plus", "circled_plus"}:
        circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2,
            minDist=max(14, min(roi.shape) // 45), param1=120, param2=18,
            minRadius=6, maxRadius=max(12, min(120, min(roi.shape) // 2)))
        if circles is not None:
            for fx, fy, fr in circles[0]:
                cx, cy, radius = int(round(fx)), int(round(fy)), int(round(fr))
                score = _symbol_score(roi, edges, cx, cy, radius, ring=(symbol == "circled_plus"))
                if score >= min_score:
                    candidates.append((score, cx, cy, radius))
        if symbol == "plus":
            line_length = max(7, min(roi.shape) // 12)
            for binary in (cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
                           cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]):
                horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (line_length, 1)))
                vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (1, line_length)))
                crossings = cv2.bitwise_and(horizontal, vertical)
                count, labels, stats, centroids = cv2.connectedComponentsWithStats(crossings, 8)
                for i in range(1, count):
                    x, y, bw, bh, area = map(int, stats[i])
                    if area < 2 or bw > line_length or bh > line_length: continue
                    cx, cy = int(round(centroids[i][0])), int(round(centroids[i][1]))
                    radius = max(8, line_length)
                    score = _symbol_score(roi, edges, cx, cy, radius)
                    if score >= min_score: candidates.append((score, cx, cy, radius))
    else:
        # Three compact connected components in a row/column are the CPU shape cue for an ellipsis.
        threshold_modes = [cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
                           cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
        blobs = []
        min_area = max(2, int(min(roi.shape) ** 2 * .000002))
        max_area = max(40, int(min(roi.shape) ** 2 * .006))
        max_blob_dim = max(5, min(roi.shape) // 30)
        for binary in threshold_modes:
            count, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
            for i in range(1, count):
                x, y, bw, bh, area = map(int, stats[i])
                if min_area <= area <= max_area and 1 <= bw <= max_blob_dim and 1 <= bh <= max_blob_dim:
                    blobs.append((float(centroids[i][0]), float(centroids[i][1]), bw, bh))
        unique = []
        for item in blobs:
            if not any(np.hypot(item[0]-v[0], item[1]-v[1]) < 3 for v in unique): unique.append(item)
        vertical = symbol == "ellipsis_vertical"
        align_tol = max(3, min(roi.shape) * .004)
        for i, a in enumerate(unique):
            for j in range(i + 1, len(unique)):
                b = unique[j]
                for k in range(j + 1, len(unique)):
                    c = unique[k]
                    vals = sorted((a, b, c), key=lambda z: z[1] if vertical else z[0])
                    primary = [v[1] if vertical else v[0] for v in vals]
                    orth = [v[0] if vertical else v[1] for v in vals]
                    gaps = [primary[1]-primary[0], primary[2]-primary[1]]
                    if min(gaps) < 2 or max(gaps)/min(gaps) > 1.8 or max(orth)-min(orth) > align_tol: continue
                    cx = int(round(sum(v[0] for v in vals)/3)); cy = int(round(sum(v[1] for v in vals)/3))
                    score = max(0.0, 1.0 - (max(orth)-min(orth))/max(align_tol,1) - abs(gaps[0]-gaps[1])/max(gaps))
                    if score >= min_score: candidates.append((score, cx, cy, int(round(max(gaps)/2))))
    # Merge duplicate scale/line responses around one glyph, retaining the strongest response.
    candidates.sort(key=lambda item: item[0], reverse=True)
    merged = []
    for score, cx, cy, radius in candidates:
        if any(np.hypot(cx-x, cy-y) < max(10, min(radius, rr) * .65) for _, x, y, rr in merged):
            continue
        merged.append((score, cx, cy, radius))
    rows = []
    for score, cx, cy, radius in merged[:100]:
        r = max(5, int(radius))
        l, t, rr, b = max(0, left+cx-r), max(0, top+cy-r), min(width, left+cx+r), min(height, top+cy+r)
        rows.append({"symbol": symbol, "bbox": [l, t, rr, b], "center": [left+cx, top+cy],
                     "score": round(float(score), 5), "coordinate_space": "original_image_pixels"})
    return rows


def _find_template_matches(gray, template, threshold):
    import cv2
    import numpy as np
    cv2.setNumThreads(2)
    cv2.ocl.setUseOpenCL(False)
    image_h, image_w = gray.shape
    base_h, base_w = template.shape
    if min(base_h, base_w) < 8 or max(base_h, base_w) > 512 or template.std() < 4:
        raise ValueError("Icon template must be 8-512 pixels and contain visible contrast.")
    candidates = []
    for scale in (0.8, 1.0, 1.2):
        width = max(8, int(round(base_w * scale)))
        height = max(8, int(round(base_h * scale)))
        if width > image_w or height > image_h:
            continue
        probe = template if scale == 1.0 else cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        scores = cv2.matchTemplate(gray, probe, cv2.TM_CCOEFF_NORMED)
        for _ in range(21):
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if not math.isfinite(score) or score < threshold:
                break
            row = {"bounds": [int(x), int(y), int(x + width), int(y + height)],
                   "center": [int(x + width // 2), int(y + height // 2)],
                   "score": round(float(score), 5), "scale": scale,
                   "coordinate_space": "original_image_pixels"}
            candidates.append(row)
            # Suppress this local peak so the next iteration can find another instance.
            y0, y1 = max(0, y - height // 2), min(scores.shape[0], y + height // 2 + 1)
            x0, x1 = max(0, x - width // 2), min(scores.shape[1], x + width // 2 + 1)
            scores[y0:y1, x0:x1] = -1
    candidates.sort(key=lambda row: row["score"], reverse=True)
    merged = []
    for row in candidates:
        cx, cy = row["center"]
        w, h = row["bounds"][2] - row["bounds"][0], row["bounds"][3] - row["bounds"][1]
        duplicate = False
        for existing in merged:
            ex, ey = existing["center"]
            ew = existing["bounds"][2] - existing["bounds"][0]
            eh = existing["bounds"][3] - existing["bounds"][1]
            if abs(cx - ex) < max(4, min(w, ew) // 2) and abs(cy - ey) < max(4, min(h, eh) // 2):
                duplicate = True
                break
        if not duplicate:
            merged.append(row)
    return merged[:20], len(merged) > 20


def main():
    payload = json.load(sys.stdin)
    path = Path(payload["image_path"]).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Image missing or larger than 50 MiB.")
    from PIL import Image
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        if width < 2 or height < 2 or width * height > 25_000_000:
            raise ValueError("Image dimensions are outside the supported limit.")
        if payload.get("expected_size") and list(image.size) != payload["expected_size"]:
            raise ValueError("Image dimensions changed after snapshot capture.")
        if image.format not in {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}:
            raise ValueError("Unsupported image encoding.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != payload.get("expected_sha256"):
        raise ValueError("Image SHA256 changed before inference.")

    if payload.get("operation") == "find_symbol":
        symbol = payload.get("symbol")
        if symbol not in SYMBOLS:
            raise ValueError("Unsupported geometric symbol.")
        import cv2
        cv2.setNumThreads(2)
        cv2.ocl.setUseOpenCL(False)
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None or list(gray.shape[::-1]) != [width, height]:
            raise ValueError("OpenCV could not read the verified image dimensions.")
        began = time.perf_counter()
        matches = _find_geometric_symbol(gray, symbol, payload.get("region"), float(payload.get("min_score", .75)))
        emit({"ok": True, "operation": "find_symbol", "symbol": symbol, "image_size": [width, height],
              "matches": matches, "match_count": len(matches), "unique": len(matches) == 1,
              "inference_ms": round((time.perf_counter()-began)*1000, 1),
              "runtime": "OpenCV CPU; OpenCL disabled"})
        return

    if payload.get("operation") == "find_template":
        template_path = Path(payload["template_path"]).resolve(strict=True)
        if not template_path.is_file() or template_path.suffix.lower() != ".png" or template_path.stat().st_size > 5 * 1024 * 1024:
            raise ValueError("Icon template must be a PNG no larger than 5 MiB.")
        template_digest = hashlib.sha256(template_path.read_bytes()).hexdigest()
        if template_digest != payload.get("template_sha256"):
            raise ValueError("Icon template changed before inference.")
        with Image.open(template_path) as icon:
            icon.load()
            tw, th = icon.size
            if tw < 8 or th < 8 or max(tw, th) > 512:
                raise ValueError("Icon template dimensions are outside the supported 8-512 pixel range.")
        import cv2
        import numpy as np
        cv2.setNumThreads(2)
        cv2.ocl.setUseOpenCL(False)
        gray = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
        template = cv2.imdecode(np.frombuffer(template_path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None or template is None or list(gray.shape[::-1]) != [width, height]:
            raise ValueError("CPU matcher could not decode the verified screenshot or icon template.")
        threshold = float(payload.get("threshold", .92))
        if not math.isfinite(threshold) or not .75 <= threshold <= 1:
            raise ValueError("Template threshold must be between 0.75 and 1.")
        began = time.perf_counter()
        matches, truncated = _find_template_matches(gray, template, threshold)
        emit({"ok": True, "operation": "find_template", "image_size": [width, height],
              "matches": matches, "match_count": len(matches), "unique": len(matches) == 1,
              "truncated": truncated, "inference_ms": round((time.perf_counter()-began)*1000, 1),
              "runtime": "OpenCV CPU; OpenCL disabled"})
        return

    import rapidocr
    model_dir = Path(rapidocr.__file__).resolve().parent / "models"
    missing = [name for name in MODEL_FILES if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError("Installed local OCR model assets are missing: " + ", ".join(missing))

    from rapidocr import RapidOCR
    # Disable all optional accelerators explicitly; do not compete with the user's GPU workload.
    cpu_params = {
        "Global.log_level": "error",
        "Global.model_root_dir": str(model_dir),
        "EngineConfig.onnxruntime.use_cuda": False,
        "EngineConfig.onnxruntime.use_dml": False,
        "EngineConfig.onnxruntime.use_cann": False,
        "EngineConfig.onnxruntime.use_coreml": False,
        "EngineConfig.onnxruntime.intra_op_num_threads": 4,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    }
    engine = RapidOCR(params=cpu_params)
    began = time.perf_counter()
    output = engine(str(path))
    elapsed_ms = round((time.perf_counter() - began) * 1000, 1)
    text_query = payload.get("query", "")
    match_mode = payload.get("match_mode", "contains")
    threshold = float(payload.get("min_confidence", 0.35))
    limit = int(payload.get("limit", 80))
    rows = []
    all_count = 0
    for quad, text, score in zip(output.boxes, output.txts, output.scores):
        text = str(text)
        confidence = float(score)
        if not math.isfinite(confidence) or confidence < threshold:
            continue
        if text_query and not (text == text_query if match_mode == "exact" else text_query in text):
            continue
        points = [[float(point[0]), float(point[1])] for point in quad]
        left = max(0, math.floor(min(point[0] for point in points)))
        top = max(0, math.floor(min(point[1] for point in points)))
        right = min(width, math.ceil(max(point[0] for point in points)))
        bottom = min(height, math.ceil(max(point[1] for point in points)))
        if right <= left or bottom <= top:
            continue
        center = [max(0, min(width - 1, round(sum(p[0] for p in points) / len(points)))),
                  max(0, min(height - 1, round(sum(p[1] for p in points) / len(points))))]
        all_count += 1
        rows.append({"text": text, "confidence": round(confidence, 5),
                     "bbox": [left, top, right, bottom], "center": center,
                     "quad": [[round(x, 2), round(y, 2)] for x, y in points],
                     "coordinate_space": "original_image_pixels"})
    rows.sort(key=lambda row: (row["bbox"][1], row["bbox"][0]))

    providers = []
    for component_name in ("text_det", "text_cls", "text_rec"):
        component = getattr(engine, component_name, None)
        session = getattr(getattr(component, "session", None), "session", None)
        if session is not None:
            providers.extend(session.get_providers())
    providers = sorted(set(providers))
    if providers and providers != ["CPUExecutionProvider"]:
        raise RuntimeError("OCR session did not stay CPU-only: " + repr(providers))
    emit({"ok": True, "image_size": [width, height], "matches": rows[:limit],
          "match_count": all_count, "truncated": all_count > limit,
          "inference_ms": elapsed_ms, "providers": providers or ["CPUExecutionProvider"]})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        raise SystemExit(2)
