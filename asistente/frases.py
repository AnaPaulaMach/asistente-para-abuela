#!/usr/bin/env python3
"""Graba con Gemini las frases fijas del asistente y las guarda en ~/asistente/frases/.

Se corre una vez (y de nuevo si se cambia la voz o el texto). Al quedar
guardadas, el asistente las puede decir aunque no haya internet: justo lo que hace
falta en una emergencia.

    ~/asistente/venv/bin/python ~/asistente/frases.py              (todas)
    ~/asistente/venv/bin/python ~/asistente/frases.py pregunta     (solo algunas)
"""
import asyncio
import sys
import wave
from pathlib import Path

# La librería de Gemini se carga recién al usarla (tarda casi 5 segundos en la
# Pi Zero): así los programas que solo leen recordatorios, como panel.py,
# no la pagan.

MODELO = "gemini-3.8-live"
VOZ = "Algenib"
CARPETA = Path.home() / "asistente" / "frases"
FRASES = {
    "pregunta": ("¿Es una emergencia? Si apretaste sin querer, tocá el botón. "
                 "Si no, en diez segundos le aviso a tu familia."),
    "cancelado": "Bueno, no aviso nada. Si me necesitás, acá estoy.",
    "avisando": "Aguantá un segundito, le estoy avisando a tu familia.",
    "avisado": ("Listo, ya le avisé a tu familia. Si querés mandarles un mensaje, "
                "tocá el botón y hablá: te escucho diez segundos."),
    "mensaje_mandado": "Ya les mandé lo que me dijiste. Quedate tranquila, ya te van a llamar.",
    "tranquila": "Quedate tranquila, tu familia ya sabe que necesitás ayuda.",
    "confirmado": "¡Muy bien! Gracias por avisarme.",
    "toca_cuando": "Tocá el botón cuando lo hayas hecho.",
    "no_conecta": "No me puedo conectar ahora. Probá de nuevo en un ratito.",
    "pregunta_responder": "¿Querés contestarle? Tocá el botón y hablá.",
    "respuesta_mandada": "Listo, se lo mandé.",
    "te_escucho": "Dale, te escucho.",
    "respuesta_sin_voz": "No te escuché. Si querés contestarle, pedímelo más tarde.",
    "recordatorio_sin_voz": "Tenés un recordatorio, pero no lo puedo leer porque no hay internet.",
    "sin_internet": "No pude avisar porque no hay internet. Sigo intentando. Si podés, llamá por teléfono.",
}


def clave_gemini():
    for linea in (Path.home() / ".config/asistente/secretos.env").read_text().splitlines():
        if linea.startswith("GEMINI_API_KEY="):
            return linea.split("=", 1)[1].strip()


async def voz_en_partes(cliente, texto):
    """La frase dicha con la voz del asistente, en pedacitos de audio (PCM de
    24 kHz) a medida que Gemini los genera: se pueden ir reproduciendo sin
    esperar el final (Gemini genera la voz a la velocidad en que se habla)."""
    from google.genai import types
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=("Hablás en español rioplatense, con calma y calidez. "
                            "Repetí exactamente la frase que te pasen, sin agregar nada."),
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOZ))),
    )
    async with cliente.aio.live.connect(model=MODELO, config=config) as sesion:
        await sesion.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=texto)]))
        async for msg in sesion.receive():
            sc = msg.server_content
            for parte in (sc.model_turn.parts if sc and sc.model_turn else []):
                if parte.inline_data:
                    yield parte.inline_data.data
            if sc and sc.turn_complete:
                break


async def grabar(cliente, texto, destino):
    audio = bytearray()
    async for pedazo in voz_en_partes(cliente, texto):
        audio += pedazo
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes(audio))
    return len(audio) / 48000


async def main():
    CARPETA.mkdir(exist_ok=True)
    from google import genai
    from google.genai import types
    cliente = genai.Client(api_key=clave_gemini(),
                           http_options=types.HttpOptions(api_version="v1beta"))
    elegidas = sys.argv[1:] or list(FRASES)
    for nombre in elegidas:
        texto = FRASES[nombre]
        segundos = await grabar(cliente, texto, CARPETA / f"{nombre}.wav")
        print(f"{nombre:16} {segundos:4.1f} s  «{texto}»")


if __name__ == "__main__":  # así recordatorios.py puede importar grabar() sin correr esto
    asyncio.run(main())
