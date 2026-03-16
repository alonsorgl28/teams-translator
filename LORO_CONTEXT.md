# LORO — Compact Context
> Cargar al inicio de cada sesión junto con CLAUDE.md.
> Última actualización: 2026-03-16

---

## 1. Qué es

Loro = overlay de subtítulos en tiempo real para cualquier audio del sistema.
Clon funcional de Seagull (getseagull.com). PyQt6 desktop, macOS + Windows.
Pipeline: captura audio del sistema → STT → traducción → overlay flotante.

---

## 2. Arquitectura

| Módulo | Responsabilidad | Líneas aprox. |
|--------|----------------|---------------|
| `audio_listener.py` | Captura chunks de audio del sistema via sounddevice. Soporta VAD (Silero) o chunks fijos. Requiere BlackHole (mac) / VB-Cable (win). | ~340 |
| `vad.py` | Voice Activity Detection con Silero VAD. Segmenta audio por boundaries de voz en vez de tiempo fijo. | ~170 |
| `transcription_service.py` | STT via OpenAI. Primario: `gpt-4o-mini-transcribe`. Fallback: `whisper-1`. Batch + experimental streaming. | ~250 |
| `translation_service.py` | Traducción via `gpt-4o-mini`. Preserva términos técnicos y números. Context window corto. | ~300 |
| `overlay_ui.py` | PyQt6. Dos modos: `cinema` (subtítulos grandes) y `list` (scroll). Always-on-top, draggable, resize. | ~900 |
| `main.py` | Orquestación async (qasync). Dedup, rolling buffer 60min, control de backlog, métricas. | ~600 |
| `config_utils.py` | Helpers para leer variables de entorno con tipos. | ~50 |
| `metrics_reporter.py` | Guarda métricas por segmento en JSONL + resumen JSON. | ~150 |

---

## 3. Variables de entorno clave

| Variable | Default | Qué controla |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Requerida. STT + traducción. |
| `SYSTEM_AUDIO_DEVICE` | auto | Nombre del dispositivo loopback (BlackHole 2ch / CABLE Output) |
| `SUBTITLE_MODE` | cinema | `cinema` (2 líneas grandes) o `list` (scroll) |
| `TRANSCRIPTION_MODEL` | gpt-4o-mini-transcribe | Modelo STT primario |
| `TRANSLATION_MODEL` | gpt-4o-mini | Modelo de traducción |
| `VAD_ENABLED` | 0 | Activar segmentación por voz (Silero VAD) en vez de chunks fijos |
| `CHUNK_SECONDS` | 1.4 | Tamaño de chunk de audio en segundos (solo si VAD_ENABLED=0) |
| `CHUNK_STEP_SECONDS` | 0.8 | Paso entre chunks (overlap, solo si VAD_ENABLED=0) |
| `MAX_SEGMENT_STALENESS_SECONDS` | 3.0 | Descarta segmentos viejos antes de procesar |
| `FILTER_GIBBERISH` | 1 | Filtra transcripciones sin sentido |
| `DEBUG_MODE` | 0 | Logging verbose |

---

## 4. Estado actual — Mar 2026

**Progreso:** 92% (F8–F9 en curso, F10 pendiente)

| Área | Estado | Notas |
|------|--------|-------|
| Audio capture | ✅ Estable | BlackHole requerido en macOS. VAD disponible (VAD_ENABLED=1) |
| STT | 🟡 Streaming activado | REALTIME_TRANSCRIPTION_ENABLED=1, fallback a batch automático |
| Traducción | ✅ Estable | gpt-4o-mini, términos técnicos OK |
| Overlay UI | ✅ Estable | Inspirado en Seagull, modo cinema/list |
| macOS cocoa plugin | ✅ Resuelto | Fix en main.py: staging plugins Qt a /tmp (macOS Sequoia) |
| BUG-23 (mezcla idiomas) | 🟡 Parcial | VAD lo elimina pero añade latencia. Necesita instrumentación |
| Latencia primer subtítulo | ✅ Medida | avg=2.35s, P95=3.17s. STT es el cuello (53%). Datos en session_metrics.jsonl |
| Drop rate | ✅ Mejorado | SOURCE_COMMIT_MIN_CONFIDENCE bajado 0.39→0.28. 14/17 drops innecesarios rescatados |
| Pipeline analytics | ✅ Nuevo | parse_pipeline.py — breakdown por etapa, análisis de gaps, modo --compare |
| Packaging (PyInstaller) | ⬜ Pendiente | F07/F08 no iniciados |
| Monetización | ⬜ Pendiente | $15/mes + 7 días gratis, Dodo Payments |

