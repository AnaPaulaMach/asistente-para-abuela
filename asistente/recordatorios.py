"""Etapa f: recordatorios diarios.

Se escriben en ~/.config/asistente/recordatorios.txt, uno por línea, así:

    09:00 Acordate de tomar la pastilla de la presión.
    13:00 Es hora de almorzar.
    # las líneas con numeral se ignoran

A la hora indicada el asistente se pone lila y dice el texto con la voz del asistente.
Ella confirma con un toque del botón. Si no confirma, lo repite cada 3
minutos; después de 3 veces sin respuesta le avisa a la familia por Telegram.

La voz de cada recordatorio se graba con Gemini apenas aparece en el archivo
(y queda guardada), así suena aunque a esa hora no haya internet.
"""
import asyncio
import hashlib
import time
from pathlib import Path

import alerta
import frases
import telegram_bot
from luces import luz

ARCHIVO = Path.home() / ".config" / "asistente" / "recordatorios.txt"
VOCES = Path.home() / "asistente" / "frases" / "recordatorios"
REPETIR_CADA = 180   # segundos entre repeticiones si no confirma
VECES = 3            # repeticiones antes de avisar a la familia


def leer():
    """Devuelve [(hora "HH:MM", texto)]; ignora líneas mal escritas."""
    lista = []
    if ARCHIVO.exists():
        for linea in ARCHIVO.read_text().splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            hora, _, texto = linea.partition(" ")
            try:
                t = time.strptime(hora, "%H:%M")
            except ValueError:
                print(f"(recordatorio ignorado, la hora tiene que ser HH:MM: {linea})", flush=True)
                continue
            if texto.strip():
                # "9:5" se entiende como 09:05, igual que la hora del reloj.
                lista.append((f"{t.tm_hour:02d}:{t.tm_min:02d}", texto.strip()))
    return lista


def voz_de(texto):
    # El nombre del archivo sale de un "hash" del texto y la voz: si cambia
    # cualquiera de los dos, es otro archivo y se vuelve a grabar solo.
    nombre = hashlib.sha1(f"{frases.VOZ}|{texto}".encode()).hexdigest()[:12]
    return VOCES / f"{nombre}.wav"


class Recordatorios:
    def __init__(self, cliente, ocupado):
        self.cliente = cliente
        self.ocupado = ocupado      # función: ¿hay charla o emergencia en curso?
        self.confirmacion = None    # asyncio.Event mientras espera el toque
        # El reloj anota en la cola y otra tarea los dice de a uno: así uno que
        # espera confirmación no hace perder el siguiente.
        self.cola = asyncio.Queue()
        self.radio = None           # la Radio de charla.py: se pausa durante el recordatorio

    def confirmar(self):
        """Lo llama charla.py ante un toque corto. True si era para un recordatorio."""
        if self.confirmacion and not self.confirmacion.is_set():
            self.confirmacion.set()
            return True
        return False

    async def preparar(self):
        """Graba la voz de los recordatorios nuevos o cambiados."""
        VOCES.mkdir(parents=True, exist_ok=True)
        for _, texto in leer():
            destino = voz_de(texto)
            if not destino.exists():
                try:
                    await frases.grabar(self.cliente, texto, destino)
                    print(f"(voz grabada para «{texto}»)", flush=True)
                except Exception as e:
                    print(f"(no pude grabar «{texto}»: {e}; lo intento más tarde)", flush=True)

    async def bucle(self):
        """Mira el reloj cada 5 segundos y anota los recordatorios de este minuto."""
        asyncio.create_task(self._decir_en_orden())
        ultimo_minuto, modificado = None, None
        while True:
            try:
                cambio = ARCHIVO.stat().st_mtime if ARCHIVO.exists() else None
                if cambio != modificado:  # el archivo cambió: grabar lo nuevo
                    modificado = cambio
                    await self.preparar()
                minuto = time.strftime("%H:%M")
                if minuto != ultimo_minuto:
                    ultimo_minuto = minuto
                    for hora, texto in leer():
                        if hora == minuto:
                            self.cola.put_nowait((hora, texto))
            except Exception as e:  # un error acá no tiene que tirar abajo la charla
                print(f"(error en recordatorios: {e})", flush=True)
            await asyncio.sleep(5)

    async def _decir_en_orden(self):
        while True:
            hora, texto = await self.cola.get()
            try:
                await self.sonar(hora, texto)
            except Exception as e:
                print(f"(error en el recordatorio «{texto}»: {e})", flush=True)

    async def sonar(self, hora, texto):
        while self.ocupado():  # si está charlando o en una emergencia, espera
            await asyncio.sleep(5)
        print(f"⏰ Recordatorio: {texto}", flush=True)
        # La placa reproduce una sola cosa: si suena la radio, se pausa y vuelve después.
        pausada = self.radio.parar() if self.radio and self.radio.sonando() else None
        voz = voz_de(texto)
        self.confirmacion = asyncio.Event()
        try:
            for _ in range(VECES):
                luz("recordatorio")
                if voz.exists():
                    await alerta._correr("aplay", "-q", "-D", alerta.PLACA, str(voz))
                else:
                    await alerta.decir("recordatorio_sin_voz")
                try:
                    await asyncio.wait_for(self.confirmacion.wait(), timeout=REPETIR_CADA)
                    print("   ✓ Confirmado.", flush=True)
                    await alerta.decir("confirmado")
                    return
                except asyncio.TimeoutError:
                    pass
            print("   ✗ No confirmó: aviso a la familia.", flush=True)
            try:
                await asyncio.to_thread(
                    telegram_bot.mandar_texto, telegram_bot.chat_familia(),
                    f"⏰ Tu abuela no confirmó el recordatorio de las {hora}: «{texto}»")
            except RuntimeError as e:
                print(f"   ✗ {e}", flush=True)
        finally:
            self.confirmacion = None
            if pausada:
                self.radio.tocar(pausada)
            else:
                luz("esperando")
