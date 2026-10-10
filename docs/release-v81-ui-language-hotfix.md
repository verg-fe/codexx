# MyCodex v81 source hotfix: English planning and live screenshot control

This source-only hotfix keeps the v81 runtime identity and adds current-frame UI observation and language guidance.

- Internal planning is directed to English; user-facing communication remains Chinese.
- Screen actions require a fresh live screenshot for the current turn. Android text is identified with CPU OCR on that same frame; symbols use CPU matching. Coordinates are mapped from the same snapshot and verified with a new screenshot.
- Stale images, tree-first visible-control lookup, raw ADB taps and repeated use of a plan after user correction are prohibited.
- The canonical UI skill and Android/Windows references are mirrored in both the published skills catalog and bundled src/skills tree. Legacy Android/Frida UI text now points to the canonical workflow.
- Verification carried forward from the G-drive build report: source syntax passed; 23 focused unit tests passed; skill validation passed; Android MCP STDIO handshake passed with 16 tools. Live phone UI end-to-end testing was not run.

No executable or release asset is included in this source-only commit.