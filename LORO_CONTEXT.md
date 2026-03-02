# LORO — Compact Context
> Cargar al inicio de cada sesión junto con CLAUDE.md.
> Última actualización: 2026-03-02

---

## 1. Qué es

Loro = overlay de subtítulos en tiempo real para cualquier audio del sistema.
Clon funcional de Seagull (getseagull.com). PyQt6 desktop, macOS + Windows.
Pipeline: captura audio del sistema → STT → traducción → overlay flotante.

---

## 2. Arquitectura

| Módulo | Responsabilidad | Líneas aprox. |
|--------|----------------|---------------|
| `audio_listener.py` | Captura chunks de audio del sistema via sounddevice. Requiere BlackHole (mac) / VB-Cable (win). | ~200 |
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
| `CHUNK_SECONDS` | 1.4 | Tamaño de chunk de audio en segundos |
| `CHUNK_STEP_SECONDS` | 0.8 | Paso entre chunks (overlap) |
| `MAX_SEGMENT_STALENESS_SECONDS` | 3.0 | Descarta segmentos viejos antes de procesar |
| `FILTER_GIBBERISH` | 1 | Filtra transcripciones sin sentido |
| `DEBUG_MODE` | 0 | Logging verbose |

---

## 4. Estado actual — Mar 2026

**Progreso:** 91% (F8–F9 en curso, F10 pendiente)

| Área | Estado | Notas |
|------|--------|-------|
| Audio capture | ✅ Estable | BlackHole requerido en macOS |
| STT | 🟡 Funciona pero batch | Streaming experimental, no default |
| Traducción | ✅ Estable | gpt-4o-mini, términos técnicos OK |
| Overlay UI | ✅ Estable | Inspirado en Seagull, modo cinema/list |
| Latencia primer subtítulo | 🔴 Alta | Cuello principal del pipeline |
| Packaging (PyInstaller) | ⬜ Pendiente | F07/F08 no iniciados |
| Monetización | ⬜ Pendiente | Pricing no decidido, sin Stripe |

---

## 5. Bugs abiertos por prioridad

### P1 — Importantes
| ID | Descripción | Archivo |
|----|-------------|---------|
| BUG-06 | Sin timeout en `Queue.get()` — workers se cuelgan si audio listener falla | `main.py:313,407` |
| BUG-07 | API key se valida tarde — error aparece al primer chunk, no al arrancar | `transcription_service.py:29` |
| BUG-08 | `except Exception` genérico oculta errores reales — debugging imposible | `main.py:264,380,484,533` |
| BUG-09 | `full_transcript_buffer` sin lock — crash posible durante export | `overlay_ui.py:304,340,361` |
| BUG-12 | `_list_audio_sources()` silencia todos los errores | `overlay_ui.py:859` |
| BUG-13 | Sin feedback visual si falta BlackHole/VB-Cable | `overlay_ui.py` (UX) |

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

1. **Testing macOS esta noche** — documentar bugs nuevos en `ALPHA/Loro/Backlog.md`
2. **BUG-13** — feedback visual cuando falta BlackHole (mayor impacto en UX de first-run)
3. **BUG-07** — validar API key al arrancar, no al primer chunk
4. **Latencia** — evaluar activar streaming STT como default (hoy experimental)
5. **F07** — packaging PyInstaller macOS para poder distribuir sin Python instalado

---

## 8. Cómo correr

```bash
cd "/Users/hola/Documents/New project"
source .venv/bin/activate   # si existe
pip install -r requirements.txt
python main.py
```

Prerequisito macOS: **BlackHole 2ch** instalado y configurado como output del sistema.
