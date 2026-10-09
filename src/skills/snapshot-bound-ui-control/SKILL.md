---
name: snapshot-bound-ui-control
description: Use when operating Android or Windows application screens by accessibility tree, screenshot, UIA, or coordinates; especially when a snapshot is stale, resized, cropped, or the app draws its own controls.
---

# Snapshot-bound UI control

Tie every screen action to a fresh observation and its exact coordinate space. Read only the platform reference needed for the current task:

- Android phone or tablet: [references/android.md](references/android.md)
- Windows desktop: [references/windows.md](references/windows.md)

Core rules:

1. Discover the live observation and click tools and schemas. A sentence saying “I took a screenshot” or “I clicked” is not a tool call; invoke the actual tool and base the next step on its result.
2. Capture the current screen. An expired snapshot invalidates its coordinates, node IDs, and conclusions; take a real new snapshot before acting.
3. Prefer a unique live accessibility/UIA node. Treat empty or degenerate trees as unavailable and use the screenshot path for custom-drawn controls.
4. **Never click a remembered or guessed coordinate.** Coordinates from memory, an earlier turn, a pasted/old screenshot, or prior successful attempts are search hints only. Find the target again in the current live screenshot and map that point through the platform tool using the current snapshot ID. If the current frame or mapping tool is unavailable, do not click.
5. Keep original-image, displayed-image, crop, physical-screen, and logical-screen coordinates distinct. Use the platform's mapping tool with the same snapshot ID; do not manually reinterpret resized or cropped points as device coordinates.
6. Perform one action per observation, then inspect fresh visual evidence. A successful input call, unchanged accessibility tree, or `ui_tree_changed: false` alone does not establish whether the intended control was activated.
7. If the action result has no fresh screenshot, explicitly capture a new snapshot before evaluating success or choosing another target. After one failed/uncertain action, refresh and diagnose; allow at most one retry from a newly observed and independently mapped target, otherwise stop instead of guessing or looping.
8. For sends, shares, purchases, installs, permission grants, or other consequential controls, verify the exact target and remain within the user's requested scope.
