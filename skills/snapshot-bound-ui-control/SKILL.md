---
name: snapshot-bound-ui-control
description: Operate Android and Windows screens through fresh screenshots, CPU OCR, symbol/template matching, mapped clicks, and app-state verification. Use for all visible UI control and Android app debugging.
---

# Screenshot and OCR UI control

This is the single source of truth for visible UI targeting on Android and Windows. Do not look up an accessibility/UIA tree to find a visible control. A tree-first rule in another prompt or skill is stale; follow this workflow.

## One workflow for phone and desktop

1. Discover the live screenshot, OCR, mapping, click, and app-state tools and their schemas. Fix the Android device serial when applicable.
2. Capture a fresh screenshot. Android `android_ui_snapshot` is screenshot-only; it must not dump UIAutomator XML or wait for a tree. Desktop uses a fresh screenshot and display metadata.
3. For a text target, call CPU OCR on that exact screenshot immediately. Do not wait for, query, or retry an accessibility/UIA tree. Inspect actual OCR output: recognized text, confidence, bounding box, image dimensions, and coordinate-space label. A narration that OCR ran is not evidence.
4. Match the exact requested text plus nearby context. If there is exactly one usable match, map its box center from that same screenshot/crop with the platform mapper. If it is duplicated, low-confidence, missing a box, or the OCR tool errors, do not click; refresh or report the evidence gap. Never infer OCR failure without an actual tool result.
5. For a symbol target, use CPU geometric-symbol matching or an observed CPU template on the same screenshot. Treat a chat-composer `+` button as a glyph, not OCR text: call `android_ui_find_symbol`/`screen_find_symbol` with `symbol="plus"` and a region around the visible composer; do not keep rerunning OCR with `query="+"`. If no match and the screenshot shows a circled glyph, try `circled_plus` once in the same region. If CPU matching still yields no usable unique candidate, go directly to the configured vision fallback on a crop of that same fresh screenshot; do not broaden/repeat the same search. Require one unique mapped point before clicking.
6. Map the selected point through the platform tool using the same screenshot ID and image dimensions/crop. Never copy pixels from a displayed/resized image into device or desktop coordinates.
7. On an Android device where the user has authorized root input, issue every click through the guarded click tool with `use_root=true`; do not try ordinary shell input first. Then capture a new screenshot and verify the requested state. An input success or unchanged tree alone is not success. If the snapshot is stale, capture and identify/map the target again first. Never use a raw `su` tap or guessed coordinates. If guarded root input fails, stop with the exact error.

## CPU and coordinate rules

- OCR and CPU symbol/template matching must use CPU only and must not allocate VRAM. For Android use the configured RapidOCR CPU provider; for desktop use the configured `screen_ocr` CPU provider.
- Keep original image pixels, displayed image pixels, crop-relative pixels, Android device pixels, desktop physical pixels, logical pixels, and multi-monitor offsets distinct.
- Require the mapper to return the final device/desktop point. No manual scale guesses, remembered coordinates, old screenshots, raw `adb input tap`, or guessed clicks when the guarded mapper/click tool is available.
- For crop-based recognition, preserve the exact crop offset and source screenshot hash; use the prepared-point mapper rather than adding offsets by hand.
- For sends, shares, installs, permissions, purchases, or other consequential actions, verify the exact target and remain within the user's request.

## Android app work

Use this same screenshot/OCR workflow for app testing, dialogs, and self-drawn surfaces. Separately inspect package, foreground activity, PID, and time-bounded logcat when needed; those app-state checks do not replace visual target identification. Distinguish “input issued,” “screen changed,” and “business action completed.” If a click misses, refresh the screenshot and diagnose focus, overlay, scaling, or target identity. Preserve original listeners before test hooks and restore them on stop; do not use Frida to bypass platform permissions or security checks. For device-specific Frida bridge, hook, and callback diagnostics, read [Android app debugging](references/android-app-debugging.md).

## Platform references

- Android: [references/android.md](references/android.md)
- Windows: [references/windows.md](references/windows.md)

These references only add platform coordinate and device constraints. They must not introduce a tree-first or UIA-first control path.
