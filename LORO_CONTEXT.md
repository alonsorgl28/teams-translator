# LORO — Compact Context
> Cargar al inicio de cada sesión junto con CLAUDE.md.
> Última actualización: 2026-03-18 (sesión 19)

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
| `translation_service.py` | Traducción via `gpt-4o-mini`. Preserva términos técnicos y números. Context window corto. | ~300 |
| `overlay_ui.py` | PyQt6. Dos modos: `cinema` (subtítulos grandes) y `list` (scroll). Always-on-top, draggable, resize. | ~900 |
| `main.py` | Orquestación async (qasync). Dedup, rolling buffer 60min, control de backlog, métricas. | ~600 |
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
| `REALTIME_TRANSCRIPTION_ENABLED` | 1 | Activa modo streaming palabra por palabra |
| `REALTIME_SESSION_MODEL` | gpt-4o-mini-transcribe | ✅ CORRECTO — este ES el modelo para Realtime API transcription. `gpt-4o-realtime-preview` NO existe. |
| `TRANSLATION_CONTEXT_TURNS` | 2 | Turnos de contexto pasados al modelo de traducción (subido de 1 a 2 en sesión #18) |
| `PREMIUM_TRIGGER_SCORE` | 1.5 | Score mínimo para usar modelo premium |
| `PREMIUM_MAX_RATIO` | 0.10 | Cap de segmentos premium por sesión (10%) |
| `FILTER_GIBBERISH` | 1 | Filtra transcripciones sin sentido |
| `DEBUG_MODE` | 1 | Logging verbose |

---

## 4. Estado actual — Mar 2026 (sesión 19)

**Progreso:** 93% (F9 en curso, F10 pendiente)

| Área | Estado | Notas |
|------|--------|-------|
| Audio capture | ✅ Estable | BlackHole requerido en macOS. VAD disponible (VAD_ENABLED=1) |
| STT batch | ✅ Estable | Runs 7+8 ejecutados. avg=2.54s, p95=3.09s |
| STT realtime | 🟡 Run 9 pendiente | BUG-24 resuelto en código. Run 9 pendiente para verificar conexión WebSocket real. |
| Traducción | 🟡 Repeticiones | gpt-4o-mini. TURNS=2. Prompt mejorado. "Claude Code" protegido de traducción. |
| Overlay UI | ✅ Estable | Modo cinema/list. Siempre on-top, draggable. `full_transcript_buffer` con Lock. |
| macOS cocoa plugin | ✅ Resuelto definitivo | PyQt6 pineado a 6.7.1 (6.8.x rompe cocoa en Sequoia). run.sh tiene auto-repair. |
| Latencia end-to-end | ✅ Medida (Run 8) | avg=2.54s, p50=2.60s, p95=3.09s, max=3.34s |
| Stale drops (emit) | 🟢 Mitigado | STALE_EMIT_RELAX_FACTOR=1.55 en .env (threshold ~4.65s) |
| Premium ratio | ✅ Cap corregido | Lógica `_select_route` revisada — cap siempre gana sobre force_premium |
| Worker stability | ✅ Mejorado | Queue.get() con timeout 5s. Exceptions loguean tipo+mensaje real. |
| Segmentación | 🟡 Tuning en progreso | COMMIT_MIN_WORDS=7, MERGE_MAX_WORDS=32, MIN_EMIT_WORDS=6 |
| Pipeline analytics | ✅ Disponible | parse_pipeline.py — breakdown por etapa, modo --compare |
| Packaging (PyInstaller) | ⬜ Pendiente | F07/F08 no iniciados |
| Monetización | ⬜ Pendiente | $15/mes + 7 días gratis, Dodo Payments |
| Análisis competitivo | ✅ Hecho | `Loro/Competitive-Analysis.md` — Seagull, Wordly, JotMe, DeepL |

---

## 5. Bugs abiertos por prioridad

### P0 — Bloqueante UX
| ID | Descripción | Estado |
|----|-------------|--------|
| BUG-24 | Realtime STT — fix aplicado: modelo removido de `connect()`, va solo en `transcription_session.update`. Timeout 5s agregado. Run 10 pendiente para validar. | 🟡 Run 10 pendiente |

### P1 — Resueltos en sesión 19
- ✅ BUG-06: `Queue.get()` con `asyncio.wait_for(timeout=5s)` en todos los workers
- ✅ BUG-08: `except Exception` ahora loguea tipo+mensaje real
- ✅ BUG-09: `full_transcript_buffer` protegido con `threading.Lock()`
- ✅ BUG-25: `_select_route` — cap siempre gana sobre `force_premium`
- ✅ BUG-26: `STALE_EMIT_RELAX_FACTOR=1.55` en .env (threshold emit ~4.65s)

### P2 — Código frágil
BUG-14 (memory leak deque), BUG-15 (None checks), BUG-16 (regex sin tests),
BUG-17 (contexto transcripción no se resetea), BUG-19 (load_dotenv sin manejo),
BUG-20 (estado corrupto en buffer), BUG-21 (target_language sin validar), BUG-22 (deps sin fijar)

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

1. **BUG-24 Run 10** — ejecutar run real con realtime activado para validar WebSocket conecta correctamente
2. **BUG-P2** — revisar BUG-14..22 si queda capacidad (deque leak, None checks, regex sin tests)
3. **F07/F08** — packaging PyInstaller macOS + Windows (primer paso hacia distribución)
4. **F06** — rebrand: eliminar referencias a "Teams Translator" en strings de UI

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
