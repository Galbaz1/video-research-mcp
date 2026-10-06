# Temporal OCR evidence

`video_ocr_timeline` reads one local video at 1–6 explicitly selected source times. Supply its SHA-256 and choose the existing `vision` or `tesseract` backend. The result retains raw OCR, original decoded-frame timestamps, crop/resize transforms, coordinates and artifact commitments for every requested point, including failures and skipped points.

For numeric evidence, select a crop containing only one plain decimal line and set `track_numbers: true`. Adjacent decreases are uncertain OCR candidates, with timestamps and raw evidence references. They are not verified application bugs. Missing, ambiguous or unsupported tokens remain visible. Sparse sampling cannot establish continuous or transient-state coverage.

The request uses one 300-second deadline and an 8 MiB aggregate artifact budget. `max_pixels` affects conservative per-point reservation; a large reservation can leave later points explicitly unrun even when compressed artifacts are small. Select a crop/resize and a pixel ceiling appropriate to the requested points. Cleanup failures are returned separately and do not replace the primary error or cancellation. A missing backend stops further dispatch; there is no model fallback or automatic retry.

An optional `transcript` must be an existing `audio_transcribe` `readback` request for the identical path and source SHA-256, with its receipt digest. This tool does not run ASR. Caption assertions, inferred word/speaker timings and observed OCR remain separate in the response.

Source qualification: R87 has 59 owned tests and 161 affected passes for its original source. Root added two cleanup/deadline regressions, reproduced both failures and verified the minimal repair. The unit tests patch native boundaries and exercise real artifact, clock and coordinate handling. Actual native OCR accuracy and the four original programme acceptance clauses remain pending; implementation and discovery are not native acceptance.
