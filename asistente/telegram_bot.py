"""Telegram para el asistente: mandar texto y notas de voz con el bot.

Solo librería estándar. Las funciones son "bloqueantes" (esperan la respuesta
de Telegram); desde asyncio se llaman con asyncio.to_thread.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CONFIG = Path.home() / ".config" / "asistente"


def leer_env(archivo):
    """Lee líneas CLAVE=valor; ignora vacías y comentarios."""
    datos = {}
    if archivo.exists():
        for linea in archivo.read_text().splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                clave, valor = linea.split("=", 1)
                datos[clave.strip()] = valor.strip()
    return datos


def _token():
    return leer_env(CONFIG / "secretos.env")["TELEGRAM_TOKEN"]


def chat_familia():
    """Por ahora, el chat de la nieta; en la etapa g, la lista de contactos."""
    return leer_env(CONFIG / "ajustes.env")["TELEGRAM_CHAT_ID"]


def _pedir(metodo, cuerpo, tipo, espera=20):
    url = f"https://api.telegram.org/bot{_token()}/{metodo}"
    pedido = urllib.request.Request(url, data=cuerpo, headers={"Content-Type": tipo})
    try:
        with urllib.request.urlopen(pedido, timeout=espera) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        # Sin la URL: lleva el token adentro.
        raise RuntimeError(f"Telegram respondió {e.code} en {metodo}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Sin conexión con Telegram ({e.reason})") from None


def mandar_texto(chat_id, texto):
    cuerpo = urllib.parse.urlencode({"chat_id": chat_id, "text": texto}).encode()
    return _pedir("sendMessage", cuerpo, "application/x-www-form-urlencoded")


def mandar_voz(chat_id, ogg, texto=None):
    """Manda un .ogg con Opus como nota de voz.

    Para subir un archivo, HTTP usa "multipart/form-data": el cuerpo va en
    partes separadas por una marca (boundary) que no aparece en los datos.
    """
    marca = uuid.uuid4().hex
    partes = [("chat_id", None, str(chat_id).encode())]
    if texto:
        partes.append(("caption", None, texto.encode()))
    partes.append(("voice", "aviso.ogg", Path(ogg).read_bytes()))
    cuerpo = bytearray()
    for nombre, archivo, datos in partes:
        cuerpo += f"--{marca}\r\n".encode()
        if archivo:
            cuerpo += (f'Content-Disposition: form-data; name="{nombre}"; filename="{archivo}"\r\n'
                       "Content-Type: audio/ogg\r\n\r\n").encode()
        else:
            cuerpo += f'Content-Disposition: form-data; name="{nombre}"\r\n\r\n'.encode()
        cuerpo += datos + b"\r\n"
    cuerpo += f"--{marca}--\r\n".encode()
    return _pedir("sendVoice", bytes(cuerpo), f"multipart/form-data; boundary={marca}", espera=60)
