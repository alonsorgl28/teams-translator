# Teams Real-Time Translator (Desktop MVP)

Local desktop MVP that captures system audio from a Microsoft Teams meeting, transcribes it, translates it into Spanish, and displays it in a floating overlay.

## Implemented Requirements

- System audio capture in 3-second async chunks (`audio_listener.py`)
- Cross-platform virtual device support:
  - Windows: VB-Cable
  - macOS: BlackHole
- Whisper-based STT with automatic language detection (`transcription_service.py`)
- Translation to Spanish with technical-domain constraints and numeric-token preservation (`translation_service.py`)
- Floating semi-transparent overlay with:
  - dark gray background at ~70% opacity
  - white text
  - auto-scroll
  - last 10 translated segments
  - draggable, always-on-top window
  - adjustable font size
  - hide/show overlay content toggle
- Interaction controls:
  - Start/Stop listening
  - Copy full transcript
  - Export transcript to `.txt`
  - Clear screen
- Memory and storage behavior:
  - 60-minute rolling in-memory buffer
  - no raw audio persisted
  - translated text is persisted only when `Save Session` is enabled
- Async architecture with bounded queue to keep latency near the 6s target

## Project Structure

- `/Users/hola/Documents/New project/audio_listener.py`
- `/Users/hola/Documents/New project/transcription_service.py`
- `/Users/hola/Documents/New project/translation_service.py`
- `/Users/hola/Documents/New project/overlay_ui.py`
- `/Users/hola/Documents/New project/main.py`

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment:

```bash
cp .env.example .env
```

4. Set `OPENAI_API_KEY` in `.env`.
5. Optional: set `SYSTEM_AUDIO_DEVICE` to force a specific virtual audio input device name.

### Runtime Configuration (optional)

