# ProjectTracker - Loro

## Progreso global estimado
**91%**

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
1. Sustituir el camino operativo principal de STT por una vía incremental/streaming soportada; hoy el default sigue siendo batch y eso limita la experiencia tipo Seagull.
2. Reducir `time-to-first-subtitle` y `time-to-first-final-translation` con preview temprano estable y flush inicial más agresivo.
3. Corregir segmentación/contexto de traducción para evitar frases semánticamente rotas en fragmentos cortos.
4. Definir benchmark fijo de 60-90s y usarlo para medir `AVG`, `P95`, primer subtítulo y calidad de traducción.
5. Ejecutar validación real F8 en Teams cuando el pipeline de latencia esté más estable.
6. Cerrar selector de dispositivo de audio en UI con detección en vivo y validación de apply/restart.

## Registro de cambios (resumen)
- 2026-02-14: Se completó MVP funcional base y se inició fase F8 (validación E2E real).
- 2026-02-19: Se añadió instrumentación de métricas por segmento y resumen de sesión (JSONL + summary), nuevos controles por entorno (`METRICS_*`) y plan formal de validación real (`ValidationPlan.md`).
- 2026-02-23: Se completó remediación de auditoría (15/15), se reforzó concurrencia/memoria/UI, se optimizó pipeline de latencia y se amplió cobertura de tests.
- 2026-02-24: Se aplicó perfil `sync-first` para reducir desfase (backlog de skip en `2`), se añadió descarte de segmentos viejos (`MAX_SEGMENT_STALENESS_SECONDS`), se dejó `gpt-4o-mini` como default de traducción por latencia, y se agregó prueba unitaria para validar stale-drop antes de render.
- 2026-02-28: Se completó rebrand del producto a `Loro`, se actualizó `README.md` para uso universal (Teams/Zoom/YouTube) y se añadieron docs de casos de uso.
- 2026-03-01: La UI quedó mucho más cerca de la referencia visual tipo Seagull; el estado real del proyecto sigue marcado por latencia inicial de subtítulos, STT aún mayormente batch y necesidad de mejor segmentación antes de traducción.
- 2026-03-01 (sesión 2): BUG-07 y BUG-13 resueltos. Fix crítico de entorno: migración a Python 3.11 (Homebrew) + PyQt6 6.8.1 + patch RPATH/codesign para cocoa plugin en macOS Sequoia. Streaming STT activado por default. Tuning de .env: TRANSLATION_MAX_TOKENS 200, MERGE_MIN_WORDS 5, MIN_EMIT_WORDS 4.
