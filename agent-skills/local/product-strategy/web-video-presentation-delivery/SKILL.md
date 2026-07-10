---
name: web-video-presentation-delivery
description: "Delivers text-to-video work in this repo through one predictable path: script to storyboard, MiMo TTS assets, HTML player, and OBS-ready manual recording. Use when the user provides text, outline, article, or voiceover material and wants a web-video-presentation style video in this project."
---

# Web Video Presentation Delivery

Use this skill to keep text-to-video delivery in this repo on one **single-player** path.

## Quick start

Use this skill when the work includes:

- turning text, outline, article, or voiceover copy into a browser video presentation
- reusing the existing chapter HTML + player + MiMo TTS flow
- preparing an OBS-ready delivery path instead of inventing a new recording mechanism

Default output:

1. align the script and storyboard
2. generate or update TTS assets with existing scripts
3. update chapter HTML and the shared player only where needed
4. verify browser playback
5. hand off an OBS-ready manual recording path

## Workflow

### 1. Lock the single-player path

Before editing anything, keep these invariants:

- one shared player: `tutorial_video_presentation_player.html`
- one recording view: `?auto=1&obs=1`
- one manual playback entry: browser `Space`
- one external recorder: `OBS`

Do not add a second recording path unless the user explicitly asks for it.

### 2. Build or update the script assets

Prefer the existing repo flow:

- source copy:
  - `docs/scripts/tutorial_script.md`
  - `docs/scripts/voiceover_tts_script.md`
  - `docs/scripts/audio_storyboard.md`
- storyboard JSON:
  - `scripts/build_storyboard_json.py`
  - `scripts/rewrite_storyboard_v3.py`

If the user gives fresh text:

1. align it into chapter/step structure
2. update the markdown source of truth
3. rebuild storyboard JSON instead of hand-editing multiple downstream files

### 3. Reuse the current TTS pipeline

Use the existing MiMo scripts before inventing new synthesis glue:

- chapter prototype:
  - `scripts/mimo_tts_ch1.py`
- step-level clone synthesis:
  - `scripts/mimo_tts_step_clone.py`

Keep these conventions unless the user changes them:

- clone style stays conversational, not announcer-style
- step wav files stay under `audio/mimo_*`
- the player reads those existing step wav paths directly

### 4. Edit HTML chapters surgically

Touch only the files that actually need content or layout updates:

- `tutorial_video_presentation_ch1.html` ... `tutorial_video_presentation_ch7.html`
- `tutorial_video_presentation_player.html`

Keep the current player model:

- same-chapter step changes use `postMessage`
- chapter changes reload the iframe
- `obs=1` hides non-essential chrome
- manual `Space` start remains the stable route

Do not reintroduce:

- browser `MediaRecorder`
- `file://` recording workflows
- automatic AppleScript-driven start as the default path
- multiple competing start modes

### 5. Verify playback before talking about recording

Verification order:

1. browser playback works
2. audio plays in browser
3. step changes and chapter transitions stay in sync
4. `obs=1` view hides non-essential UI
5. only then move to OBS capture

If browser playback is broken, do not continue to OBS troubleshooting yet.

### 6. Record through OBS, manually

Stable path in this repo:

1. start local HTTP service
2. open `http://127.0.0.1:8787/tutorial_video_presentation_player.html?auto=1&obs=1&session=<timestamp>`
3. confirm OBS preview first
4. start OBS recording
5. manually press `Space` in the browser
6. verify the output file has audio

### 7. Finish with docs, not chat-only tribal knowledge

If the work changes the stable route:

- update `docs/video-recording-runbook.md`
- update `docs/video-recording-retrospective.md`
- update `video_presentation/README.md`
- update `.agents/README.md` if the reusable skill surface changed

## Deliverables

Return:

- updated file path(s)
- short summary of what changed
- any remaining recording or audio caveats

## Reference

See [REFERENCE.md](REFERENCE.md) for stable commands, non-goals, and repo-specific pitfalls.
