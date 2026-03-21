# LORO — Compact Context
> Cargar al inicio de cada sesión junto con CLAUDE.md.
> Última actualización: 2026-03-21 (sesión 22)

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
| `transcription_service.py` | STT via OpenAI. Primario: `gpt-4o-mini-transcribe`. Fallback: `whisper-1`. Batch (activo) + Realtime (BUG-24 pendiente modelo). | ~480 |
| `translation_service.py` | Traducción via `gpt-4o-mini`. Prompt simplificado (5 reglas). Context window corto (TURNS=0). | ~300 |
| `overlay_ui.py` | PyQt6. Dos modos: `cinema` (subtítulos grandes) y `list` (scroll). Always-on-top, draggable, resize. Meeting Mode button + summary label. | ~1080 |
| `main.py` | Orquestación async (qasync). Dedup, rolling buffer 60min, control de backlog, métricas. Meeting Mode bypass. | ~640 |
| `native_vibrancy.py` | Inyecta NSVisualEffectView en macOS via pyobjc (material HUD, corner_radius 22). | ~115 |
| `config_utils.py` | Helpers para leer variables de entorno con tipos. | ~50 |
| `metrics_reporter.py` | Guarda métricas por segmento en JSONL + resumen JSON. | ~150 |

---

## 3. Variables de entorno clave

