#!/usr/bin/env python3
"""Etapa b: el asistente y Telegram.

- Al arrancar te manda "hola" por Telegram.
- Si le mandás un audio (nota de voz), lo reproduce por el parlante.
- Si le mandás texto, te contesta que lo recibió.
- Solo hace caso a TU chat: los mensajes de cualquier otra persona se ignoran.

Usa solo la librería estándar de Python: habla con la API de Telegram por HTTPS.
La primera vez, si no sabe cuál es tu chat, te pide que le escribas al bot y lo guarda.
Se corta con Ctrl+C.
"""
import json
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG = Path.home() / ".config" / "asistente"
SECRETOS = CONFIG / "secretos.env"  # TELEGRAM_TOKEN (lo escribe la usuaria, permisos 600)
AJUSTES = CONFIG / "ajustes.env"        # TELEGRAM_CHAT_ID (no es secreto, lo guarda este programa)
PARLANTE = "plughw:seeed2micvoicec"


def leer_env(archivo):
    """Lee líneas CLAVE=valor; ignora vacías y comentarios."""
    datos = {}
    if archivo.exists():
        for linea in archivo.read_text().splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                clave, valor = linea.split("=", 1)
                datos[clave.strip()] = valor.strip()
    return datos


TOKEN = leer_env(SECRETOS)["TELEGRAM_TOKEN"]


def api(metodo, espera=10, **params):
    """Llama a un método de la API de Telegram y devuelve el campo "result".

    Los errores se muestran sin la URL, porque la URL lleva el token adentro.
    """
    url = f"https://api.telegram.org/bot{TOKEN}/{metodo}"
    datos = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(url, data=datos, timeout=espera) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram respondió {e.code} en {metodo}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Sin conexión con Telegram ({e.reason})") from None


def descargar(file_id, destino):
    """Los archivos se piden en dos pasos: getFile da la ruta y después se baja."""
    ruta = api("getFile", file_id=file_id)["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{ruta}"
    with urllib.request.urlopen(url, timeout=30) as r:
        destino.write_bytes(r.read())


def reproducir(ogg):
    """Las notas de voz vienen en Opus (dentro de un .ogg): opusdec las pasa a WAV."""
    wav = ogg.with_suffix(".wav")
    # 48 kHz: el códec de la placa usa un solo reloj; conviene usar siempre la misma frecuencia.
    subprocess.run(["opusdec", "--quiet", "--rate", "48000", str(ogg), str(wav)], check=True)
    subprocess.run(["aplay", "-q", "-D", PARLANTE, str(wav)], check=True)


def descubrir_chat():
    """Espera el primer mensaje, muestra de quién es y pregunta si es tu chat."""
    print("No sé cuál es tu chat. Mandale cualquier mensaje al bot desde Telegram...")
    desde = 0
    while True:
        for u in api("getUpdates", espera=40, offset=desde, timeout=30):
            desde = u["update_id"] + 1
            chat = (u.get("message") or {}).get("chat")
            if not chat:
                continue
            nombre = chat.get("first_name") or chat.get("title")
            if input(f"Llegó un mensaje de «{nombre}» (chat {chat['id']}). ¿Sos vos? (s/n): ") == "s":
                with AJUSTES.open("a") as f:
                    f.write(f"TELEGRAM_CHAT_ID={chat['id']}\n")
                # Confirmamos los mensajes leídos para que no vuelvan a llegar.
                api("getUpdates", offset=desde, timeout=0)
                return str(chat["id"])


def main():
    chat_id = leer_env(AJUSTES).get("TELEGRAM_CHAT_ID") or descubrir_chat()
    api("sendMessage", chat_id=chat_id, text="👋 Hola, soy tu asistente. Mandame una nota de voz y la reproduzco.")
    print("Mandé el hola. Esperando mensajes (Ctrl+C para salir)...")

    desde = 0
    while True:
        # "Long polling": Telegram tiene la conexión abierta hasta 30 s y responde
        # apenas llega algo. Así nos enteramos al instante sin preguntar a cada rato.
        for u in api("getUpdates", espera=40, offset=desde, timeout=30):
            # offset = último + 1: le dice a Telegram que esos mensajes ya los procesamos.
            desde = u["update_id"] + 1
            m = u.get("message") or {}
            if str(m.get("chat", {}).get("id")) != chat_id:
                continue  # alguien que no sos vos: se ignora
            audio = m.get("voice") or m.get("audio")
            if audio:
                print(f"Llegó un audio de {audio.get('duration', '?')} s, reproduciendo...")
                with tempfile.TemporaryDirectory() as tmp:
                    ogg = Path(tmp) / "audio.ogg"
                    descargar(audio["file_id"], ogg)
                    reproducir(ogg)
                api("sendMessage", chat_id=chat_id, text="🔊 Listo, ya lo escuché.")
            elif "text" in m:
                print(f"Llegó texto: {m['text']}")
                api("sendMessage", chat_id=chat_id, text=f"Recibí: {m['text']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nChau.")
