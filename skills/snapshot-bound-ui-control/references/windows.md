# Windows screenshot and OCR workflow

- Capture a fresh screenshot and record its actual capture bounds plus `DisplayInventory` geometry. Do not query UIA/accessibility trees to locate visible controls.
- For a text target, run `screen_ocr` on the exact screenshot and inspect its recognized text, confidence, bounding box, image dimensions, and coordinate-space label. If the OCR call errors, report a tool failure rather than saying it found no text.
- Match the requested label using nearby context and require one usable box. Map the center from that same screenshot/crop through the desktop coordinate tool. Keep image pixels, physical desktop coordinates, logical coordinates, DPI scaling, crop offsets, and multi-monitor origins distinct.
- For symbols, use CPU geometric-symbol or observed CPU-template matching on the same screenshot. General vision is only a fallback after OCR and CPU matching cannot identify the target.
- Make one guarded click or keypress, then capture a new screenshot and verify the requested state. A successful input return is not task success.
- If the user takes control of mouse/keyboard, stop input and reobserve only after control is available. On ambiguity, stale image, or missing map metadata, do not guess; refresh and diagnose. Retry at most once from a newly observed target.
