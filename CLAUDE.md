# CLAUDE.md — Loro (Translation Overlay)

> Leer este archivo al inicio de cada sesión antes de tocar cualquier código.
> Producto: clon funcional de Seagull (getseagull.com) — subtítulos en tiempo real para cualquier app.
> Última actualización: 2026-03-02

---

## Identidad del proyecto

**Loro** = overlay de traducción en tiempo real para cualquier audio del sistema.
Inspirado en Seagull: limpio, minimal, sin setup, always-on-top.
Repo local: `/Users/hola/Documents/New project/`
GitHub: `alonsorgl28/teams-translator` (público)

---

## Reglas de trabajo

- **No tocar lo que funciona.** BUG-01..05, BUG-10, BUG-11 están resueltos. No refactorizar por estética.
- **Un bug a la vez.** Resolver por prioridad: P0 → P1 → P2 → Features.
- **Toda variable configurable va en `.env`.** Nunca hardcodear thresholds, modelos o timeouts.
- **Tests antes de cerrar ticket.** Si no hay test para el bug, crearlo.
- **Actualizar `ProjectTracker.md` y `LORO_CONTEXT.md` al cerrar la sesión.**

---

## Gotchas confirmados

| Gotcha | Detalle |
|--------|---------|
| BlackHole obligatorio en macOS | `audio_listener.py` falla explícitamente si no hay dispositivo loopback. Sin BlackHole, START no hace nada. |
| `QApplication.clipboard()` crashea en Linux sin display | `main.py:548` — no testear en entornos headless. |
| `qasync` + `PyQt6` — event loop compartido | El loop de asyncio es el mismo de Qt. No crear loops separados. |
| Cambio de idioma no cancela pipeline activo | El contexto se limpia (BUG-03 ✅) pero la cola de audio no se vacía. Puede haber chunks del idioma anterior. |
| `.env` sin trailing newline causa que última variable no se cargue | Siempre dejar línea vacía al final del `.env`. |
| `FULL_TRANSCRIPT_MAX_SEGMENTS` controla memoria de la UI | Default 500. Sesiones largas acumulan RAM en overlay si no se limita. |

---

## Arquitectura rápida

```
audio_listener.py   → captura chunks del sistema (sounddevice + BlackHole/VB-Cable)
       ↓
transcription_service.py  → STT batch/stream (gpt-4o-mini-transcribe → whisper-1 fallback)
       ↓
translation_service.py    → traducción (gpt-4o-mini, preserva términos técnicos + números)
       ↓
overlay_ui.py       → PyQt6 overlay, modos: cinema / list, always-on-top, draggable
       ↑
main.py             → orquestación async (qasync), dedup, rolling buffer 60min, métricas
```

---

## Estado actual de bugs

**Resueltos:** BUG-01, 02, 03, 04, 05, 10, 11
**Pendientes P1:** BUG-06, 07, 08, 09, 12, 13
**Pendientes P2:** BUG-14 al 22

---

## Sesión start template

```
Lee CLAUDE.md y LORO_CONTEXT.md. Luego implementa [TAREA].
```

---

## Visión producto (no perder de vista)

**Posicionamiento decidido (2 mar 2026):** Loro no compite con Seagull en simplicidad.
Loro es la herramienta para el **profesional técnico** — developer, PM, trader, analista —
que quiere control total: sin límite de horas, sin intermediarios, audio directo a OpenAI.

| | Seagull | Loro |
|--|---------|------|
| Cliente | Cualquiera | Profesional técnico |
| Horas | 48h/mes ($6.99) | Ilimitadas (tu API key) |
| Privacidad | Audio en servidores de Seagull | Audio va directo a OpenAI |
| Setup | Zero | BlackHole requerido ← **resolver esto** |

**Los dos bloqueantes reales para vender:**
1. BlackHole — fricción de instalación que mata conversiones (prioridad antes de marketing)
2. Latencia inicial del primer subtítulo — experiencia de primera impresión crítica