- `LOG_LEVEL` (default: `INFO`)
  - Controls application log verbosity.
  - Valid values include standard Python levels (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- `FULL_TRANSCRIPT_MAX_SEGMENTS` (default: `500`)
  - Maximum number of translated segments retained in the UI full transcript buffer.
  - Older entries are discarded first when the limit is reached.
  - Recommended range: `200` to `2000` depending on session length and memory constraints.
- `AUDIO_MAX_BUFFER_SECONDS` (default: `12.0`)
  - Maximum in-memory audio backlog inside the capture listener before old samples are dropped.
  - Helps bound memory usage if upstream processing slows down.
  - Recommended range: `6.0` to `20.0` seconds.
- `LITERAL_COMPLETE_MODE` (default: `0`)
  - `0` prioritizes real-time visual updates (recommended for live meetings).
  - `1` prioritizes longer, more complete segments at the cost of latency.
- `APP_BRAND_NAME` (default: `Auralink`)
  - Visible product name in the overlay header and settings dialog.
- `SOURCE_LANGUAGE` (default: `Auto-detect`)
  - Initial source language shown in settings (`From`).
- `TARGET_LANGUAGE` (default: `Spanish`)
  - Initial target language shown in settings (`To`) and used by translation runtime.
- `SUBTITLE_MODE` (default: `cinema`)
  - `cinema` shows subtitle-style live lines while listening.
  - `list` keeps transcript lines visible while listening.
- `SUBTITLE_UPDATE_MS` (default sample: `220`)
  - Interval used to flush pending subtitle chunks into visible text.
  - Lower values feel faster; values too low can increase fragment noise.
- `TRANSCRIPTION_MODEL` (default in sample `.env`: `gpt-4o-mini-transcribe`)
  - Primary speech-to-text model.
  - If unavailable in your account/region, runtime falls back to `TRANSCRIPTION_FALLBACK_MODEL`.
- `TRANSCRIPTION_FALLBACK_MODEL` (default in sample `.env`: `whisper-1`)
  - Automatic fallback STT model when the primary model returns unsupported-model errors.
- `TRANSLATION_MODEL` (default in sample `.env`: `gpt-4o-mini`)
  - Primary translation model (latency-first default).
  - Use `gpt-4o-mini` for lowest latency; switch to `gpt-4.1-mini` when quality is prioritized over speed.
- `TRANSLATION_FALLBACK_MODEL` (default in sample `.env`: `gpt-4.1-mini`)
  - Automatic fallback if the primary model fails with model/availability errors.
- `TRANSLATION_MAX_TOKENS` (default sample: `120`)
  - Hard cap for translation output tokens to reduce long run-on outputs and latency variance.
- `MAX_AUDIO_BACKLOG_BEFORE_SKIP` / `MAX_TEXT_BACKLOG_BEFORE_SKIP` (sample profile: `2`)
  - Drops old queued work when backlog grows, keeping visible output current.
- `MIN_EMIT_WORDS` (default: `3` in real-time mode)
  - Minimum words required before forced rendering of an unfinished fragment.
  - Helps avoid one-word lines like `You`, `Open`, `Model`.
- `MAX_PENDING_RENDER_AGE_SECONDS` (default: `1.4`, sample profile: `1.2`)
  - Hard cap on how long a pending fragment can wait before being rendered.
  - Increase slightly if you prefer smoother, longer subtitle lines.
- `MAX_SEGMENT_STALENESS_SECONDS` (default: `3.0` in realtime mode, `8.0` in literal mode)
  - Drops segments that are already too old before render to avoid delayed subtitle bursts.
  - Lower values prioritize sync-to-now; higher values prioritize completeness.
- `TRANSLATION_CONTEXT_ENABLED` (default sample: `1`)
  - Enables short text context across translation calls.
- `TRANSLATION_CONTEXT_TURNS` (default sample: `2`)
  - Number of recent source/translation turns carried into the prompt.
- `TRANSLATION_CONTEXT_MAX_CHARS` (default sample: `160`)
  - Hard cap for context text injected in each translation request.
- `TRANSLATION_GLOSSARY_ENABLED` (default sample: `0`)
  - Enables/disables dynamic term glossary accumulation (can increase prompt size/latency when enabled).
- `METRICS_ENABLED` (default: `1`)
  - Enables session metrics collection (JSONL events + summary output).
- `METRICS_OUTPUT_PATH` (default: `./reports/session_metrics.jsonl`)
  - JSONL event stream with per-segment timing and pipeline error records.
- `METRICS_SUMMARY_PATH` (default: `./reports/session_summary.json`)
  - Session-level aggregate metrics (`avg`, `p50`, `p95`, `max`, issue rate).
- `METRICS_MIN_TEXT_LEN` (default: `8`)
  - Minimum emitted segment length required to include it in metric logs.
- `METRICS_APPEND_MODE` (default: `0`)
  - `0` starts a fresh JSONL file each session.
  - `1` appends events across sessions.
- `TRANSCRIPTION_LANGUAGE_HINT` (default: `auto`)
  - Optional STT language hint (e.g. `en`) to reduce wrong-language detections.
- `TRANSCRIPTION_CONTEXT_ENABLED` (default: `0`)
  - Enables short rolling prompt context between chunks.
- `TRANSCRIPTION_CONTEXT_MAX_CHARS` (default: `220`)
  - Max prompt context length when rolling context is enabled.

## Audio Routing

### Windows (VB-Cable)

1. Install VB-Cable.
2. Set Teams output device to `CABLE Input`.
3. Ensure the app captures `CABLE Output` as input.

### macOS (BlackHole)

1. Install BlackHole.
2. Create a Multi-Output Device (optional but recommended) in Audio MIDI Setup.
3. Set Teams output to BlackHole (or the Multi-Output Device including BlackHole).

The listener attempts automatic matching (`CABLE Output`, `VB-Audio`, `BlackHole`) and intentionally fails startup if no valid loopback device is detected, to avoid microphone capture by mistake.

## Run

```bash
python main.py
```

### UI Preview (sin audio/API)

Para probar solo el diseño de la interfaz con subtítulos simulados:

```bash
python main.py --preview-ui
```

## Notes

- Language detection is automatic; required languages (English, Portuguese, Mandarin Chinese, Hindi) are supported by Whisper models.
- Translation prompt enforces technical terminology and formal engineering/procurement tone.
- Numeric tokens are validated and re-checked to reduce accidental number/unit changes.
- Session metrics files are created under `./reports/` by default when metrics are enabled.