---

## 5. Bugs abiertos por prioridad

### P1 — Importantes
| ID | Descripción | Archivo |
|----|-------------|---------|
| BUG-06 | Sin timeout en `Queue.get()` — workers se cuelgan si audio listener falla | `main.py` |
| BUG-07 | ✅ RESUELTO | `validate_api_key()` en `transcription_service.py` + llamada en `main.py:start()` |
| BUG-08 | `except Exception` genérico oculta errores reales — debugging imposible | `main.py` |
| BUG-09 | `full_transcript_buffer` sin lock — crash posible durante export | `overlay_ui.py` |
| BUG-12 | `_list_audio_sources()` silencia todos los errores | `overlay_ui.py` |
| BUG-13 | ✅ RESUELTO | `show_error_dialog()` en `overlay_ui.py` + detección en `main.py:start()` |

### P2 — Código frágil
BUG-14 (memory leak deque), BUG-15 (None checks), BUG-16 (regex sin tests),
BUG-17 (contexto transcripción no se resetea), BUG-19 (load_dotenv sin manejo),
BUG-20 (estado corrupto en buffer), BUG-21 (target_language sin validar), BUG-22 (deps sin fijar)

---

## 6. Features pendientes (en orden)

**Semana 1:**
- F01 `schema.py` — tipos Session, Segment, SessionStats
- F02 Audio device selector en UI con medidor de nivel
- F04/F05 Export TXT + SRT con timestamps
- F06 Rebrand strings (ninguna referencia a "Teams Translator")

**Semana 2:**
- F07/F08 Build PyInstaller macOS + Windows
- F09 README "Quick Start 3 minutos"
- F11 Test E2E smoke

**Monetización:**
- M01 Decisión pricing
- M02/M03 Stripe setup + integración

---

## 7. Próximos pasos inmediatos

1. **Correr sesión real con nuevo threshold** — validar que el drop rate baja y no aparece basura visible en la UI
2. **Comparar VAD on vs off** — correr sesión con `VAD_ENABLED=1`, guardar JSONL, comparar con `python parse_pipeline.py --compare`
3. **BUG-23** — confirmar resolución con prueba instrumentada (VAD elimina mezcla de idiomas)
4. **BUG-06 / BUG-08 / BUG-09** — bugs P1 aún sin tocar
5. **F07** — packaging PyInstaller macOS

---

## 8. Cómo correr

```bash
loro
```
> Alias configurado en `~/.zshrc`. Equivale a:
> `source ~/loro-venv/bin/activate && cd "/Users/hola/Documents/New project" && python3.11 main.py`

**Prerequisitos macOS:**
- **BlackHole 2ch** instalado y configurado como output del sistema
- **Python 3.11 via Homebrew** (`/opt/homebrew/bin/python3.11`)
- **PyQt6 6.8.1** — pinado en `requirements.txt`
- **venv en `~/loro-venv`** — NO dentro del proyecto (el espacio en "New project" rompe pip)

**Si el venv se corrompe o hay que recrearlo:**
```bash
rm -rf ~/loro-venv
/opt/homebrew/bin/python3.11 -m venv ~/loro-venv
source ~/loro-venv/bin/activate
python3.11 -m pip install -r "/Users/hola/Documents/New project/requirements.txt"
```

**Analizar métricas de pipeline:**
```bash
cd "/Users/hola/Documents/New project" && python3.11 parse_pipeline.py
# Comparar dos sesiones:
python3.11 parse_pipeline.py --compare reports/sesion_a.jsonl reports/sesion_b.jsonl
```

> **Nota:** El fix de cocoa ya está integrado en main.py. No es necesario `install_name_tool` ni `codesign` manual.
