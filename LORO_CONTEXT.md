# LORO — Compact Context
> Cargar al inicio de cada sesión junto con CLAUDE.md.
> Última actualización: 2026-03-16 (sesión 17)

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
| `MAX_SEGMENT_STALENESS_SECONDS` | 1.0 | Descarta segmentos viejos antes de procesar |
| `REALTIME_TRANSCRIPTION_ENABLED` | 1 | Activa modo streaming palabra por palabra (BUG-24: falla por REALTIME_SESSION_MODEL incorrecto) |
| `REALTIME_SESSION_MODEL` | gpt-4o-mini-transcribe | ⚠️ INCORRECTO — debe ser `gpt-4o-realtime-preview` |
| `TRANSLATION_CONTEXT_TURNS` | 1 | Turnos de contexto pasados al modelo de traducción |
| `PREMIUM_TRIGGER_SCORE` | 1.5 | Score mínimo para usar modelo premium |
| `PREMIUM_MAX_RATIO` | 0.10 | Cap de segmentos premium por sesión (10%) |
| `FILTER_GIBBERISH` | 1 | Filtra transcripciones sin sentido |
| `DEBUG_MODE` | 1 | Logging verbose |

---

## 4. Estado actual — Mar 2026 (sesión 17)

**Progreso:** 93% (F9 en curso, F10 pendiente)

| Área | Estado | Notas |
|------|--------|-------|
| Audio capture | ✅ Estable | BlackHole requerido en macOS. VAD disponible (VAD_ENABLED=1) |
| STT batch | ✅ Estable | 0.0% issue rate, 0 drops en Run 5 y Run 6. avg latencia STT ~0.8s |
| STT realtime | 🔴 BUG-24 | Fix de protocolo aplicado (transcription_session.update ✅). Pendiente: REALTIME_SESSION_MODEL debe ser gpt-4o-realtime-preview |
| Traducción | ✅ Estable | gpt-4o-mini. TRANSLATION_CONTEXT_TURNS=1 (3→1 reduce repetición de contexto) |
| Overlay UI | ✅ Estable | Modo cinema/list. Siempre on-top, draggable |
| macOS cocoa plugin | ✅ Resuelto | xattr quarantine + codesign en main.py y run.sh |
| Latencia end-to-end | ✅ Medida (Run 6) | avg=2.04s, p50=1.73s, p95=3.26s, max=3.40s |
| Stale drops (emit) | 🟡 4 por sesión | age_s>3.51s en chunks lentos. Fix: subir STALE_EMIT_RELAX_FACTOR 1.17→1.35 |
| Premium ratio | 🟡 13.5% (cap 10%) | Cap no está funcionando correctamente. Pendiente revisar lógica |
| Chunk size | ✅ Fijo | CHUNK_SECONDS=1.8 (cap MAX_CHUNK_SECONDS_LIVE subido a 2.5) |
| Pipeline analytics | ✅ Disponible | parse_pipeline.py — breakdown por etapa, modo --compare |
| Packaging (PyInstaller) | ⬜ Pendiente | F07/F08 no iniciados |
| Monetización | ⬜ Pendiente | $15/mes + 7 días gratis, Dodo Payments |

---

## 5. Bugs abiertos por prioridad

### P0 — Bloqueante UX
| ID | Descripción | Estado |
|----|-------------|--------|
| BUG-24 | Realtime STT no funciona — `REALTIME_SESSION_MODEL=gpt-4o-mini-transcribe` inválido para el WebSocket realtime. Fix protocolo ya aplicado. Pendiente: cambiar a `gpt-4o-realtime-preview` en `.env` y validar | 🟡 Parcial |

### P1 — Importantes
| ID | Descripción | Archivo |
|----|-------------|---------|
| BUG-06 | Sin timeout en `Queue.get()` — workers se cuelgan si audio listener falla | `main.py` |
| BUG-08 | `except Exception` genérico oculta errores reales | `main.py` |
| BUG-09 | `full_transcript_buffer` sin lock — crash posible durante export | `overlay_ui.py` |
| BUG-25 | Premium ratio 13.5% ignora cap PREMIUM_MAX_RATIO=0.10 — revisar lógica | `main.py` |
| BUG-26 | 4 stale drops por sesión — STALE_EMIT_RELAX_FACTOR 1.17 muy ajustado | `main.py` |

### P2 — Código frágil
BUG-14 (memory leak deque), BUG-15 (None checks), BUG-16 (regex sin tests),
BUG-17 (contexto transcripción no se resetea), BUG-19 (load_dotenv sin manejo),
BUG-20 (estado corrupto en buffer), BUG-21 (target_language sin validar), BUG-22 (deps sin fijar)

### Resueltos en sesión 17
- ✅ BUG-24 (protocolo): `session.update` → `transcription_session.update` + payload correcto
- ✅ Chunk cap: `MAX_CHUNK_SECONDS_LIVE` 1.0→2.5 (ya no silencia CHUNK_SECONDS del .env)
- ✅ Contexto repetido en traducción: prompt con `[REFERENCE ONLY]` + rules 6/10 reforzadas
- ✅ Cocoa crash: xattr quarantine + codesign en main.py y run.sh
- ✅ Stale threshold: `STALE_EMIT_RELAX_FACTOR` 1.5→1.17

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

1. **BUG-24 final** — cambiar `REALTIME_SESSION_MODEL=gpt-4o-realtime-preview` en `.env`, probar Run 7 con realtime activado
2. **BUG-25** — revisar lógica de cap premium en `main.py` (13.5% > 10%)
3. **BUG-26** — subir `STALE_EMIT_RELAX_FACTOR` 1.17→1.35 para eliminar stale drops en chunks lentos
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
