"""'Decile a mi nieta que me llame': el asistente no llama, pero avisa por Telegram.

Si la persona que nombra tiene su chat de Telegram en personas.toml
(`telegram`), el aviso le llega a ella. Si no, le llega a la familia
(TELEGRAM_CHAT_ID), con el teléfono de esa persona si está anotado, para
que la llame o le pase el mensaje.

Para no mandar diez avisos si lo pide varias veces seguidas, cada persona
recibe como mucho uno cada ESPERA minutos.
"""
import time
import unicodedata

import personas
import telegram_bot

ESPERA = 10   # minutos entre avisos a la misma persona
_ultimo = {}  # persona -> cuándo se le avisó


def _simple(texto):
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").strip()


def _buscar(nombre, datos):
    buscado = _simple(nombre)
    if not buscado:
        return None
    for p in datos.get("persona", []):
        if buscado in (_simple(p.get("nombre")), _simple(p.get("apodo"))) \
                or buscado == _simple(p.get("nombre")).split(" ")[0]:
            return p
    return None


def pedir(persona="", motivo=""):
    datos = personas.cargar()
    ella = datos.get("ella", {})
    quien_pide = ella.get("apodo") or ella.get("nombre") or "Tu abuela"
    elegida = _buscar(persona, datos)
    nombre = elegida["nombre"] if elegida else (persona.strip() or "")

    clave = _simple(nombre) or "familia"
    if time.monotonic() - _ultimo.get(clave, -1e9) < ESPERA * 60:
        return {"ok": True, "avisado": nombre or "la familia", "nota": "ya se había avisado hace un ratito"}

    hora = time.strftime("%H:%M")
    if elegida and elegida.get("telegram"):
        destino, quien = elegida["telegram"], elegida["nombre"]
        texto = f"📞 {quien_pide} quiere que la llames ({hora})."
    else:
        destino, quien = telegram_bot.chat_familia(), "la familia"
        con = f" con {nombre}" if nombre else ""
        texto = f"📞 {quien_pide} quiere hablar{con} ({hora}): ¿la llamás?"
        if elegida and elegida.get("telefono"):
            texto += f" Teléfono de {nombre}: {elegida['telefono']}."
    if motivo.strip():
        texto += f"\nDice: «{motivo.strip()}»"

    telegram_bot.mandar_texto(destino, texto)
    _ultimo[clave] = time.monotonic()
    if quien == "la familia" and nombre:
        return {"ok": True, "avisado": "la familia", "nota": f"{nombre} no tiene Telegram: le avisé a la familia para que la llame"}
    return {"ok": True, "avisado": quien}
