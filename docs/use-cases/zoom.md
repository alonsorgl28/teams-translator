# Zoom Use Case

## Purpose
Usar Loro para traducir en tiempo real llamadas de Zoom (clases, entrevistas, demos, soporte).

## Windows setup (VB-Cable)
1. Instala VB-Cable.
2. Configura Zoom para salida en `CABLE Input`.
3. Inicia Loro y confirma captura desde `CABLE Output`.
4. Ajusta `SYSTEM_AUDIO_DEVICE` en `.env` si el auto-detect no selecciona el dispositivo correcto.

## macOS setup (BlackHole)
1. Instala BlackHole.
2. Crea un Multi-Output Device en Audio MIDI Setup.
3. Configura Zoom para salida en BlackHole o en el Multi-Output Device.
4. Inicia Loro y revisa subtítulos traducidos en vivo.

## Verification checklist
- [ ] El audio de Zoom llega al dispositivo virtual (VB-Cable/BlackHole).
- [ ] Loro muestra transcripción/traducción en tiempo real.
- [ ] Puedo detener y reanudar sin reiniciar toda la app.
- [ ] Exportar `.txt` guarda el historial visible de la sesión.
- [ ] No hay captura accidental del micrófono local como fuente principal.
