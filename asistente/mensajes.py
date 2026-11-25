"""Mensajes de la familia por Telegram, dichos en voz alta, y respuestas de ella.

- Alguien de la familia le escribe o le manda un audio al bot: el asistente
  se lo dice a ella ("Te llegó un mensaje de tu nieta. Dice: ...") y le
  confirma al que lo mandó que ya se lo dijo.
- Solo la familia: los chats anotados en personas.toml, o quien tenga su
  usuario de Telegram anotado ahí (la primera vez se guarda su chat). A
  cualquier otro se lo ignora, y a la familia le llega un aviso.
- Ella contesta hablando ("decile a mi hija que gracias"): la herramienta
  mandar_mensaje de charla.py usa mandar().
- Los mensajes del día quedan anotados para el prompt: "¿qué me dijo?".
"""
import asyncio
import hashlib
import json
import tempfile
import time
from pathlib import Path

import alerta
import frases
import personas
import telegram_bot
from llamadas import _buscar
from luces import luz

CASA = Path.home() / "asistente"
VOCES = CASA / "frases" / "mensajes"            # avisos grabados ("Te llegó un audio de ...")
RECIENTES = telegram_bot.CONFIG / "mensajes-recientes.json"
LARGO_MAX = 600                                   # caracteres: un mensaje más largo se corta
VIEJO = 10                                        # minutos: un mensaje más viejo no se dice
ESPERA_RESPUESTA = 15                             # segundos para tocar el botón y contestar


def _ella():
    e = personas.cargar().get("ella", {})
    return e.get("apodo") or e.get("nombre") or "tu abuela"


def _nombre(p):
    return p.get("apodo") or p["nombre"]


def recientes(horas=24):
    """Los mensajes de las últimas `horas`, para el prompt."""
    try:
        lista = json.loads(RECIENTES.read_text())
    except (OSError, ValueError):
        return []
    return [m for m in lista if time.time() - m["cuando"] < horas * 3600]


def _anotar(de, texto):
    lista = recientes() + [{"cuando": time.time(), "hora": time.strftime("%H:%M"), "de": de, "texto": texto}]
    RECIENTES.write_text(json.dumps(lista[-20:], ensure_ascii=False))
    RECIENTES.chmod(0o600)


def mandar(persona, texto):
    """Lo que ella le dice a alguien. Le llega a esa persona si el bot conoce su
    chat; si no, a la familia, aclarando para quién es."""
    texto = texto.strip()
    if not texto:
        return {"error": "no hay nada para mandar"}
    elegida = _buscar(persona, personas.cargar())
    if elegida and elegida.get("telegram"):
        telegram_bot.mandar_texto(elegida["telegram"], f"💬 {_ella()} dice: {texto}")
        return {"ok": True, "mandado_a": _nombre(elegida)}
    para = _nombre(elegida) if elegida else persona.strip()
    telegram_bot.mandar_texto(telegram_bot.chat_familia(),
                              f"💬 {_ella()} le manda a {para or 'la familia'}: {texto}"
                              + (f"\n({para} no tiene Telegram con el asistente: ¿se lo pasás?)" if para else ""))
    return {"ok": True, "mandado_a": "la familia", "nota": f"{para} no tiene Telegram: se lo mandé a la familia" if para else ""}


