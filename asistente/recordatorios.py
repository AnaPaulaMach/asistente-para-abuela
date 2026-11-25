"""Recordatorios: diarios o de una sola vez.

Se escriben en ~/.config/asistente/recordatorios.txt, uno por línea, así:

    09:00 Acordate de tomar la pastilla de la presión.      (todos los días)
    27/11 17:00 Hoy viene el médico a las cinco y media.    (solo ese día)
    # las líneas con numeral se ignoran

Ella también los agrega y los borra hablando (herramientas agregar_recordatorio
y borrar_recordatorio de charla.py). Los de una sola vez se borran solos
después de sonar (o si quedaron viejos porque el aparato estaba apagado).

A la hora indicada el asistente se pone lila y dice el texto con la voz del asistente.
Ella confirma con un toque del botón. Si no confirma, lo repite cada 3
minutos; después de 3 veces sin respuesta le avisa a la familia por Telegram.

La voz de cada recordatorio se graba con Gemini apenas aparece en el archivo
(y queda guardada), así suena aunque a esa hora no haya internet.
"""
import asyncio
import hashlib
import time
import unicodedata
from pathlib import Path

import alerta
import frases
import tareas
import telegram_bot
from luces import luz

ARCHIVO = Path.home() / ".config" / "asistente" / "recordatorios.txt"
VOCES = Path.home() / "asistente" / "frases" / "recordatorios"
REPETIR_CADA = 180   # segundos entre repeticiones si no confirma
REINTENTO = 600      # segundos para volver a intentar grabar una voz que falló
VECES = 3            # repeticiones antes de avisar a la familia


def _parsear(linea):
    """Una línea del archivo como {fecha, hora, texto, linea}, o None si no sirve."""
    linea = linea.strip()
    if not linea or linea.startswith("#"):
        return None
    partes = linea.split(" ", 2)
    fecha = None
    if "/" in partes[0]:
        dia, _, mes = partes[0].partition("/")
        if not (dia.isdigit() and mes.isdigit()) or len(partes) < 3:
            print(f"(recordatorio ignorado, la fecha tiene que ser DD/MM: {linea})", flush=True)
            return None
        fecha = f"{int(dia):02d}/{int(mes):02d}"
        partes = partes[1:]
    else:
        partes = linea.split(" ", 1)
    try:
        t = time.strptime(partes[0], "%H:%M")
    except ValueError:
        print(f"(recordatorio ignorado, la hora tiene que ser HH:MM: {linea})", flush=True)
        return None
    texto = partes[1].strip() if len(partes) > 1 else ""
    if not texto:
        return None
    # "9:5" se entiende como 09:05, igual que la hora del reloj.
    return {"fecha": fecha, "hora": f"{t.tm_hour:02d}:{t.tm_min:02d}", "texto": texto, "linea": linea}


def todos():
    if not ARCHIVO.exists():
        return []
    return [r for r in map(_parsear, ARCHIVO.read_text().splitlines()) if r]


def leer():
    """Los de hoy, como [(hora "HH:MM", texto)]: los diarios y los de la fecha de hoy."""
    hoy = time.strftime("%d/%m")
    return [(r["hora"], r["texto"]) for r in todos() if r["fecha"] in (None, hoy)]


