"""Avisos de estado por Telegram, para enterarse sin tener el widget abierto.

- Se prendió la Pi (no un simple reinicio de la charla): puede haber sido un
  corte de luz.
- Temperatura de TEMP_MAX °C o más (normal: 40-55 °C; a los 80 se frena sola).
- Baja tensión: el cargador o el cable no dan la corriente que hace falta.
- Estuvo sin internet: sin internet no se puede avisar, así que avisa cuando
  vuelve, con desde y hasta cuándo.

Cada aviso se repite como mucho una vez por hora (la baja tensión, una por día).
"""
import asyncio
import re
import subprocess
import time
from pathlib import Path

import telegram_bot

TEMP_MAX = 75
REVISAR_CADA = 60          # segundos
SIN_INTERNET_MIN = 2       # minutos sin internet a partir de los que se avisa


def _correr(*comando):
    return subprocess.run(comando, capture_output=True, text=True).stdout.strip()


def temperatura():
    t = re.search(r"([0-9.]+)", _correr("vcgencmd", "measure_temp"))
    return float(t.group(1)) if t else None


def baja_tension_ahora():
    """get_throttled: el bit 0 es "baja tensión en este momento"."""
    valor = re.search(r"0x([0-9a-fA-F]+)", _correr("vcgencmd", "get_throttled"))
    return bool(valor and int(valor.group(1), 16) & 0x1)


class Vigilante:
    def __init__(self, nombre="Beto"):
        self.nombre = nombre
        self._ultimo = {}            # tipo de aviso -> cuándo se mandó
        self.sin_internet_desde = None

    def _avisar(self, tipo, texto, cada=3600):
        if time.time() - self._ultimo.get(tipo, 0) < cada:
            return
        try:
            telegram_bot.mandar_texto(telegram_bot.chat_familia(), texto)
            self._ultimo[tipo] = time.time()
        except RuntimeError as e:
            print(f"(vigilante: no pude avisar «{tipo}»: {e})", flush=True)

    def conexion(self, anda):
        """mensajes.py avisa si llegar a Telegram anduvo o no."""
        if not anda:
            if self.sin_internet_desde is None:
                self.sin_internet_desde = time.time()
            return
        if self.sin_internet_desde is not None:
            desde, self.sin_internet_desde = self.sin_internet_desde, None
            if time.time() - desde >= SIN_INTERNET_MIN * 60:
                inicio = time.strftime("%H:%M", time.localtime(desde))
                self._avisar("internet", f"📶 {self.nombre} estuvo sin internet de {inicio} a "
                             f"{time.strftime('%H:%M')}. Ya volvió.", cada=0)

    async def vigilar(self):
        prendida = float(Path("/proc/uptime").read_text().split()[0])
        if prendida < 300:
            await asyncio.to_thread(
                self._avisar, "encendido",
                f"🔌 {self.nombre} se prendió ({time.strftime('%H:%M')}). Si no lo reiniciaste vos, "
                "puede haberse cortado la luz.")
        while True:
            try:
                temp = await asyncio.to_thread(temperatura)
                if temp is not None and temp >= TEMP_MAX:
                    await asyncio.to_thread(
                        self._avisar, "temperatura",
                        f"🌡 {self.nombre} está a {temp:.0f} °C (lo normal es 40-55). ¿Le da el sol o "
                        "está tapado? A los 80 °C se frena solo.")
                if await asyncio.to_thread(baja_tension_ahora):
                    await asyncio.to_thread(
                        self._avisar, "tension",
                        f"⚡ {self.nombre} tiene baja tensión: el cargador o el cable no dan la corriente "
                        "que necesita. Probá con otro.", 86400)
            except Exception as e:  # un error acá no tiene que afectar la charla
                print(f"(vigilante: {e})", flush=True)
            await asyncio.sleep(REVISAR_CADA)
