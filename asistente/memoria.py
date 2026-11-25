"""La memoria del asistente: notas cortas de lo que ella le cuenta.

Gemini no recuerda nada entre una charla y otra. Cuando ella cuenta algo que
vale la pena (una visita, cómo se siente, un plan, algo que le gusta), Gemini
usa la herramienta `recordar` y la nota se guarda acá; al empezar cada charla,
las notas van en el prompt. Si pide "olvidate de eso", usa `olvidar`.

Las notas viven SOLO en la Pi (~/.config/asistente/memoria.md, permisos 600):
son charlas privadas. Se guardan las últimas MAXIMO; las más viejas se borran.
"""
import time
import unicodedata

from telegram_bot import CONFIG

ARCHIVO = CONFIG / "memoria.md"
MAXIMO = 80          # notas guardadas
EN_EL_PROMPT = 40    # las más nuevas van en cada charla (cada una suma unos tokens)


def _simple(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def notas():
    if not ARCHIVO.exists():
        return []
    return [l[2:].strip() for l in ARCHIVO.read_text().splitlines() if l.startswith("- ")]


def _guardar(lista):
    ARCHIVO.write_text("".join(f"- {n}\n" for n in lista[-MAXIMO:]))
    ARCHIVO.chmod(0o600)


def recordar(nota):
    nota = " ".join(nota.split())
    if not nota:
        return {"error": "la nota está vacía"}
    lista = notas()
    if any(_simple(nota) in _simple(n) for n in lista[-10:]):
        return {"ok": True, "nota": "ya lo tenía anotado"}
    lista.append(f"{time.strftime('%d/%m')}: {nota}")
    _guardar(lista)
    print(f"📝 Nota: {nota}", flush=True)
    return {"ok": True}


def olvidar(sobre):
    """Borra las notas que tienen todas las palabras importantes de `sobre`."""
    palabras = [p for p in _simple(sobre).split() if len(p) > 3]
    if not palabras:
        return {"error": "decime de qué es la nota que hay que olvidar"}
    lista = notas()
    quedan = [n for n in lista if not all(p in _simple(n) for p in palabras)]
    _guardar(quedan)
    borradas = len(lista) - len(quedan)
    print(f"📝 Olvidadas {borradas} notas sobre «{sobre}»", flush=True)
    return {"ok": True, "borradas": borradas}


def para_el_prompt():
    lista = notas()[-EN_EL_PROMPT:]
    if not lista:
        return ""
    return "Cosas que te contó en otras charlas (tus notas):\n" + "\n".join(f"- {n}" for n in lista)
