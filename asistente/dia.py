"""El "buen día" y el chequeo de que está bien.

- BUEN_DIA (hora en ajustes.env, por defecto 09:00): el asistente la saluda con
  el clima del día (sin asustar con tormentas), quién cumple años y cuántos
  recordatorios tiene, y la invita a charlar.
- CHEQUEO (por defecto 11:00): si desde la mañana no tocó el botón ni giró la
  ruedita, le avisa a la familia por Telegram. Un aviso por día como mucho.
  No le pide nada a ella: es una red de seguridad tranquila.
"""
import asyncio
import time

import clima
import frases
import personas
import recordatorios
import telegram_bot
from luces import luz

DESDE = 6   # la "mañana" empieza a esta hora: lo de la noche anterior no cuenta


def _ajuste(clave, defecto):
    return telegram_bot.leer_env(telegram_bot.CONFIG / "ajustes.env").get(clave, defecto).strip()


def _clima_tranquilo():
    """El pronóstico en una frase calma: la lluvia y la tormenta se nombran suave."""
    try:
        d = clima.consultar()
        hoy = d["hoy"]
    except Exception:
        return ""
    cielo = hoy["cielo"]
    if "tormenta" in cielo or "fuerte" in cielo or "chaparrones" in cielo:
        cielo = "con algo de lluvia"
    return f"Hoy va a estar {cielo}, con una máxima de {hoy['maxima']} grados."


class Dia:
    def __init__(self, cliente, ocupado, radio):
        self.cliente = cliente
        self.ocupado = ocupado
        self.radio = radio
        self.ultima_senal = 0.0      # la última vez que tocó el botón o giró la ruedita
        self._hecho = {}             # "saludo"/"chequeo" -> fecha en que se hizo

    def senal(self):
        """charla.py la llama con cada toque y con cada giro de la ruedita."""
        self.ultima_senal = time.time()

    def _toca(self, que, hora):
        hoy = time.strftime("%d/%m")
        if self._hecho.get(que) == hoy or time.strftime("%H:%M") < hora:
            return False
        # Solo en los primeros 30 minutos: si la Pi se prende a la tarde, no saluda "buen día".
        h, m = (int(x) for x in hora.split(":"))
        if time.time() - time.mktime(time.localtime()[:3] + (h, m, 0, 0, 0, -1)) > 1800:
            self._hecho[que] = hoy
            return False
        return True

    async def bucle(self):
        while True:
            try:
                if self._toca("saludo", _ajuste("BUEN_DIA", "09:00")):
                    while self.ocupado():
                        await asyncio.sleep(5)
                    await self.saludar()
                    self._hecho["saludo"] = time.strftime("%d/%m")
                if self._toca("chequeo", _ajuste("CHEQUEO", "11:00")):
                    self._hecho["chequeo"] = time.strftime("%d/%m")
                    await asyncio.to_thread(self.chequear)
            except Exception as e:
                print(f"(día: {e})", flush=True)
            await asyncio.sleep(20)

    async def saludar(self):
        ella = personas.cargar().get("ella", {})
        nombre = ella.get("apodo") or ella.get("nombre") or ""
        partes = [f"Buen día, {nombre}." if nombre else "Buen día."]
        partes.append(await asyncio.to_thread(_clima_tranquilo))
        cumplen = personas.cumplen_hoy()
        if cumplen:
            partes.append(f"Hoy cumple años {' y '.join(cumplen)}.")
        cuantos = len(recordatorios.leer())
        if cuantos:
            partes.append("Hoy tenés un recordatorio." if cuantos == 1 else f"Hoy tenés {cuantos} recordatorios.")
        partes.append("Si querés charlar, tocá el botón.")
        texto = " ".join(p for p in partes if p)
        pausada = self.radio.parar() if self.radio and self.radio.sonando() else None
        print(f"☀️  {texto}", flush=True)
        luz("hablando")
        try:
            await frases.decir_en_vivo(self.cliente, texto)
        finally:
            if pausada:
                self.radio.tocar(pausada)
            else:
                luz("esperando")

    def chequear(self):
        manana = time.mktime(time.localtime()[:3] + (DESDE, 0, 0, 0, 0, -1))
        if self.ultima_senal >= manana:
            return
        ella = personas.cargar().get("ella", {})
        nombre = ella.get("apodo") or ella.get("nombre") or "Tu abuela"
        telefono = f" Su teléfono: {ella['telefono']}." if ella.get("telefono") else ""
        print("☀️  Chequeo: no hubo señales esta mañana, aviso a la familia", flush=True)
        telegram_bot.mandar_texto(
            telegram_bot.chat_familia(),
            f"☀️ {nombre} todavía no habló con el asistente hoy ({time.strftime('%H:%M')}): "
            f"no tocó el botón ni el volumen desde la mañana. ¿La llamás?{telefono}")
