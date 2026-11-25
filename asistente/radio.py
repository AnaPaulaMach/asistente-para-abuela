"""La radio: emisoras por internet que mpv reproduce por el parlante.

Las emisoras están en ~/.config/asistente/radios.toml (ejemplo en ejemplos/):

    [[radio]]
    nombre = "Folklórica"
    url = "https://..."
    descripcion = "Radio Nacional Folklórica: chacarera y folklore"

Mientras suena la radio la placa no puede grabar (un solo reloj): por eso un
toque del botón la apaga y deja hablar. Se apaga sola a las HORAS_MAX horas.
"""
import subprocess
import tomllib
import unicodedata
from pathlib import Path

from luces import luz

ARCHIVO = Path.home() / ".config" / "asistente" / "radios.toml"
SONANDO = Path.home() / ".config" / "asistente" / "radio-sonando"   # para el panel
SALIDA = "alsa/plughw:seeed2micvoicec"
HORAS_MAX = 3


def emisoras():
    if not ARCHIVO.exists():
        return []
    with ARCHIVO.open("rb") as f:
        return [r for r in tomllib.load(f).get("radio", []) if r.get("nombre") and r.get("url")]


def _simple(texto):
    """Minúsculas y sin tildes, para que "folklorica" encuentre "Folklórica"."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def buscar(pedido):
    """La emisora que mejor coincide con lo que pidió; la primera si no dijo cuál."""
    lista = emisoras()
    if not lista:
        return None
    pedido = _simple(pedido or "")
    for r in lista:
        if pedido and (pedido in _simple(r["nombre"]) or _simple(r["nombre"]) in pedido):
            return r
    for r in lista:
        if pedido and any(p in _simple(r.get("descripcion", "")) for p in pedido.split() if len(p) > 3):
            return r
    return None if pedido else lista[0]


class Radio:
    def __init__(self):
        self.proceso = None
        self.nombre = None

    def sonando(self):
        return self.proceso is not None and self.proceso.poll() is None

    def tocar(self, nombre):
        r = buscar(nombre)
        if r is None:
            return None
        self.parar()
        # "timeout" la corta sola a las HORAS_MAX horas, por si queda prendida.
        self.proceso = subprocess.Popen(
            ["timeout", f"{HORAS_MAX}h", "mpv", "--no-video", "--no-terminal",
             f"--audio-device={SALIDA}", "--cache=yes", r["url"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.nombre = r["nombre"]
        SONANDO.write_text(self.nombre)
        luz("radio")
        print(f"📻 Radio: {self.nombre}", flush=True)
        return self.nombre

    def parar(self):
        """Apaga la radio. Devuelve el nombre de la que sonaba (o None)."""
        nombre = self.nombre if self.sonando() else None
        if self.proceso is not None:
            if self.proceso.poll() is None:
                self.proceso.terminate()
                try:
                    self.proceso.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proceso.kill()
            self.proceso = None
        self.nombre = None
        SONANDO.unlink(missing_ok=True)
        if nombre:
            print("📻 Radio apagada", flush=True)
        return nombre
