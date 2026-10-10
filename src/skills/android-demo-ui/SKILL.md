---
name: android-demo-ui
description: Android app development and runtime diagnostics with Frida or logs. Use snapshot-bound-ui-control for all visible screen reading and input.
---

# Android app development and runtime diagnostics

This legacy skill covers Android app behavior, Frida bridges, callbacks, and logs. It is not an authority for screen control. For every Android or Windows UI action, use the single canonical `snapshot-bound-ui-control` skill.

- The first UI observation in each turn must be a fresh screenshot of the live target. An old session image, a file found on disk, or remembered screen state is never proof of what is currently displayed.
- For visible text, run CPU OCR on that exact screenshot. For symbols, use CPU symbol/template matching. Map from that same frame and make one guarded click, then capture a new frame to verify.
- A user correction invalidates the pending plan: stop before another action, capture a fresh screen, and reassess. A chat/contact name is a visible label to find, not a request to search files or type into app search.
- On the user's authorized rooted Android device, all clicks use the guarded Android click tool with `use_root=true`. Never use raw `su`, `adb input`, `sendevent`, or guessed coordinates for UI control.
- Do not query accessibility trees or UIA trees to locate visible controls. Do not use the general vision model until CPU OCR and CPU symbol/template matching cannot identify the target.

For runtime diagnosis, verify the exact package, foreground process, PID, Frida client/server versions, and time-bounded logs. Preserve original listeners before temporary instrumentation and restore them on stop. Distinguish an input event, a visible state change, and the app's business callback; a successful command alone proves none of the latter two. Use the example assets only as implementation references, not as device/UI instructions.

For device-specific Frida bridge, hook, and callback details, consult `snapshot-bound-ui-control/references/android-app-debugging.md`. Do not follow older tree-first screen-control instructions in bundled legacy references.
