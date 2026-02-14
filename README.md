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

## Notes

- Language detection is automatic; required languages (English, Portuguese, Mandarin Chinese, Hindi) are supported by Whisper models.
- Translation prompt enforces technical terminology and formal engineering/procurement tone.
- Numeric tokens are validated and re-checked to reduce accidental number/unit changes.
