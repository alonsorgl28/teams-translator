# Teams Use Case

## Purpose
Usar Loro para traducir en vivo reuniones de Microsoft Teams sin depender de subtítulos nativos.

## Windows setup (VB-Cable)
1. Instala VB-Cable.
2. En Windows Sound, deja `CABLE Input` como salida para Teams (o selecciona `CABLE Input` dentro de Teams).
3. Ejecuta Loro y verifica que capture `CABLE Output`.
4. Si hace falta, define `SYSTEM_AUDIO_DEVICE` en `.env`.

## macOS setup (BlackHole)
1. Instala BlackHole.
2. Crea un Multi-Output Device en Audio MIDI Setup (recomendado).
3. En Teams, selecciona BlackHole o el Multi-Output Device como salida.
4. Ejecuta Loro y valida que aparezcan subtítulos en vivo.

## Verification checklist
- [ ] El medidor/input del sistema muestra actividad mientras habla la reunión.
- [ ] En Loro, el estado cambia a modo `Live` al iniciar.
- [ ] Puedo ver subtítulos en pantalla durante la reunión.
- [ ] Al exportar, el `.txt` contiene líneas traducidas recientes.
- [ ] No aparece error de autenticación (`401/403`).
