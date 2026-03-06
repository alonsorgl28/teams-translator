# Loro — Universal Real-Time Audio Translator

Traduce en vivo cualquier audio que puedas escuchar.

Loro es un MVP de escritorio que captura audio del sistema, lo transcribe, lo traduce en tiempo real y lo muestra en un overlay flotante.

- Funciona con cualquier app que reproduzca audio (Teams, Zoom, YouTube, reproductores locales, navegador).
- Muestra subtítulos en vivo y permite exportar la transcripción traducida.
- El modo técnico preserva números, unidades y acrónimos.

## Quick Start in 3 minutes

### Windows (VB-Cable)

1. Crea y activa un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Configura entorno:

```bash
cp .env.example .env
```

4. Define `OPENAI_API_KEY` en `.env`.
5. Instala VB-Cable.
6. En la app que quieras traducir, usa `CABLE Input` como salida de audio.
7. Ejecuta:

```bash
python main.py
```

### macOS (BlackHole)

1. Crea y activa un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Configura entorno:

```bash
cp .env.example .env
```

4. Define `OPENAI_API_KEY` en `.env`.
5. Instala BlackHole.
6. En Audio MIDI Setup, crea un Multi-Output Device (opcional pero recomendado).
7. En la app que quieras traducir, enruta salida a BlackHole (o al Multi-Output Device que incluya BlackHole).
8. Ejecuta:

```bash
python main.py
```

## Setup

1. Crea y activa un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Configura entorno:

```bash
cp .env.example .env
```

4. Define `OPENAI_API_KEY` en `.env`.
5. Opcional: configura `SYSTEM_AUDIO_DEVICE` para forzar un dispositivo de entrada virtual específico.

## Audio Routing (Universal System Audio)

### Windows (VB-Cable)

1. Instala VB-Cable.
2. Configura la salida de la app origen (ejemplo: Teams/Zoom/browser) en `CABLE Input`.
3. Verifica que Loro capture `CABLE Output` como entrada.

### macOS (BlackHole)

1. Instala BlackHole.
2. Crea un Multi-Output Device en Audio MIDI Setup (opcional, recomendado).
3. Configura la salida de la app origen hacia BlackHole (o el Multi-Output Device que incluya BlackHole).

El listener intenta detectar automáticamente dispositivos comunes (`CABLE Output`, `VB-Audio`, `BlackHole`) y falla al iniciar si no encuentra loopback válido, para evitar captura accidental del micrófono.

## Use cases

- Teams: traducción en vivo durante reuniones internas y con clientes.
- Zoom: subtítulos traducidos para llamadas internacionales.
- YouTube: seguimiento de contenido técnico en otros idiomas.

## Runtime Configuration (optional)

- `APP_BRAND_NAME` (default: `Loro`)
- `SOURCE_LANGUAGE` (default: `Auto-detect`)
- `TARGET_LANGUAGE` (default: `Spanish`)
- `SYSTEM_AUDIO_DEVICE` (optional device override)
- `SUBTITLE_MODE` (`cinema` or `list`)
- `SUBTITLE_UPDATE_MS`
- `LITERAL_COMPLETE_MODE`
- `TRANSCRIPTION_MODEL` / `TRANSCRIPTION_FALLBACK_MODEL`
- `TRANSLATION_MODEL` / `TRANSLATION_FALLBACK_MODEL`
- `TRANSLATION_MAX_TOKENS`
- `MAX_AUDIO_BACKLOG_BEFORE_SKIP` / `MAX_TEXT_BACKLOG_BEFORE_SKIP`
- `METRICS_ENABLED`, `METRICS_OUTPUT_PATH`, `METRICS_SUMMARY_PATH`

Referencia completa de defaults: revisa `/Users/hola/Documents/New project/.env.example`.

## Run

```bash
python main.py
```

### UI Preview (sin audio/API)

```bash
python main.py --preview-ui
```

## Roadmap

- v1: 6–10 languages + autodetect.
- v2: 60+ languages + dialect packs.

## Project Structure

- `/Users/hola/Documents/New project/audio_listener.py`
- `/Users/hola/Documents/New project/transcription_service.py`
- `/Users/hola/Documents/New project/translation_service.py`
- `/Users/hola/Documents/New project/overlay_ui.py`
- `/Users/hola/Documents/New project/main.py`
