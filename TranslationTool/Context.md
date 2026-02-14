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
Fecha de actualización: 2026-02-14

Implementado:
- `/Users/hola/Documents/New project/audio_listener.py`
  - Captura de audio por `sounddevice`.
  - Chunking asíncrono cada 3 segundos.
  - Búsqueda de dispositivos loopback (VB-Cable/BlackHole).
  - Falla explícita si no encuentra dispositivo virtual válido (evita fallback a micrófono).
- `/Users/hola/Documents/New project/transcription_service.py`
  - Integración STT asíncrona con `whisper-1`.
  - Detección automática de idioma.
  - Reintentos básicos.
- `/Users/hola/Documents/New project/translation_service.py`
  - Traducción a español con tono formal técnico.
  - Preservación de términos críticos (AAAC, ACSR, OPGW, DDP, FOB, CIF).
  - Validación de preservación de números/unidades con segunda pasada correctiva.
- `/Users/hola/Documents/New project/overlay_ui.py`
  - Overlay oscuro ~70% opacidad, texto blanco.
  - Últimos 10 segmentos, auto-scroll, slider de fuente.
  - Ventana draggable y always-on-top.
  - Botones requeridos + toggle de visibilidad del área de texto.
- `/Users/hola/Documents/New project/main.py`
  - Orquestación async con `qasync`.
  - Pipeline: Audio -> STT -> Traducción -> UI.
  - Buffer rolling de 60 minutos.
  - Save Session (solo texto traducido).
- Soporte de proyecto:
  - `/Users/hola/Documents/New project/requirements.txt`
  - `/Users/hola/Documents/New project/.env.example`
  - `/Users/hola/Documents/New project/README.md`

## 4) Decisiones técnicas clave
- Stack principal: Python + PyQt6 + asyncio/qasync.
- Servicios IA: OpenAI (`whisper-1` + chat model para traducción).
- Diseño modular por archivos funcionales solicitados.
- No persistir audio por requisito de privacidad/scope.

## 5) Riesgos y pendientes
- Prueba E2E real en Teams + dispositivo virtual en cada OS.
- Medición real de latencia sostenida (<6s) bajo carga/red variable.
- Mejorar selección de dispositivo desde UI (hoy: auto + variable `SYSTEM_AUDIO_DEVICE`).
- Manejo de fallos de red/API más robusto (retries/backoff/circuit breaker).

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
