"""Las personas de su vida, desde ~/.config/asistente/personas.toml (privado).

TOML es un formato de texto pensado para que lo escriba una persona: se lee
como una ficha, y Python lo entiende sin instalar nada (módulo tomllib).
Acá lo convertimos en texto para el prompt, sin teléfonos ni chats de
Telegram: Gemini no los necesita para charlar.
"""
import time
import tomllib
from pathlib import Path

ARCHIVO = Path.home() / ".config" / "asistente" / "personas.toml"


# Los chats de Telegram que el bot aprende solo (cuando alguien de la familia
# le escribe por primera vez) van aparte, en un archivo que vive solo en la Pi:
# así desplegar.sh no los pisa al copiar personas.toml desde la compu.
CHATS = ARCHIVO.with_name("chats-telegram.env")


def _chats_aprendidos():
    datos = {}
    if CHATS.exists():
        for linea in CHATS.read_text().splitlines():
            if "=" in linea:
                nombre, chat = linea.split("=", 1)
                datos[nombre.strip()] = chat.strip()
    return datos


def cargar():
    if not ARCHIVO.exists():
        return {}
    with ARCHIVO.open("rb") as f:
        datos = tomllib.load(f)
    aprendidos = _chats_aprendidos()
    for p in datos.get("persona", []):
        if not p.get("telegram") and p.get("nombre") in aprendidos:
            p["telegram"] = aprendidos[p["nombre"]]
    return datos


def de_telegram(chat_id, usuario=""):
    """¿Quién es este chat? Por su número de chat, o por su usuario de Telegram
    anotado en la ficha (y entonces se guarda el chat para la próxima)."""
    chat_id, usuario = str(chat_id), (usuario or "").lower().lstrip("@")
    datos = cargar()
    for p in datos.get("persona", []):
        if str(p.get("telegram", "")) == chat_id:
            return p
    for p in datos.get("persona", []):
        if usuario and (p.get("telegram_usuario") or "").lower().lstrip("@") == usuario:
            with CHATS.open("a") as f:
                f.write(f"{p['nombre']}={chat_id}\n")
            CHATS.chmod(0o600)
            p["telegram"] = chat_id
            return p
    return None


def _cumple(p):
    """El cumpleaños como "DD/MM" (acepta "5/3"); vacío si falta o está mal."""
    dia, _, mes = (p.get("cumpleanos") or "").strip().partition("/")
    if dia.isdigit() and mes.isdigit():
        return f"{int(dia):02d}/{int(mes):02d}"
    return ""


def para_el_prompt(datos=None):
    datos = cargar() if datos is None else datos
    if not datos:
        return ""
    lineas = []
    ella = datos.get("ella", {})
    if ella:
        texto = f"Ella se llama {ella.get('nombre', '')}"
        if ella.get("apodo"):
            texto += f", le dicen {ella['apodo']}: llamala así"
        if _cumple(ella):
            texto += f". Su cumpleaños es el {_cumple(ella)}"
        lineas.append(texto + ".")
    casa = [p for p in datos.get("persona", []) if p.get("vive_con_ella")]
    resto = [p for p in datos.get("persona", []) if not p.get("vive_con_ella")]
    for titulo, grupo in (("Viven con ella:", casa), ("El resto de su gente:", resto)):
        if grupo:
            lineas.append(titulo)
            for p in grupo:
                texto = f"- {p['nombre']}"
                if p.get("apodo"):
                    texto += f" ({p['apodo']})"
                if p.get("relacion"):
                    texto += f": {p['relacion']}"
                if _cumple(p):
                    texto += f"; cumple el {_cumple(p)}"
                if p.get("notas"):
                    texto += f". {p['notas']}"
                lineas.append(texto)
    hoy = cumplen_hoy(datos)
    if hoy:
        lineas.append(f"¡Hoy cumple años {', '.join(hoy)}! Si viene al caso, recordáselo con alegría.")
    return "\n".join(lineas)


def cumplen_hoy(datos=None):
    datos = cargar() if datos is None else datos
    hoy = time.strftime("%d/%m")
    todos = [datos.get("ella", {})] + datos.get("persona", [])
    return [p.get("apodo") or p["nombre"] for p in todos
            if p.get("nombre") and _cumple(p) == hoy]


if __name__ == "__main__":
    print(para_el_prompt())