| Variable | Valor actual (.env) | Qué controla |
|----------|---------------------|-------------|
| `OPENAI_API_KEY` | — | Requerida. STT + traducción. |
| `SYSTEM_AUDIO_DEVICE` | BlackHole 2ch | Nombre del dispositivo loopback |
| `SUBTITLE_MODE` | cinema | `cinema` (2 líneas grandes) o `list` (scroll) |
| `TRANSCRIPTION_MODEL` | gpt-4o-mini-transcribe | Modelo STT primario (batch) |
| `TRANSLATION_MODEL` | gpt-4o-mini | Modelo de traducción |
| `VAD_ENABLED` | 0 | Activar segmentación por voz (Silero VAD) |
| `CHUNK_SECONDS` | 1.8 | Tamaño de chunk de audio en segundos |
| `CHUNK_STEP_SECONDS` | 1.8 | Paso entre chunks (sin overlap actualmente) |
| `MAX_SEGMENT_STALENESS_SECONDS` | 1.5 | Descarta segmentos viejos antes de procesar (subido de 1.0 en sesión #18) |
| `REALTIME_TRANSCRIPTION_ENABLED` | **0** | Desactivado — SDK instalado tiene bug con `connect()`. No reactivar hasta resolver versión. |
| `REALTIME_SESSION_MODEL` | gpt-4o-mini-transcribe | Modelo para Realtime API (cuando se reactive). |
| `TRANSLATION_MAX_TOKENS` | **120** | Subido de 80 en sesión 21. El inglés→español expande ~15-20%; 80 tokens cortaba frases largas. |
| `TRANSLATION_CONTEXT_TURNS` | **0** | ⚠️ MANTENER EN 0. Con valor 1-2, gpt-4o-mini incluye historial completo en output (ghost translations). No es problema de prompt — es comportamiento del modelo. No reactivar. |
| `PREMIUM_TRIGGER_SCORE` | 1.5 | Score mínimo para usar modelo premium |
| `PREMIUM_MAX_RATIO` | 0.10 | Cap de segmentos premium por sesión (10%) |
| `FILTER_GIBBERISH` | 1 | Filtra transcripciones sin sentido |
| `DEBUG_MODE` | 1 | Logging verbose |

---

## 4. Estado actual — Mar 2026 (sesión 21) — BASE: RUN 11, MEJORAS DE CALIDAD PENDIENTES VALIDACIÓN

**Progreso:** 93% (F9 en curso, F10 pendiente)

| Área | Estado | Notas |
|------|--------|-------|
| Audio capture | ✅ Estable | BlackHole requerido en macOS. VAD disponible (VAD_ENABLED=1) |
| STT batch | ✅ Estable | Run 11: avg=2.81s, p95=3.94s, issue_rate=0% |
| STT realtime | ⬜ Desactivado | BUG-24 — SDK bug. Batch suficiente. Latencia ~2.5-4s es floor arquitectural con batch. |
| Traducción | 🟡 Validación pendiente | Prompt simplificado 10→5 reglas (s21). MAX_TOKENS 80→120 (s21). Run 12 pendiente. |
| Overlay UI | ✅ Estable + Meeting Mode | Meeting Mode (MM-01/02): bypass traducción, STT directo, timestamps relativos, summary. |
| macOS vibrancy | ✅ Implementado | `native_vibrancy.py` — NSVisualEffectView HUD via pyobjc (sesión 21, Claude paralelo). |
| macOS cocoa plugin | ✅ Resuelto definitivo | PyQt6 pineado a 6.7.1. run.sh tiene auto-repair. |
| Latencia end-to-end | ✅ Medida (Run 11) | avg=2.81s, p50=3.16s, p95=3.94s. Floor ~2.5s con batch STT. |
| Stale drops (emit) | 🟢 Mitigado | STALE_EMIT_RELAX_FACTOR=1.55 (threshold ~4.65s) |
| Premium ratio | ✅ Cap corregido | `_select_route` — cap siempre gana sobre force_premium |
| Worker stability | ✅ Estable | Queue.get() con timeout 5s. Exception logging correcto. |
| Pipeline analytics | ✅ Disponible | parse_pipeline.py — breakdown por etapa, modo --compare |
| Packaging (PyInstaller) | ⬜ Pendiente | F07/F08 no iniciados |
| Monetización | ⬜ Pendiente | $15/mes + 7 días gratis, Dodo Payments |

---

## 5. Bugs abiertos por prioridad

### P0 — Bloqueante UX
| ID | Descripción | Estado |
|----|-------------|--------|
| BUG-24 | Realtime STT — SDK bug con `connect()`. **Desactivado en .env** (`REALTIME_TRANSCRIPTION_ENABLED=0`). No retomar hasta tener versión compatible del SDK. | ✅ Mitigado (desactivado) |

### P1 — Resueltos en sesión 19
- ✅ BUG-06: `Queue.get()` con `asyncio.wait_for(timeout=5s)` en todos los workers
- ✅ BUG-08: `except Exception` ahora loguea tipo+mensaje real
- ✅ BUG-09: `full_transcript_buffer` protegido con `threading.Lock()`
- ✅ BUG-25: `_select_route` — cap siempre gana sobre `force_premium`
- ✅ BUG-26: `STALE_EMIT_RELAX_FACTOR=1.55` en .env (threshold emit ~4.65s)

### P2 — Código frágil (pendientes)
BUG-16 (regex sin tests), BUG-20 (estado corrupto en buffer)

### Resueltos sesión 20 (este Claude — bugs P2)
- ✅ BUG-14: `RollingTranscriptBuffer._entries` — `maxlen=3600` (cap seguridad + time-pruning)
- ✅ BUG-15: assert al inicio de worker loops, removidos `# type: ignore[union-attr]`
- ✅ BUG-17: `reset_context()` resetea `_active_model_index=0` + `buffer.clear()` en cambio de idioma
- ✅ BUG-19: `load_dotenv()` envuelto en `try/except` (bundle + local)
- ✅ BUG-21: `TARGET_LANGUAGE` validado contra set de idiomas conocidos, fallback a "Spanish"
- ✅ BUG-22: `requirements.txt` — upper bounds en todas las deps (`<2.0.0`, `<3.0.0`, etc.)
- ✅ F06: confirmado — código ya estaba limpio, sin referencias a "Teams Translator" en `.py`

### Resueltos sesiones 17-19
- ✅ BUG-24 (protocolo): `session.update` → `transcription_session.update` (s17)
- ✅ BUG-24 (modelo): removido de `connect()`, timeout 5s (s19)
- ✅ BUG-06/08/09: queue timeout, exception logging, transcript lock (s19)
- ✅ BUG-25/26: premium cap + stale relax factor (s19)
- ✅ Chunk cap: `MAX_CHUNK_SECONDS_LIVE` 1.0→2.5 (s17)
- ✅ Cocoa crash: PyQt6 pineado 6.7.1, xattr+codesign en run.sh (s17/18)
- ✅ "Claude Code" protegido de traducción (s19)

---

## 6. Features pendientes (en orden)

**Semana 1:**
- F01 `schema.py` — tipos Session, Segment, SessionStats
- F02 Audio device selector en UI con medidor de nivel
- F04/F05 Export TXT + SRT con timestamps
- ~~F06 Rebrand strings~~ ✅ Código limpio (solo queda nombre repo GitHub)

**Semana 2:**
- F07/F08 Build PyInstaller macOS + Windows
- F09 README "Quick Start 3 minutos"
- F11 Test E2E smoke

**Monetización:**
- M01 Decisión pricing
- M02/M03 Stripe setup + integración

---

## 7. Próximos pasos inmediatos

1. **Run 12** — validar prompt simplificado + MAX_TOKENS=120: ¿menos frases cortadas? ¿mejor fluidez?
2. **BUG-16** — regex sin tests: agregar cobertura en `translation_service.py`
3. **BUG-20** — estado corrupto en buffer: investigar y fijar
4. **Meeting Mode** — validar en uso real (commit e8986e5 en rama `codex/rebrand-to-loro`)
5. **F07/F08** — packaging PyInstaller macOS + Windows

> ⚠️ TRANSLATION_CONTEXT_TURNS=1 — descartado. El ghost translation es comportamiento del modelo gpt-4o-mini, no un problema de prompt. No reintentar.

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
