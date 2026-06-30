---
name: Narrated demo video workflow
description: How to build a 60-90s narrated product-demo video in this environment despite the 8s generateVideo cap.
---

# Building narrated product-demo videos

**Rule:** `generateVideo` (media-generation) is capped at 8 seconds, so it cannot
produce a 60-90s narrated walkthrough. Build the demo as a slideshow instead:
PIL slides + per-segment TTS + ffmpeg.

**Why:** A single long clip is impossible with the AI video tool, and AI-generated
video renders text unreliably. Self-rendered PIL slides give crisp, branded
captions and deterministic output.

**How to apply (the pipeline that worked):**
1. Write the narration as N short segments (one per slide). ~150 wpm; ~230 words ≈ 95s.
2. Render one PIL slide per segment (1920x1080). Bundled DejaVu fonts live at
   `<PIL pkg>/fonts/DejaVuSans*.ttf`. Crisp text, no AI image generation for text.
3. TTS each segment separately (`textToSpeech`), then `ffprobe` each for duration.
4. Per slide, make a still-image clip held for (segment_duration + ~0.6s) with
   `-c:v libx264 -preset ultrafast` (default preset times out the tool on 7 clips).
5. Pad each audio segment with matching trailing silence (`apad=pad_dur=`), concat
   audio and video separately, then mux. In the final mux use `-c:v copy` (do NOT
   re-encode the whole video — that is what blew the 120s tool timeout); only the
   audio mix is re-encoded.
6. Optional soft music bed: `generateMusic`, mix under narration at ~volume=0.10
   with a fade-out via `amix`.
7. Long ffmpeg builds: `nohup ... &` is unreliable (background procs die when the
   bash-tool shell exits). Instead run the build as a TEMPORARY console workflow
   (`configureWorkflow` outputType:"console", redirect to a log), poll the log /
   `getWorkflowStatus` until done, then `removeWorkflow`. ALWAYS write the final mux
   to a temp file and `mv` into place on success — a build killed at the 120s tool
   timeout mid-write leaves a corrupt "partial file" mp4 (ffprobe still reports a
   duration; only a full decode `ffmpeg -i x -f null -` exposes the NAL errors).

## Real moving app footage (not static screenshots)
**Rule:** To show REAL moving app footage, record the running app with Playwright
(`new_context(record_video_dir=...)` → .webm), serving un-gated `?cap=` views on a
SECOND temporary workflow/port so the gated live app on 5000 is untouched. Then in
the build, re-time each clip to its narration segment with ffmpeg `setpts=factor*PTS`
(factor=target/srcdur) — do NOT chase exact durations in the recorder (Playwright
webm duration is inflated by the scroll loop + IPC).
**Why:** User explicitly wanted live screen recordings, not Ken-Burns screenshots.
**How to apply:** warm-up pass (load view, wait render, fill @st.cache_data) then a
record pass so footage is fast/populated; skip warm-up for short static pages (login).
Heavy AI views (strategy/qc) paint blank for the first few seconds even after warm —
trim a lead-in (`-ss N` before `-i`) so the clip starts on real content. Scale to
`-2:1080` + white `pad` to 1920 (app bg is white, side bars blend). Record one view
per bash call (warm+record of 2 views exceeds 120s). Clean up after: delete the temp
recorder/capture scripts, remove the capture workflow, and uninstall recording-only
deps (playwright pip + chromium & its xorg/gtk nix libs) — none are needed at runtime.