def _simple(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _escribir(lineas):
    ARCHIVO.write_text("".join(l + "\n" for l in lineas))
    ARCHIVO.chmod(0o600)   # puede tener datos de salud (remedios, médicos)


def _borrar_voces(textos):
    """Borra la voz grabada de los textos que ya no usa ningún recordatorio."""
    en_uso = {r["texto"] for r in todos()}
    for texto in set(textos) - en_uso:
        voz_de(texto).unlink(missing_ok=True)


def agregar(hora, texto, fecha=None):
    """Agrega uno. Sin fecha: todos los días. Devuelve lo que quedó anotado."""
    r = _parsear(f"{fecha} {hora} {texto}" if fecha else f"{hora} {texto}")
    if r is None:
        raise ValueError("la hora tiene que ser HH:MM (y la fecha DD/MM)")
    linea = (f"{r['fecha']} " if r["fecha"] else "") + f"{r['hora']} {r['texto']}"
    previo = ARCHIVO.read_text() if ARCHIVO.exists() else ""
    ARCHIVO.write_text(previo + ("" if previo.endswith("\n") or not previo else "\n") + linea + "\n")
    ARCHIVO.chmod(0o600)
    return {"fecha": r["fecha"], "hora": r["hora"], "texto": r["texto"]}


def borrar(sobre="", exacto=""):
    """Borra por la línea exacta, o los que tienen todas las palabras de `sobre`."""
    lineas = ARCHIVO.read_text().splitlines() if ARCHIVO.exists() else []
    palabras = [p for p in _simple(sobre).split() if len(p) > 2]
    quedan, borrados = [], []
    for linea in lineas:
        r = _parsear(linea)
        if r and ((exacto and _parsear(exacto) and r["linea"] == _parsear(exacto)["linea"])
                  or (palabras and all(p in _simple(r["texto"]) for p in palabras))):
            borrados.append(r["linea"])
        else:
            quedan.append(linea)
    if borrados:
        _escribir(quedan)
        _borrar_voces(_parsear(l)["texto"] for l in borrados)
    return borrados


def _limpiar_viejos():
    """Saca los de una sola vez que ya pasaron (si el aparato estuvo apagado)."""
    hoy = time.localtime()
    lineas = ARCHIVO.read_text().splitlines() if ARCHIVO.exists() else []
    quedan = []
    for linea in lineas:
        r = _parsear(linea)
        if r and r["fecha"]:
            dia, mes = (int(x) for x in r["fecha"].split("/"))
            # Más de un mes "en el pasado" es del año que viene (diciembre → enero).
            atras = (hoy.tm_mon - mes) % 12
            if atras == 0 and (dia, r["hora"]) < (hoy.tm_mday, time.strftime("%H:%M")) or 0 < atras < 6:
                print(f"(recordatorio vencido, lo saco: {linea})", flush=True)
                continue
        quedan.append(linea)
    if len(quedan) != len(lineas):
        _escribir(quedan)
        _borrar_voces(r["texto"] for r in map(_parsear, lineas) if r and r["linea"] not in quedan)


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
        """Graba la voz de los recordatorios nuevos o cambiados. Devuelve True si
        quedaron todas; si alguna falló (sin internet), bucle() reintenta."""
        VOCES.mkdir(parents=True, exist_ok=True)
        todo_bien = True
        for texto in [r["texto"] for r in todos()]:
            destino = voz_de(texto)
            if not destino.exists():
                try:
                    await frases.grabar(self.cliente, texto, destino)
                    print(f"(voz grabada para «{texto}»)", flush=True)
                except Exception as e:
                    destino.unlink(missing_ok=True)   # un archivo a medias no sirve
                    print(f"(no pude grabar «{texto}»: {e}; reintento en {REINTENTO // 60} min)", flush=True)
                    todo_bien = False
        return todo_bien

    async def bucle(self):
        """Mira el reloj cada 5 segundos y anota los recordatorios de este minuto."""
        tareas.lanzar(self._decir_en_orden(), "decir recordatorios")
        ultimo_minuto, modificado, reintentar, grabando = None, None, 0.0, None
        while True:
            try:
                cambio = ARCHIVO.stat().st_mtime if ARCHIVO.exists() else None
                if grabando and grabando.done():
                    # Terminó de grabar voces: si alguna falló, reintentar más tarde.
                    reintentar = 0.0 if grabando.result() else time.time() + REINTENTO
                    grabando = None
                if grabando is None and (cambio != modificado or (reintentar and time.time() > reintentar)):
                    # En una tarea aparte: si Gemini tarda, el reloj sigue andando.
                    modificado, reintentar = cambio, 0.0
                    grabando = tareas.lanzar(self.preparar(), "voces de recordatorios")
                minuto = time.strftime("%H:%M")
                if minuto != ultimo_minuto:
                    ultimo_minuto = minuto
                    hoy = time.strftime("%d/%m")
                    for r in todos():
                        if r["hora"] == minuto and r["fecha"] in (None, hoy):
                            self.cola.put_nowait(r)
                    _limpiar_viejos()
            except Exception as e:  # un error acá no tiene que tirar abajo la charla
                print(f"(error en recordatorios: {e})", flush=True)
            await asyncio.sleep(5)

    async def _decir_en_orden(self):
        while True:
            r = await self.cola.get()
            try:
                await self.sonar(r["hora"], r["texto"])
            except Exception as e:
                print(f"(error en el recordatorio «{r['texto']}»: {e})", flush=True)
            finally:
                if r["fecha"]:
                    borrar(exacto=r["linea"])  # los de una sola vez se van después de sonar

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
                while alerta.activa:   # en plena emergencia no se repite el recordatorio
                    await asyncio.sleep(2)
                luz("recordatorio")
                if voz.exists():
                    await alerta._correr("aplay", "-q", "-D", alerta.PLACA, str(voz))
                    # Que quede claro que la luz lila espera un toque.
                    await alerta.decir("toca_cuando")
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
