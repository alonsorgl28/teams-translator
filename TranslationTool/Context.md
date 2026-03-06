# Translation Tool - Contexto del Proyecto

## 1) Objetivo
Construir un MVP local de escritorio que traduzca reuniones de Microsoft Teams en tiempo real hacia español, con enfoque técnico en infraestructura eléctrica y compras/licitaciones.

## 2) Alcance funcional (MVP)
- Captura de audio del sistema (no micrófono) en chunks de 3 segundos.
- STT con detección automática de idioma (en, pt, zh, hi).
- Traducción a español manteniendo terminología técnica y números/unidades.
- Overlay flotante semi-transparente, arrastrable, always-on-top, auto-scroll.
- Controles: Start/Stop, Copy, Export `.txt`, Clear.
- Buffer de texto de 60 minutos.
- Sin almacenamiento de audio crudo.
- Guardado de texto traducido solo si `Save Session` está habilitado.

## 3) Estado actual (actualizado)
Fecha de actualización: 2026-02-24

Implementado:
- `/Users/hola/Documents/New project/audio_listener.py`
  - Captura de audio por `sounddevice`.
  - Chunking asíncrono configurable por entorno.
  - Búsqueda de dispositivos loopback (VB-Cable/BlackHole).
  - Falla explícita si no encuentra dispositivo virtual válido (evita fallback a micrófono).
  - Buffer de audio protegido con lock y límite en memoria (`AUDIO_MAX_BUFFER_SECONDS`).
- `/Users/hola/Documents/New project/transcription_service.py`
  - Integración STT asíncrona con modelo primario configurable (`TRANSCRIPTION_MODEL`) y fallback (`TRANSCRIPTION_FALLBACK_MODEL`).
  - Detección automática de idioma con hint opcional (`TRANSCRIPTION_LANGUAGE_HINT`).
  - Reintentos básicos.
  - Contexto de prompt configurable/desactivable para evitar deriva.
- `/Users/hola/Documents/New project/translation_service.py`
  - Traducción multilenguaje hacia target configurable (`TARGET_LANGUAGE`), con foco en español técnico por defecto.
  - Preservación de términos críticos y números/unidades.
  - Validación de preservación de números/unidades con segunda pasada correctiva.
  - Fallback de modelo configurable y contexto corto controlado.
  - Default actual orientado a latencia: `gpt-4o-mini` (fallback `gpt-4o-mini`).
- `/Users/hola/Documents/New project/overlay_ui.py`
  - Overlay oscuro con modo `list` y modo `cinema`, con diseño más minimalista/premium.
  - Buffer completo acotado con `FULL_TRANSCRIPT_MAX_SEGMENTS`.
  - Ventana draggable y always-on-top.
  - Botones requeridos + panel de subtítulos en vivo.
  - Corregido bug de visibilidad en transición Start/Stop (modo cinema).
- `/Users/hola/Documents/New project/main.py`
  - Orquestación async con `qasync`.
  - Pipeline: Audio -> STT -> Traducción -> UI.
  - Buffer rolling de 60 minutos.
  - Save Session (solo texto traducido).
  - Dedupe por `SequenceMatcher` manteniendo orden.
  - Tarea de toggle referenciada/cancelable.
  - Control de backlog audio/texto con descarte de cola vieja.
  - Descarte explícito de segmentos stale antes de STT/traducción/render (`MAX_SEGMENT_STALENESS_SECONDS`).
  - Limpieza de ruido de transcripción (promos/URLs/repeticiones).
  - Emisión de fragmentos calibrada por latencia y mínimo de palabras.
- Soporte de proyecto:
  - `/Users/hola/Documents/New project/requirements.txt`
  - `/Users/hola/Documents/New project/.env.example`
  - `/Users/hola/Documents/New project/README.md`
  - `/Users/hola/Documents/New project/config_utils.py`
  - `/Users/hola/Documents/New project/metrics_reporter.py`
  - `/Users/hola/Documents/New project/tests/` (unit tests de audio/UI/dedup/metrics/traducción)

## 4) Decisiones técnicas clave
- Stack principal: Python + PyQt6 + asyncio/qasync.
- Servicios IA: OpenAI (`whisper-1` + chat model para traducción).
- Diseño modular por archivos funcionales solicitados.
- No persistir audio por requisito de privacidad/scope.

## 5) Riesgos y pendientes
- Prueba E2E real en Teams + dispositivo virtual en cada OS (actualmente validación fuerte en YouTube).
- Ajuste fino de equilibrio latencia vs precisión semántica por tipo de contenido (tuning de `MAX_SEGMENT_STALENESS_SECONDS`, `MERGE_*`, `MIN_EMIT_WORDS`).
- Selector de dispositivo desde UI (hoy: auto + variable `SYSTEM_AUDIO_DEVICE`).
- Estrategia de resiliencia de red/API más robusta (retries/backoff/circuit breaker).
- Refinamiento visual de UI para lectura continua de subtítulos en sesiones largas.

## 6) Protocolo para cambios constantes (prompts futuros)
1. Registrar el cambio pedido en la sección `Change Log`.
2. Evaluar impacto (arquitectura, UI, performance, costos API).
3. Actualizar primero este `Context.md`.
4. Actualizar `ProjectTracker.md` con progreso y tareas derivadas.
5. Implementar código y dejar evidencia de validación.

## 7) Recomendación de memoria del proyecto
Tu idea de `memory.md` es buena como bitácora rápida. Recomendación:
- Fuente oficial: `Context.md` + `ProjectTracker.md`.
- Bitácora opcional: `TranslationTool/memory.md` para notas cortas entre prompts.

## 8) Change Log
- 2026-02-14:
  - Se creó el scaffold completo del MVP local.
  - Se implementó pipeline asíncrono de traducción en tiempo real.
  - Se agregó overlay con controles requeridos.
  - Se agregó buffer de 60 minutos y lógica de Save Session.
  - Se documentó setup/run y routing de audio virtual.
- 2026-02-19:
  - Se agregó instrumentación de métricas por segmento/sesión (`reports/*.json*`).
  - Se formalizó plan de validación y seguimiento (`ValidationPlan.md`).
- 2026-02-23:
  - Se ejecutó remediación técnica de concurrencia/memoria/mantenibilidad (auditoría 15/15).
  - Se añadió `config_utils.py` y se unificó lectura de variables de entorno.
  - Se acotaron buffers en audio/UI y se reforzó deduplicación/limpieza de ruido.
  - Se ajustó pipeline para menor latencia percibida y mejor legibilidad en tiempo real.
  - Se ampliaron pruebas unitarias y validación de regresiones de visualización.
- 2026-02-24:
  - Se aplicó perfil sync-first para reducir desfase en subtítulos en vivo.
  - Se incorporó descarte de segmentos viejos con umbral configurable (`MAX_SEGMENT_STALENESS_SECONDS`).
  - Se ajustó default de traducción a `gpt-4o-mini` para menor latencia.
  - Se agregó cobertura de test para asegurar que segmentos stale no llegan a la UI.
