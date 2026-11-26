"""Las noticias del lugar donde vive ella, con el RSS de Google Noticias.

RSS es un formato que los sitios de noticias publican para que un programa
lea sus titulares: gratis y sin clave. Google Noticias junta los de muchos
diarios; le pedimos los del último día que nombran el lugar (NOTICIAS_LUGAR
en ~/.config/asistente/ajustes.env).

Las noticias policiales y de tragedias se sacan, salvo que ella pregunte
justo por eso: le dan miedo y no hace falta que se entere por un parlante.
"""
import email.utils
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from telegram_bot import CONFIG, leer_env

# Palabras que marcan una noticia que puede asustar (se buscan sin importar mayúsculas).
DELICADAS = (
    "detenid", "detuvieron", "arrest", "asesin", "homicid", "femicid", "crimen", "matar", "mató",
    "muert", "murió", "falleci", "cadáver", "sin vida", "accidente", "choque", "chocó", "vuelco",
    "robo", "robaron", "asalt", "delincu", "violen", "abus", "disparo", "balea", "apuñal",
    "incendio", "tragedia", "herid", "policía", "policial", "narco", "secuestr", "desaparec",
    "morir", "ahog", "grave", "terapia intensiva",
)
# El clima va por consultar_clima, que lo cuenta con calma; acá se saltea
# (y las tormentas le dan miedo).
CLIMA = ("clima", "pronóstico", "tormenta", "smn", "alerta", "granizo", "lluvia", "temperatura")
CANTIDAD = 12
# Palabras que no dicen de qué trata una noticia (para juntar las repetidas).
VACIAS = set("""el la los las un una unos unas de del al a en y o que por para con sin se su sus
    es son lo le les como más pero este esta ya ante tras sobre desde hasta entre""".split())


def _palabras(titulo):
    return {p.strip('.,:;"“”¿?¡!()') for p in titulo.lower().split()} - VACIAS - {""}


def _misma_noticia(a, b):
    """Varios diarios cuentan lo mismo con otro título: si comparten 3 palabras
    que importan (o casi todas las del más corto), es la misma noticia."""
    comunes = len(a & b)
    return comunes >= 3 or comunes >= 0.6 * min(len(a), len(b))


def _es_delicada(titulo):
    t = titulo.lower()
    return any(p in t for p in DELICADAS)


def buscar(tema="", incluir_delicadas=False, dias=2):
    """Devuelve los titulares más nuevos: [{titulo, fuente, hace_horas}]."""
    lugar = leer_env(CONFIG / "ajustes.env").get("NOTICIAS_LUGAR", "").strip()
    if not lugar:
        return {"error": "no está configurado el lugar de las noticias"}
    consulta = f'"{lugar}" {tema}'.strip() + f" when:{dias}d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": consulta, "hl": "es-419", "gl": "AR", "ceid": "AR:es-419"})
    pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(pedido, timeout=10) as r:
        raiz = ET.fromstring(r.read())

    ahora = time.time()
    vistas, lista, sacadas = [], [], 0   # vistas: las palabras de cada noticia ya anotada
    for item in raiz.findall("./channel/item"):
        fuente = item.findtext("source") or ""
        titulo = (item.findtext("title") or "").strip()
        # Google le agrega " - Nombre del diario" al final: se lo sacamos.
        if fuente and titulo.endswith(" - " + fuente):
            titulo = titulo[: -len(" - " + fuente)]
        palabras = _palabras(titulo) - set(_palabras(lugar))
        if not titulo or any(p in titulo.lower() for p in CLIMA) \
                or any(_misma_noticia(palabras, v) for v in vistas):
            continue  # del clima, o la misma noticia contada por otro diario
        vistas.append(palabras)
        if not incluir_delicadas and _es_delicada(titulo):
            sacadas += 1
            continue
        try:
            horas = round((ahora - email.utils.parsedate_to_datetime(item.findtext("pubDate")).timestamp()) / 3600)
        except (TypeError, ValueError):
            horas = None
        lista.append({"titulo": titulo, "fuente": fuente, "hace_horas": horas})

    lista.sort(key=lambda n: n["hace_horas"] if n["hace_horas"] is not None else 99)
    if not lista and dias <= 2 and tema:
        return buscar(tema, incluir_delicadas, dias=7)  # un tema puntual: mirar la semana
    return {"lugar": lugar, "noticias": lista[:CANTIDAD], "sacadas_por_delicadas": sacadas}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(buscar(" ".join(sys.argv[1:])), ensure_ascii=False, indent=2))
