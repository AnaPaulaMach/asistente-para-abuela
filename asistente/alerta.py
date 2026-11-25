"""Etapa e: la emergencia (pulsación larga del botón).

1. El asistente pregunta "¿Es una emergencia?" y cuenta 10 segundos con las luces.
2. Un toque corto lo cancela. Si nadie lo cancela, AVISA: si se cayó y no
   puede contestar, el aviso tiene que salir igual.
3. Manda el aviso por Telegram y le ofrece mandar un mensaje: si toca el
   botón (dentro de un minuto) graba 10 segundos y los manda como nota de voz.
   Solo graba si ella toca: nunca queda escuchando de más.
4. Sin internet: lo dice y reintenta cada 20 segundos durante 5 minutos.

Las frases están grabadas en ~/asistente/frases/ (frases.py), así funcionan aunque
Gemini no responda.
"""
import array
import asyncio
import tempfile
import time
import wave
from pathlib import Path

import telegram_bot
from luces import luz

FRASES = Path.home() / "asistente" / "frases"
PLACA = "plughw:seeed2micvoicec"
CUENTA = 10          # segundos para cancelar
GRABACION = 10       # segundos de audio que se mandan a la familia
ESPERA_MENSAJE = 60  # segundos para tocar el botón y grabar el mensaje
REINTENTO = 20       # segundos entre intentos sin internet
INTENTOS = 15        # 15 x 20 s = 5 minutos

activa = False       # los recordatorios esperan mientras haya una emergencia


async def _correr(*comando):
    p = await asyncio.create_subprocess_exec(
        *comando, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    await p.wait()


def normalizar(wav, ganancia_max=20):
    """Sube el volumen de una grabación: los micrófonos graban bajito.

    Resta la continua (el promedio) y multiplica para que el pico quede al 90 %
    del máximo, sin pasar de `ganancia_max` veces (si no, el silencio con
    ruido de fondo se volvería un "shhh" fuerte).
    """
    with wave.open(str(wav)) as w:
        parametros = w.getparams()
        # Los primeros 0,2 s traen el salto del conversor al arrancar: afuera.
        w.readframes(w.getframerate() // 5)
        muestras = array.array("h", w.readframes(w.getnframes()))
    if not muestras:
        return
    media = sum(muestras) // len(muestras)
    # Un golpe aislado no debe frenar la ganancia: tomamos como "pico" el valor
    # que supera al 99,9 % de las muestras, en lugar del máximo absoluto.
    pico = sorted(abs(x - media) for x in muestras)[int(len(muestras) * 0.999)] or 1
    ganancia = min(ganancia_max, 0.9 * 32767 / pico)
    for i, x in enumerate(muestras):
        muestras[i] = max(-32768, min(32767, int((x - media) * ganancia)))
    with wave.open(str(wav), "wb") as w:
        w.setparams(parametros)
        w.writeframes(muestras.tobytes())
    print(f"   (volumen x{ganancia:.1f})", flush=True)


async def decir(frase):
    await _correr("aplay", "-q", "-D", PLACA, str(FRASES / f"{frase}.wav"))


async def _esperar_toque(toques, segundos):
    try:
        return await asyncio.wait_for(toques.get(), timeout=segundos)
    except asyncio.TimeoutError:
        return None


async def _mandar(funcion, *args):
    """Intenta mandar a Telegram; sin conexión reintenta. Devuelve True si salió."""
    for intento in range(INTENTOS):
        try:
            await asyncio.to_thread(funcion, *args)
            return True
        except RuntimeError as e:
            print(f"   ✗ {e} (intento {intento + 1} de {INTENTOS})", flush=True)
            luz("error")
            if intento == 0:
                await decir("sin_internet")
            await asyncio.sleep(REINTENTO)
    return False


async def emergencia(toques):
    """Toda la secuencia. `toques` es la cola del botón, para poder cancelar."""
    global activa
    activa = True
    try:
        await _emergencia(toques)
    finally:
        activa = False


async def _emergencia(toques):
    apretado = time.strftime("%H:%M")
    print("🚨 Pulsación larga: preguntando si es una emergencia...", flush=True)
    while not toques.empty():  # toques viejos no cuentan como cancelación
        toques.get_nowait()

    luz("emergencia")
    await decir("pregunta")
    for quedan in range(CUENTA, 0, -1):
        luz("cuenta", quedan)
        toque = await _esperar_toque(toques, 1)
        if toque == "corto":
            print("   Cancelado con un toque.", flush=True)
            luz("esperando")
            await decir("cancelado")
            return
        if toque == "larga":
            break  # la volvió a mantener: es que sí, avisar ya

    luz("emergencia")
    print("   Avisando a la familia por Telegram...", flush=True)
    chat = telegram_bot.chat_familia()
    texto = (f"🚨 EMERGENCIA: tu abuela mantuvo apretado el botón de emergencia a las {apretado} "
             "y no canceló el aviso. Si graba un mensaje, te lo mando enseguida.")
    if not await _mandar(telegram_bot.mandar_texto, chat, texto):
        print("   ✗ No se pudo avisar en 5 minutos.", flush=True)
        luz("error")
        return
    print("   ✓ Aviso mandado. Esperando si quiere grabar un mensaje...", flush=True)
    luz("emergencia")
    await decir("avisado")

    while not toques.empty():
        toques.get_nowait()
    if await _esperar_toque(toques, ESPERA_MENSAJE) is None:
        print("   No grabó mensaje.", flush=True)
        await decir("tranquila")
        luz("esperando")
        return

    with tempfile.TemporaryDirectory() as tmp:
        wav, ogg = Path(tmp) / "mensaje.wav", Path(tmp) / "mensaje.ogg"
        luz("escuchando")
        print(f"   🎤 Grabando {GRABACION} s...", flush=True)
        # 16 kHz alcanza para voz y es 3 veces menos trabajo para normalizar.
        await _correr("arecord", "-q", "-D", PLACA, "-f", "S16_LE", "-r", "16000", "-c", "1",
                      "-d", str(GRABACION), str(wav))
        await asyncio.to_thread(normalizar, wav)
        await _correr("opusenc", "--quiet", str(wav), str(ogg))
        luz("emergencia")
        audio_ok = await _mandar(telegram_bot.mandar_voz, chat, ogg,
                                 f"🎤 Mensaje de tu abuela después del aviso ({apretado})")

    if audio_ok:
        print("   ✓ Mensaje mandado.", flush=True)
        await decir("mensaje_mandado")
        luz("esperando")
    else:
        print("   ✗ El mensaje de voz no salió.", flush=True)
        luz("error")
