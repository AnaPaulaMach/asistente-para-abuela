"""Volumen del asistente en niveles del 1 al 10.

Lo usan la ruedita del costado (encoder rotativo) y Gemini cuando le piden
"hablá más fuerte". El nivel se guarda en ~/.config/asistente/volumen para que
sobreviva a los reinicios.

Por dentro mueve el control "PCM" del códec (volumen digital, antes del
amplificador): cada nivel son 3 dB, del 1 (-39 dB) al 10 (-12 dB).
3 dB más se escucha como "un poco más fuerte"; 10 dB, como "el doble".
"""
import math
import subprocess
import threading
from pathlib import Path

PLACA = "seeed2micvoicec"
ARCHIVO = Path.home() / ".config" / "asistente" / "volumen"
MINIMO, MAXIMO, INICIAL = 1, 10, 4


def decibeles(nivel):
    return -42 + 3 * nivel


def _pitido(tasa=24000, segundos=0.12, frecuencia=660):
    """Un "bip" corto con subida y bajada suave (sin el clic del corte brusco)."""
    n = int(tasa * segundos)
    datos = bytearray()
    for i in range(n):
        envolvente = min(1.0, i / 200, (n - i) / 200)
        valor = int(12000 * envolvente * math.sin(2 * math.pi * frecuencia * i / tasa))
        datos += valor.to_bytes(2, "little", signed=True)
    return bytes(datos)


class Volumen:
    def __init__(self):
        self.lock = threading.Lock()  # la ruedita y Gemini pueden llegar a la vez
        self.ocupado = lambda: False  # charla.py lo reemplaza: ¿hay mic o parlante en uso?
        self.al_cambiar = None        # charla.py lo usa para mostrar el nivel en las luces
        self.bip = None
        self._sonido = _pitido()
        try:
            self.nivel = int(ARCHIVO.read_text())
        except (OSError, ValueError):
            self.nivel = INICIAL
        self.fijar(self.nivel, pitar=False)

    def fijar(self, nivel, pitar=True):
        with self.lock:
            self.nivel = max(MINIMO, min(MAXIMO, int(nivel)))
            # "--" avisa que lo que sigue no son opciones: si no, "-30dB" se lee como "-3".
            subprocess.run(["amixer", "-q", "-c", PLACA, "--", "sset", "PCM",
                            f"{decibeles(self.nivel)}dB"], check=False)
            ARCHIVO.write_text(str(self.nivel))
        print(f"🔊 Volumen {self.nivel}/10", flush=True)
        if pitar and self.al_cambiar:
            self.al_cambiar(self.nivel)
        if pitar and not self.ocupado():
            self.pitar()
        return self.nivel

    def subir(self, pasos=1):
        return self.fijar(self.nivel + pasos)

    def bajar(self, pasos=1):
        return self.fijar(self.nivel - pasos)

    def pitar(self):
        """Un bip al nuevo volumen, para escuchar cómo quedó."""
        if self.bip and self.bip.poll() is None:
            return  # todavía suena el anterior: no se encimen
        self.bip = subprocess.Popen(
            ["aplay", "-q", "-D", f"plughw:{PLACA}", "-t", "raw", "-f", "S16_LE",
             "-r", "24000", "-c", "1"],
            stdin=subprocess.PIPE, start_new_session=True)
        self.bip.stdin.write(self._sonido)
        self.bip.stdin.close()

    def esperar_pitido(self):
        if self.bip:
            self.bip.wait(timeout=2)