class Mensajes:
    def __init__(self, cliente, ocupado, radio):
        self.cliente = cliente
        self.ocupado = ocupado        # función: ¿hay charla, emergencia o recordatorio en curso?
        self.radio = radio
        self.entregando = False
        self.esperando_toque = False  # preguntó "¿querés contestarle?" y espera un toque
        self._toque = None
        self._cancelado = False
        self.cola = asyncio.Queue()
        self._desconocidos = {}       # chat -> cuándo se avisó (un aviso por hora)

    async def escuchar(self):
        """Espera mensajes de Telegram todo el tiempo y los pone en la cola."""
        asyncio.create_task(self._entregar_en_orden())
        while True:
            try:
                for m in await asyncio.to_thread(telegram_bot.recibir, 30):
                    await self._recibido(m)
            except Exception as e:  # sin internet, etc.: reintenta en un rato
                print(f"(mensajes: {e})", flush=True)
                await asyncio.sleep(20)

    async def _recibido(self, m):
        chat = m.get("chat", {})
        de = m.get("from", {})
        persona = await asyncio.to_thread(personas.de_telegram, chat.get("id"), de.get("username"))
        if persona is None:
            await self._desconocido(chat, de)
            return
        nombre = _nombre(persona)
        if time.time() - m.get("date", time.time()) > VIEJO * 60:
            # Llegó mientras el aparato estaba apagado o sin internet: no lo dice de golpe.
            await asyncio.to_thread(telegram_bot.mandar_texto, chat["id"],
                                    f"Recién lo veo (el aparato estuvo sin conexión). Si todavía querés, mandámelo de nuevo.")
            return
        if m.get("text", "").startswith("/"):
            # /start: lo manda Telegram la primera vez que alguien abre el bot.
            await asyncio.to_thread(telegram_bot.mandar_texto, chat["id"],
                                    f"Hola, {nombre}: lo que me mandes (texto o audio) se lo digo a {_ella()}.")
            return
        audio = m.get("voice") or m.get("audio")
        if audio:
            self.cola.put_nowait({"chat": chat["id"], "de": nombre, "audio": audio["file_id"]})
        elif m.get("text"):
            self.cola.put_nowait({"chat": chat["id"], "de": nombre, "texto": m["text"][:LARGO_MAX]})
        else:
            await asyncio.to_thread(telegram_bot.mandar_texto, chat["id"],
                                    "Solo puedo pasarle textos y audios.")
        print(f"✉️  Mensaje de {nombre}", flush=True)

    async def _desconocido(self, chat, de):
        quien = " ".join(x for x in (de.get("first_name"), de.get("last_name")) if x) or "alguien"
        usuario = f" (@{de['username']})" if de.get("username") else ""
        print(f"(mensaje de un desconocido: {quien}{usuario}, ignorado)", flush=True)
        if time.time() - self._desconocidos.get(chat.get("id"), 0) < 3600:
            return
        self._desconocidos[chat.get("id")] = time.time()
        try:
            await asyncio.to_thread(
                telegram_bot.mandar_texto, telegram_bot.chat_familia(),
                f"👤 {quien}{usuario} le escribió al asistente y no está en la lista: no se lo pasé a {_ella()}. "
                "Si es de la familia, anotá su usuario de Telegram en su ficha (telegram_usuario).")
        except RuntimeError:
            pass

    async def _voz(self, texto, guardar=False):
        """El texto dicho con la voz del asistente (Gemini). Los avisos fijos
        ("Te llegó un audio de ...") se guardan para no pedirlos cada vez."""
        nombre = hashlib.sha1(f"{frases.VOZ}|{texto}".encode()).hexdigest()[:12] + ".wav"
        destino = (VOCES if guardar else Path(tempfile.gettempdir())) / nombre
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            await frases.grabar(self.cliente, texto, destino)
        return destino

    async def _tocar(self, wav):
        await alerta._correr("aplay", "-q", "-D", alerta.PLACA, str(wav))

    async def _entregar_en_orden(self):
        while True:
            m = await self.cola.get()
            while self.ocupado():      # espera que termine la charla, la emergencia o un recordatorio
                await asyncio.sleep(2)
            self.entregando = True
            pausada = self.radio.parar() if self.radio and self.radio.sonando() else None
            luz("mensaje")
            try:
                await self._entregar(m)
                await asyncio.to_thread(telegram_bot.mandar_texto, m["chat"],
                                        f"✓ Se lo dije a {_ella()} ({time.strftime('%H:%M')}).")
                await self._ofrecer_respuesta(m)
            except Exception as e:
                print(f"(no pude decir el mensaje de {m['de']}: {e})", flush=True)
                try:
                    await asyncio.to_thread(telegram_bot.mandar_texto, m["chat"],
                                            f"✗ No pude decírselo a {_ella()} ({e}). Probá de nuevo en un rato.")
                except RuntimeError:
                    pass
            finally:
                self.entregando = False
                if pausada:
                    self.radio.tocar(pausada)
                else:
                    luz("esperando")

    def atender_toque(self, toque):
        """charla.py lo llama con cada toque. True si el toque era para contestar."""
        if not self.esperando_toque:
            return False
        self._cancelado = toque == "larga"   # mantenerlo apretado es la emergencia
        self._toque.set()
        return not self._cancelado

    async def _ofrecer_respuesta(self, m):
        """'¿Querés contestarle?': si toca el botón, la graba hasta que se calla y
        se la manda como nota de voz. Todo con frases grabadas y en la Pi: sin tokens."""
        await alerta.decir("pregunta_responder")
        self._toque, self._cancelado = asyncio.Event(), False
        self.esperando_toque = True
        luz("mensaje")
        print("  (¿contesta? esperando un toque)", flush=True)
        try:
            await asyncio.wait_for(self._toque.wait(), timeout=ESPERA_RESPUESTA)
        except asyncio.TimeoutError:
            print("  (no quiso contestar)", flush=True)
            return
        finally:
            self.esperando_toque = False
        if self._cancelado:
            return
        luz("escuchando")
        print("  🎤 grabando la respuesta…", flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            wav, ogg = Path(tmp) / "respuesta.wav", Path(tmp) / "respuesta.ogg"
            if not await alerta.grabar_hasta_silencio(wav):
                print("  (no la escuché hablar)", flush=True)
                await alerta.decir("respuesta_sin_voz")
                return
            await asyncio.to_thread(alerta.normalizar, wav)
            await alerta._correr("opusenc", "--quiet", str(wav), str(ogg))
            luz("pensando")
            await asyncio.to_thread(telegram_bot.mandar_voz, m["chat"], ogg, f"🎤 Respuesta de {_ella()}")
        await alerta.decir("respuesta_mandada")
        print(f"🎤 {_ella()} le contestó a {m['de']}", flush=True)

    async def _entregar(self, m):
        if "texto" in m:
            # En dos partes: si va todo junto ("... Dice: Hola"), Gemini lee
            # solo el mensaje y se saltea quién lo manda.
            await self._tocar(await self._voz(f"Te llegó un mensaje de {m['de']}.", guardar=True))
            wav = await self._voz(m["texto"])
            try:
                await self._tocar(wav)
            finally:
                wav.unlink(missing_ok=True)  # el mensaje dicho no queda guardado
            _anotar(m["de"], m["texto"])
            return
        await self._tocar(await self._voz(f"Te llegó un audio de {m['de']}.", guardar=True))
        with tempfile.TemporaryDirectory() as tmp:
            ogg, wav = Path(tmp) / "audio.ogg", Path(tmp) / "audio.wav"
            await asyncio.to_thread(telegram_bot.descargar, m["audio"], ogg)
            await alerta._correr("opusdec", "--quiet", "--rate", "48000", str(ogg), str(wav))
            await self._tocar(wav)
        _anotar(m["de"], "(un audio)")
