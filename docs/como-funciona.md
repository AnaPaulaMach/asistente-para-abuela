# Cómo funciona (la parte técnica)

## Hardware y pines

| Función | Pin |
|---|---|
| Botón principal | GPIO17 (pull-up, activo en bajo) |
| Ruedita (encoder) | GPIO13 y GPIO26 |
| LEDs WS2812 | GPIO12 (PWM0) |
| Audio (ReSpeaker) | I2C en GPIO2/3, I2S en GPIO18–21 |

La placa de sonido usa un solo reloj para grabar y reproducir: el programa nunca hace las dos cosas a la vez.

## Instalación en la Pi

1. Raspberry Pi OS Lite de 64 bits, con SSH y WiFi (de 2,4 GHz: la Zero 2 W no ve las de 5 GHz).
2. Overlay de la placa de sonido: `dtparam=i2s=on` y `dtoverlay=respeaker-2mic-v2_0` en `/boot/firmware/config.txt`.
3. Paquetes: `sudo apt install python3-libgpiod python3-numpy opus-tools rsync mpv`.
4. Copiá `asistente/` y `systemd/` a `~/asistente` en la Pi (o usá `desplegar.sh` desde tu compu).
5. Dos entornos de Python:
   ```bash
   python3 -m venv --system-site-packages ~/asistente/venv
   ~/asistente/venv/bin/pip install google-genai
   python3 -m venv ~/asistente/venv-luces
   ~/asistente/venv-luces/bin/pip install rpi_ws281x
   ```
6. Configuración privada en `~/.config/asistente/` (mirá `ejemplos/`): `secretos.env` (permisos 600), `ajustes.env`, `perfil.md`, `personas.toml` (600), `recordatorios.txt` y `radios.toml`.
7. Frases fijas (emergencia, recordatorios): `~/asistente/venv/bin/python ~/asistente/frases.py`
8. Servicios: `bash ~/asistente/instalar-servicios.sh`

Para ver qué pasa: `journalctl -u asistente-charla -f`

## Las piezas

| Archivo | Qué hace |
|---|---|
| `charla.py` | El programa principal: botón, ruedita, conexión con Gemini Live, escucha automática después de una pregunta |
| `entradas.py` | El botón y la ruedita con libgpiod: el kernel avisa cuando un pin cambia (0 % de CPU en reposo) |
| `tareas.py` | Tareas de fondo que no se pierden y anotan sus errores |
| `prompt/base.md` | Las instrucciones de Gemini (públicas). El perfil y la familia van aparte, en archivos privados |
| `personas.py` | Lee `personas.toml` y arma el texto para el prompt (sin teléfonos) y los cumpleaños del día |
| `alerta.py` | La emergencia: pregunta, cuenta regresiva, aviso y mensaje de voz por Telegram |
| `recordatorios.py` | Recordatorios diarios o de una sola vez (`27/11 17:00 texto`), con confirmación y aviso si no confirma; ella los agrega y borra hablando |
| `dia.py` | El "buen día" (clima tranquilo, cumpleaños, recordatorios) y el chequeo: si a la mañana no tocó el botón ni la ruedita, avisa a la familia |
| `vigilante.py` | Avisos por Telegram: se prendió (¿corte de luz?), temperatura de 75 °C o más, baja tensión, estuvo sin internet |
| `memoria.py` | Notas de lo que ella cuenta (herramientas recordar y olvidar), privadas en `memoria.md`; las últimas 40 van en cada charla, se guardan 80 |
| `mensajes.py` | Mensajes de la familia por Telegram (texto o audio) dichos en voz alta, con confirmación; solo de quienes están en `personas.toml`; ella contesta hablando (herramienta mandar_mensaje) |
| `llamadas.py` | "Decile a … que me llame": avisa por Telegram (a esa persona si tiene chat, si no a la familia con su teléfono), uno cada 10 minutos como mucho |
| `radio.py` | Emisoras por internet con mpv (lista privada en `radios.toml`); un toque la apaga, se apaga sola a las 3 horas |
| `noticias.py` | Titulares del día (RSS de Google Noticias, sin clave) sin policiales ni tragedias; herramienta de Gemini |
| `clima.py` | El pronóstico de Open-Meteo (herramienta de Gemini) |
| `volumen.py` | Niveles del 1 al 10, guardados; la ruedita y Gemini usan lo mismo |
| `leds.py` / `luces.py` | Las luces corren aparte, como root; la charla les manda el estado por UDP local |
| `telegram_bot.py` | Mandar texto y notas de voz con el bot |
| `frases.py` | Graba con Gemini las frases fijas, que después funcionan sin internet |
| `agregar-wifi.sh` | Suma otra red WiFi sin borrar las que ya conoce |

## Decisiones que vale la pena contar

- **Pensado para una Pi Zero encendida todo el día:** en reposo la charla usa 0 % de CPU (libgpiod en vez de un hilo que revisa los pines), el audio se procesa con numpy, las luces no redibujan cuando nada cambia, y nada se queda esperando para siempre (límites de tiempo con Gemini; los procesos de audio mueren si se cancela su tarea).

- **"Tocar y hablar", no "mantener apretado para hablar":** mantener apretado es la emergencia.
- **La emergencia avisa si nadie la cancela:** si se cayó y no puede contestar, el aviso tiene que salir igual.
- **Las herramientas de Gemini** (*function calling*): Gemini no cambia el volumen ni busca el clima por su cuenta; le pide al programa que lo haga.
- **Cuánto se paga:** cada respuesta vuelve a procesar toda la charla anterior; por eso la conexión se cierra a los 2 minutos sin uso.
- **Búsqueda en Google:** Gemini puede buscar para preguntas puntuales (5.000 búsquedas gratis por mes; después USD 14 cada 1.000).
- **Seguridad:** SSH solo con llave, ningún otro puerto abierto, actualizaciones automáticas, registro que se borra a la semana, acceso remoto por Tailscale.
