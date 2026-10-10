# Android screenshot and OCR workflow

- Pin the intended ADB serial and check the foreground package/activity when needed. Call `android_ui_snapshot` for a fresh original-size PNG; this tool must capture a screenshot only and must not invoke UIAutomator.
- For a text target, call `android_ui_ocr` on that exact `snapshot_id` before any visual model. Require returned text, confidence, bounding box, image dimensions, and coordinate-space label. A tool error is not an empty OCR result.
- Match exact text with nearby context and require one usable box. Map its center using `android_ui_map_point` with the same `snapshot_id`, screenshot dimensions, and crop. Never pass OCR pixels directly to ADB or a click tool.
- If OCR finds no usable text, use CPU geometric-symbol or observed CPU-template matching for an icon. General vision is the last fallback after these tools fail to identify the target.
- For an Android device where the user has authorized root input, call `android_ui_click` with `use_root=true` for every click; do not attempt ordinary shell input. Inspect its fresh screenshot and verify the requested state. An input return or unchanged accessibility data is not proof of success.
- Use package/activity/PID/logcat tools for app-state diagnosis, not to guess visible-control coordinates. If the target snapshot is stale, capture a fresh screenshot and rerun OCR/mapping before clicking. Never issue a raw `adb shell su -c 'input tap …'` or `sendevent` command. If root input is not authorized or the guarded root click fails, stop and report the exact error.
- A stale snapshot, ambiguous match, OCR error, or missing mapping means no click. After one uncertain action, refresh and diagnose; permit at most one retry from a newly identified target.
