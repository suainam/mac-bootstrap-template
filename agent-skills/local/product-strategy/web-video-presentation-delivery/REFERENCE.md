# Reference

## Stable commands

### HTTP service

```bash
cd "${PRODUCT_STRATEGY_DIR:-$HOME/work/projects/product_strategy}/catalogue/franchise_store"
python3 -m http.server 8787 --bind 127.0.0.1
```

### Open the OBS-ready player

```bash
cd "${PRODUCT_STRATEGY_DIR:-$HOME/work/projects/product_strategy}/catalogue/franchise_store"
./scripts/open_obs_player.sh
```

Or open manually:

```text
http://127.0.0.1:8787/tutorial_video_presentation_player.html?auto=1&obs=1&session=<timestamp>
```

## Existing script entrypoints

- storyboard build:
  - `scripts/build_storyboard_json.py`
  - `scripts/rewrite_storyboard_v3.py`
- TTS:
  - `scripts/mimo_tts_ch1.py`
  - `scripts/mimo_tts_step_clone.py`
- sankey asset:
  - `scripts/build_sankey_svg_aligned.py`

## Stable recording rules

- use `http://127.0.0.1`, never `file://`
- keep one player instance
- keep one playback entry
- prefer manual browser `Space` over scripted key injection
- verify OBS output file audio separately from browser playback

## Current audio caveat

On this machine, browser playback can be healthy while OBS output is silent.

If OBS only captures sound through `Global/扬声器`, it is recording the system mix, not isolated Chrome audio. That means:

- browser sound can be captured
- background system sounds can also leak in

If isolated browser-only capture becomes a recurring requirement, add BlackHole or an equivalent virtual audio device instead of inventing more player logic.

## Non-goals

Do not default to:

- frontend `MediaRecorder`
- `record=1` style self-recording UI
- `autostart_ms` as the main delivery path
- AppleScript-controlled formal recording
- multiple competing playback or recording modes
