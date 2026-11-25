#!/usr/bin/env python3
"""Genera la misma frase con varias voces de Gemini Live, para elegir una.

Sin argumentos usa la lista VOCES; si no, las voces que se le pasen:
    ~/asistente/venv/bin/python ~/asistente/voces.py Algenib Schedar
Con --estilo se le pide cómo decirla (las muestras llevan "-estilo" en el nombre):
    ~/asistente/venv/bin/python ~/asistente/voces.py --estilo="con picardía" Puck Gacrux

Guarda cada muestra en ~/asistente/voces/<Voz>.wav (24 kHz, mono). Después se
escuchan con:  for f in ~/asistente/voces/*.wav; do echo "$f"; aplay -q -D plughw:seeed2micvoicec "$f"; sleep 1; done
"""
import asyncio
import subprocess
import sys
import wave
from pathlib import Path

from google import genai
from google.genai import types

MODELO = "gemini-3.8-live"
# Voces y cómo las describe Google (traducido).
VOCES = {
    "Sulafat": "cálida",
    "Vindemiatrix": "suave, amable",
    "Achernar": "suave",
    "Gacrux": "madura",
    "Achird": "amigable",
    "Aoede": "ligera",
    "Kore": "firme",
    "Charon": "informativa (masculina)",
}
FRASE = "Hola, querida. ¿Cómo amaneciste hoy? Si querés, charlamos un ratito."
CARPETA = Path.home() / "asistente" / "voces"


def clave_gemini():
    for linea in (Path.home() / ".config/asistente/secretos.env").read_text().splitlines():
        if linea.startswith("GEMINI_API_KEY="):
            return linea.split("=", 1)[1].strip()


async def muestra(cliente, voz, estilo=None):
    instruccion = "Hablás en español rioplatense. Repetí exactamente la frase que te pasen, sin agregar nada."
    if estilo:
        instruccion += f" Decila {estilo}."
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=instruccion,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voz))),
    )
    audio = bytearray()
    async with cliente.aio.live.connect(model=MODELO, config=config) as sesion:
        await sesion.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=FRASE)]))
        async for msg in sesion.receive():
            sc = msg.server_content
            for parte in (sc.model_turn.parts if sc and sc.model_turn else []):
                if parte.inline_data:
                    audio += parte.inline_data.data
            if sc and sc.turn_complete:
                break
    nombre = f"{voz}-estilo" if estilo else voz
    with wave.open(str(CARPETA / f"{nombre}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes(audio))
    return len(audio) / 48000


async def main():
    CARPETA.mkdir(exist_ok=True)
    cliente = genai.Client(api_key=clave_gemini(),
                           http_options=types.HttpOptions(api_version="v1beta"))
    estilo = None
    nombres = []
    for arg in sys.argv[1:]:
        if arg.startswith("--estilo="):
            estilo = arg.split("=", 1)[1]
        else:
            nombres.append(arg)
    voces = {v: VOCES.get(v, "") for v in nombres} or VOCES
    for voz, descripcion in voces.items():
        try:
            segundos = await muestra(cliente, voz, estilo)
            print(f"{voz:13} ({descripcion}): {segundos:.1f} s", flush=True)
            # La escuchamos enseguida, así se puede comparar sin otro comando.
            nombre = f"{voz}-estilo" if estilo else voz
            subprocess.run(["aplay", "-q", "-D", "plughw:seeed2micvoicec",
                            str(CARPETA / f"{nombre}.wav")])
        except Exception as e:
            print(f"{voz:13}: no disponible ({str(e)[:60]})")


asyncio.run(main())
