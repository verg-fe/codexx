# Windows desktop coordinate workflow

- Start with the actual `windows_desktop` tool list and schemas. Use `Snapshot`/UIA for a unique named control; use `Screenshot` for custom-drawn content or when the control tree is insufficient.
- Expired snapshot IDs and control IDs are invalid. Make a real fresh tool call before any subsequent action; do not keep using the old frame after saying “refresh”.
- For screenshot clicks, obtain the screenshot's real capture bounds and `DisplayInventory`. Keep image pixels, crop offsets, physical desktop coordinates, virtual-screen origins, DPI scaling, and logical click coordinates separate. Map through an available coordinate tool with the matching frame; if required metadata is missing, stop rather than guess.
- Make one click/keypress per observation, then capture the new screen and verify the target state. `ui_tree_changed: false` or a successful input return is not sufficient by itself.
- On an uncertain result, reobserve and diagnose focus, occlusion, window, display, and scaling. Retry at most once from a fresh confirmed target; stop if still ambiguous.
- If the user takes control of the mouse/keyboard, stop input and wait until control is available before taking a new observation.