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
3. Paquetes: `sudo apt install python3-gpiozero python3-lgpio opus-tools rsync`.
4. Copiá `asistente/` y `systemd/` a `~/asistente` en la Pi (o usá `desplegar.sh` desde tu compu).
5. Dos entornos de Python:
   ```bash
   python3 -m venv --system-site-packages ~/asistente/venv
   ~/asistente/venv/bin/pip install google-genai
   python3 -m venv ~/asistente/venv-luces
   ~/asistente/venv-luces/bin/pip install rpi_ws281x
   ```
6. Configuración privada en `~/.config/asistente/` (mirá `ejemplos/`): `secretos.env` (permisos 600), `ajustes.env`, `perfil.md`, `personas.toml` (600) y `recordatorios.txt`.
7. Frases fijas (emergencia, recordatorios): `~/asistente/venv/bin/python ~/asistente/frases.py`
8. Servicios: `bash ~/asistente/instalar-servicios.sh`

Para ver qué pasa: `journalctl -u asistente-charla -f`

## Las piezas

| Archivo | Qué hace |
|---|---|
| `charla.py` | El programa principal: botón, ruedita, conexión con Gemini Live, escucha automática después de una pregunta |
| `prompt/base.md` | Las instrucciones de Gemini (públicas). El perfil y la familia van aparte, en archivos privados |
| `personas.py` | Lee `personas.toml` y arma el texto para el prompt (sin teléfonos) y los cumpleaños del día |
| `alerta.py` | La emergencia: pregunta, cuenta regresiva, aviso y mensaje de voz por Telegram |
| `recordatorios.py` | Recordatorios diarios con confirmación y aviso si no confirma |
| `clima.py` | El pronóstico de Open-Meteo (herramienta de Gemini) |
| `volumen.py` | Niveles del 1 al 10, guardados; la ruedita y Gemini usan lo mismo |
| `leds.py` / `luces.py` | Las luces corren aparte, como root; la charla les manda el estado por UDP local |
| `telegram_bot.py` | Mandar texto y notas de voz con el bot |
| `frases.py` | Graba con Gemini las frases fijas, que después funcionan sin internet |
| `agregar-wifi.sh` | Suma otra red WiFi sin borrar las que ya conoce |

## Decisiones que vale la pena contar

- **"Tocar y hablar", no "mantener apretado para hablar":** mantener apretado es la emergencia.
- **La emergencia avisa si nadie la cancela:** si se cayó y no puede contestar, el aviso tiene que salir igual.
- **Las herramientas de Gemini** (*function calling*): Gemini no cambia el volumen ni busca el clima por su cuenta; le pide al programa que lo haga.
- **Cuánto se paga:** cada respuesta vuelve a procesar toda la charla anterior; por eso la conexión se cierra a los 2 minutos sin uso.
- **Seguridad:** SSH solo con llave, ningún otro puerto abierto, actualizaciones automáticas, registro que se borra a la semana, acceso remoto por Tailscale.
