# Android coordinate workflow

## Observe

- Fix the intended ADB serial and foreground package before interacting. Call the current `android_ui_snapshot`; keep its `snapshot_id`, original PNG width/height, screenshot path, and candidate list together.
- Match a unique enabled clickable node by exact text, content description, or resource ID when the app exposes useful nodes. Use the node's bounds/candidate ID rather than reading coordinates from a rendered screenshot.
- If the tree contains only a zero-size root such as `[0,0][0,0]` and no useful descendants (common in self-drawn surfaces), treat the tree as unavailable. Do not keep calling text lookup; use the fresh screenshot.

## Map and click

- A coordinate from memory, a previous attempt, or an attached/old screenshot is never directly actionable. At most use it to know where to inspect; re-identify the visible target on the current snapshot, then map that point. Do not issue `adb shell input tap` or a guessed coordinate as a shortcut when the guarded UI click tool is available.
- Screenshot points are in the image coordinate space. For a resized full-screen display point `(x, y)`, pass the displayed content width/height and the same snapshot ID to `android_ui_map_point`; pass crop bounds only when the screenshot is cropped. Use the returned original-device point, never a point retyped as a guessed device coordinate.
- For a prepared crop, use `android_ui_prepare_vision` and `android_ui_map_prepared_point`; do not add crop offsets by hand.
- Call `android_ui_click` with that same snapshot ID and candidate ID or mapped point. Do not fall back to raw `adb input tap` when the guarded click tool is available.
- If a stale snapshot or changed UI is rejected, no tap should be treated as completed. Capture a new snapshot and relocate.

## Verify and recover

- Inspect the fresh screenshot returned after the click and compare it with the intended state. A tree may remain empty or unchanged while a self-drawn dialog appears; `ui_tree_changed: false` is not a click verdict.
- If the click response contains no fresh image, call `android_ui_snapshot` before claiming success, failure, or selecting the next control. Do not replace screenshot verification with another coordinate guess.
- A command result such as `input_sent: true` proves input was issued, not that the target action completed. Verify the new screen or application state.
- If Android refuses injection, preserve the exact permission error. On a user-authorized rooted device, check `su` availability and use the guarded tool's root option only when needed. Do not fabricate a successful touch.
- One action per snapshot. After an uncertain result, refresh and diagnose why the target did not activate (wrong mapping, stale frame, overlay, or target misidentification); retry once only if a fresh frame independently confirms a newly mapped target. Stop before any unintended send/share/confirmation step.
