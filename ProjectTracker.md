# ProjectTracker - Loro

## Progreso global estimado
**93%**

## Fases 0% -> 100%

| Fase | % | Objetivo | Estado |
|---|---:|---|---|
| F0 | 0% | Kickoff y definición del problema | Completado |
| F1 | 10% | Recolección de requisitos funcionales y no funcionales | Completado |
| F2 | 20% | Diseño de arquitectura modular y flujo de datos | Completado |
| F3 | 30% | Scaffold base del proyecto y dependencias | Completado |
| F4 | 40% | Captura de audio del sistema por chunks (3s) | Completado |
| F5 | 50% | STT con detección de idioma | Completado |
| F6 | 60% | Traducción técnica a español con reglas de preservación | Completado |
| F7 | 70% | Overlay UI y controles principales | Completado |
| F8 | 80% | Integración E2E local + validaciones en entorno real | En progreso (validación fuerte en YouTube, falta benchmark fijo y validación Teams real) |
| F9 | 90% | Hardening (manejo de errores, latencia sostenida, UX fina) | En progreso (UI premium avanzada; cuello principal actual en STT batch, sincronía y segmentación de traducción) |
| F10 | 100% | Release candidate estable y documentación final | Pendiente |

## Entregables completados
- Código modular solicitado:
  - `/Users/hola/Documents/New project/audio_listener.py`
  - `/Users/hola/Documents/New project/transcription_service.py`
  - `/Users/hola/Documents/New project/translation_service.py`
  - `/Users/hola/Documents/New project/overlay_ui.py`
  - `/Users/hola/Documents/New project/main.py`
  - `/Users/hola/Documents/New project/metrics_reporter.py`
  - `/Users/hola/Documents/New project/config_utils.py`
- Setup/documentación:
  - `/Users/hola/Documents/New project/requirements.txt`
  - `/Users/hola/Documents/New project/.env.example`
  - `/Users/hola/Documents/New project/README.md`
  - `/Users/hola/Documents/New project/ValidationPlan.md`
  - `/Users/hola/Documents/New project/docs/use-cases/`
- Contexto operativo:
  - `/Users/hola/Documents/New project/TranslationTool/Context.md`
- Calidad:
  - `/Users/hola/Documents/New project/tests/` (audio buffer/UI/dedup/metrics/translation/visualización)

## Backlog inmediato (siguiente iteración)
1. BUG-24 final — cambiar REALTIME_SESSION_MODEL=gpt-4o-realtime-preview, validar Run 7 con realtime activo.
2. BUG-25 — revisar cap premium en main.py (13.5% > cap 10%).
3. BUG-26 — subir STALE_EMIT_RELAX_FACTOR 1.17→1.35 para eliminar stale drops.
4. BUG-06 / BUG-08 / BUG-09 — bugs P1 pendientes.
5. F07/F08 — packaging PyInstaller macOS + Windows.

## Registro de cambios (resumen)
- 2026-02-14: Se completó MVP funcional base y se inició fase F8 (validación E2E real).
- 2026-02-19: Se añadió instrumentación de métricas por segmento y resumen de sesión (JSONL + summary), nuevos controles por entorno (`METRICS_*`) y plan formal de validación real (`ValidationPlan.md`).
- 2026-02-23: Se completó remediación de auditoría (15/15), se reforzó concurrencia/memoria/UI, se optimizó pipeline de latencia y se amplió cobertura de tests.
- 2026-02-24: Se aplicó perfil `sync-first` para reducir desfase (backlog de skip en `2`), se añadió descarte de segmentos viejos (`MAX_SEGMENT_STALENESS_SECONDS`), se dejó `gpt-4o-mini` como default de traducción por latencia, y se agregó prueba unitaria para validar stale-drop antes de render.
- 2026-02-28: Se completó rebrand del producto a `Loro`, se actualizó `README.md` para uso universal (Teams/Zoom/YouTube) y se añadieron docs de casos de uso.
- 2026-03-01: La UI quedó mucho más cerca de la referencia visual tipo Seagull; el estado real del proyecto sigue marcado por latencia inicial de subtítulos, STT aún mayormente batch y necesidad de mejor segmentación antes de traducción.
- 2026-03-01 (sesión 2): BUG-07 y BUG-13 resueltos. Fix crítico de entorno: migración a Python 3.11 (Homebrew) + PyQt6 6.8.1 + patch RPATH/codesign para cocoa plugin en macOS Sequoia. Streaming STT activado por default. Tuning de .env: TRANSLATION_MAX_TOKENS 200, MERGE_MIN_WORDS 5, MIN_EMIT_WORDS 4.
- 2026-03-12: Silero VAD implementado (vad.py + audio_listener.py). Fix permanente de cocoa crash (staging plugins Qt a /tmp en main.py). Latencia primer subtítulo: 46s→6s. BUG-23 parcialmente resuelto (VAD elimina mezcla pero añade latencia). Próximo: instrumentar pipeline para diagnóstico cuantitativo. Commit `e4a5e0d`.
- 2026-03-16: Pipeline analizado con datos reales (93 registros). Latencia avg=2.35s P95=3.17s. STT=53% del tiempo. Drop rate reducido: SOURCE_COMMIT_MIN_CONFIDENCE 0.39→0.28 (14/17 drops innecesarios rescatados). Gaps largos diagnosticados como silencios naturales (no bugs). Nuevo script `parse_pipeline.py` con modo --compare para VAD off vs on. venv movido a `~/loro-venv` (fix path con espacios). Alias `loro` configurado. Commit `0441ff9`.
- 2026-03-16 (sesión 17): 6 runs de validación. Run 5 y Run 6: 0.0% issue rate, 0 drops. Fixes aplicados: chunk cap 1.0→2.5s, TRANSLATION_CONTEXT_TURNS 3→1, prompt de contexto con [REFERENCE ONLY], xattr+codesign en run.sh, STALE_EMIT_RELAX_FACTOR 1.5→1.17. BUG-24 parcial: protocolo transcription_session.update corregido, pero REALTIME_SESSION_MODEL sigue siendo incorrecto (gpt-4o-mini-transcribe → necesita gpt-4o-realtime-preview). Métricas Run 6: avg=2.04s p50=1.73s p95=3.26s, premium ratio 13.5% (excede cap). Commits `fa2d665`, `75fcabf`.
