# YouTube Use Case

## Purpose
Usar Loro para traducir videos de YouTube en vivo durante reproducción (tutoriales, podcasts, conferencias).

## Windows setup (VB-Cable)
1. Instala VB-Cable.
2. Configura el navegador o el sistema para salida en `CABLE Input`.
3. Ejecuta Loro y deja que detecte `CABLE Output`.
4. Reproduce un video y valida flujo continuo de subtítulos.

## macOS setup (BlackHole)
1. Instala BlackHole.
2. Crea un Multi-Output Device si quieres seguir escuchando por altavoces/audífonos.
3. Configura salida del navegador a BlackHole o al Multi-Output Device.
4. Ejecuta Loro y reproduce el video.

## Verification checklist
- [ ] El medidor de audio del sistema se mueve al reproducir el video.
- [ ] Veo subtítulos traducidos en vivo dentro de Loro.
- [ ] El texto exportado coincide con el periodo de reproducción probado.
- [ ] El rendimiento se mantiene sin pausas largas.
- [ ] Si uso audífonos Bluetooth, el ruteo sigue enviando audio al loopback virtual.
