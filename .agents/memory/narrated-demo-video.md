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
7. Long ffmpeg builds: run with `nohup ... &` in the background and poll, since a
   single foreground bash call hits the 120s timeout.
