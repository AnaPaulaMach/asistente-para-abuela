#!/usr/bin/env python3
"""Etapa c: charlar con Gemini Live usando el botón.

- Toque corto: el asistente escucha. Hablás, y cuando hacés silencio Gemini contesta
  por el parlante. Para seguir la charla, otro toque.
- Si tocás mientras Gemini habla, lo interrumpís y vuelve a escuchar.
- Pulsación larga (2 s): reservada para la emergencia (etapa e); por ahora solo
  la anuncia. Por eso se escucha al SOLTAR el toque y no al apretar.
- La conexión con Gemini queda abierta 2 minutos después del último toque, así
  recuerda de qué venían hablando; después se cierra y el próximo toque la abre.

Se corre con el venv: ~/asistente/venv/bin/python ~/asistente/charla.py   (Ctrl+C para salir)
"""
import array
import asyncio
import contextlib
import re
import signal
import time
from collections import Counter
from pathlib import Path

from google import genai
from google.genai import types
from gpiozero import Button, RotaryEncoder

import alerta
import tareas
import clima
import llamadas as llamar
import memoria
import mensajes as mensajeria  # "llamadas" ya es la lista de pedidos de Gemini
import noticias
import personas
import radio as radios
import telegram_bot
from frases import VOZ  # una sola voz para la charla y las frases grabadas
from luces import luz
from radio import Radio
import recordatorios as avisos
from recordatorios import Recordatorios
from dia import Dia
from vigilante import Vigilante
from volumen import Volumen

MODELO = "gemini-3.8-live"
VERSION_API = "v1beta"             # sin indicarla, la librería 3.6.1 da 404 en Live
# Precios por millón de tokens en USD (página de precios de AI Studio, 24/11/2026).
# "Pensamientos" se cobran como texto de salida.
PRECIOS = {"texto_in": 0.75, "audio_in": 3.00, "texto_out": 4.50, "audio_out": 12.00}
CONSUMO = Path.home() / "asistente" / "consumo.log"
PLACA = "plughw:seeed2micvoicec"   # micrófonos y parlante del ReSpeaker
TASA_MIC = 16000                   # Gemini Live espera PCM de 16 bits, mono, 16 kHz
BLOQUE = TASA_MIC * 2 // 10        # 100 ms de audio (2 bytes por muestra)
DESCARTE = TASA_MIC * 2 * 15 // 100  # los primeros 150 ms traen un salto del conversor
ESCUCHA_MAX = 90                   # tope por vez: habla mucho, y 90 s cuestan menos de 1 centavo
ESPERA_RESPUESTA = 10              # después de una pregunta, cuánto espera que empiece a hablar
GANANCIA_MIC = 3                   # los mics graban bajito: x3 (~+10 dB) antes de mandar
UMBRAL_VOZ = 350                   # RMS ya amplificado: silencio ~240, voz baja ~1000 o más
INACTIVIDAD = 120                  # segundos sin que nadie hable antes de cerrar la conexión
ESPERA_TOQUE = 15                  # después de un toque, cuánto espera que empiece a hablar
FIN_SILENCIO = 5                   # silencio (según la Pi) que da su turno por terminado
CONEXION_MAX = 10                  # segundos máximos para conectarse con Gemini

# Las instrucciones para Gemini están en archivos de texto, no en el código:
# - prompt/base.md: cómo habla el asistente y qué puede hacer (sin datos personales).
# - ~/.config/asistente/perfil.md: quién es ella y su familia. PRIVADO: queda solo
#   en la Pi (permisos 600) y nunca se sube al repositorio.
# Se leen en cada conexión: si los editás, la próxima charla ya los usa.
PROMPT_BASE = Path(__file__).parent / "prompt" / "base.md"
PERFIL = Path.home() / ".config" / "asistente" / "perfil.md"

# Funciones que Gemini puede pedir que ejecutemos ("function calling"): le
# describimos qué hacen y qué datos llevan, y él decide cuándo usarlas.
HERRAMIENTAS = [types.Tool(function_declarations=[types.FunctionDeclaration(
    name="cambiar_volumen",
    description="Cambia el volumen del parlante del asistente. Niveles del 1 (muy bajo) al 10 (muy fuerte).",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "accion": {"type": "string", "enum": ["subir", "bajar", "fijar"],
                       "description": "subir o bajar un poco, o fijar un nivel exacto"},
            "nivel": {"type": "integer", "minimum": 1, "maximum": 10,
                      "description": "solo para 'fijar'"},
            "pasos": {"type": "integer", "minimum": 1, "maximum": 5,
                      "description": "cuánto subir o bajar; 'mucho más fuerte' son 3"},
        },
        "required": ["accion"],
    },
), types.FunctionDeclaration(
    name="consultar_clima",
    description=("Devuelve el clima de ahora y el pronóstico de hoy y mañana donde vive ella. "
                 "Usala cuando pregunte por el clima, la temperatura o si va a llover."),
    parameters_json_schema={"type": "object", "properties": {}},
), types.FunctionDeclaration(
    name="noticias",
    description=("Trae los titulares del último día de los diarios de donde vive ella, ya sin "
                 "noticias policiales ni tragedias. Usala cuando pregunte qué pasó hoy, qué hay "
                 "de nuevo, o por un tema (fútbol, un festival, un barrio)."),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "tema": {"type": "string",
                     "description": "palabras para buscar, por ejemplo 'fútbol' o 'Añatuya'; vacío para lo general"},
            "incluir_delicadas": {"type": "boolean",
                                  "description": "true SOLO si ella pregunta directamente por un hecho policial o un accidente"},
        },
    },
), types.FunctionDeclaration(
    name="pedir_llamada",
    description=("Le avisa por Telegram a alguien de la familia que ella quiere que la llamen. "
                 "Vos no podés llamar: usala cuando pida hablar con alguien o que la llamen."),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "persona": {"type": "string",
                        "description": "a quién quiere hablarle, como ella lo dice; vacío si no dijo"},
            "motivo": {"type": "string",
                       "description": "lo que quiere decirle, solo si lo dijo, en sus palabras y corto"},
        },
    },
), types.FunctionDeclaration(
    name="recordar",
    description=("Guarda una nota corta de algo que ella te contó y conviene recordar en otra "
                 "charla: una visita, un plan, cómo se siente, algo que le gusta o le preocupa."),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "nota": {"type": "string",
                     "description": ("en tercera persona, corta y con fechas concretas, por ejemplo "
                                     "'el jueves 27 viene su nieta a visitarla' o 'le duele la rodilla'")},
        },
        "required": ["nota"],
    },
), types.FunctionDeclaration(
    name="olvidar",
    description="Borra las notas sobre un tema cuando ella pide que te olvides de algo.",
    parameters_json_schema={
        "type": "object",
        "properties": {"sobre": {"type": "string", "description": "palabras clave de lo que hay que olvidar"}},
        "required": ["sobre"],
    },
), types.FunctionDeclaration(
    name="agregar_recordatorio",
    description=("Agrega un recordatorio que ella pide ('recordame...'). Por defecto es de una sola "
                 "vez; todos_los_dias solo si lo dice ('todos los días', 'siempre')."),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "hora": {"type": "string", "description": "HH:MM en 24 horas, por ejemplo 17:00 (vacía si usás en_minutos)"},
            "en_minutos": {"type": "integer",
                           "description": "si dice 'en 10 minutos' o 'dentro de una hora': los minutos (10, 60); el programa calcula la hora"},
            "texto": {"type": "string",
                      "description": ("lo que vas a decir a esa hora, dirigido a ella, por ejemplo "
                                      "'Es hora de regar las plantas'")},
            "fecha": {"type": "string", "description": "DD/MM si dijo un día; vacío para hoy (o mañana si ya pasó)"},
            "todos_los_dias": {"type": "boolean"},
        },
        "required": ["texto"],
    },
), types.FunctionDeclaration(
    name="borrar_recordatorio",
    description="Borra los recordatorios sobre un tema cuando ella lo pide.",
    parameters_json_schema={
        "type": "object",
        "properties": {"sobre": {"type": "string", "description": "palabras clave, por ejemplo 'plantas'"}},
        "required": ["sobre"],
    },
), types.FunctionDeclaration(
    name="hora_actual",
    description=("Devuelve la fecha y la hora exactas de donde vive ella (Argentina). Usala SIEMPRE "
                 "que pregunte la hora, el día o la fecha: no la calcules ni la supongas."),
    parameters_json_schema={"type": "object", "properties": {}},
), types.FunctionDeclaration(
    name="mandar_mensaje",
    description=("Le manda por Telegram un mensaje de ella a alguien de la familia. Usala cuando "
                 "diga 'decile a ... que ...' o quiera contestar un mensaje que le llegó."),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "persona": {"type": "string", "description": "a quién, como ella lo dice"},
            "texto": {"type": "string",
                      "description": "lo que quiere decirle, en primera persona y con sus palabras"},
        },
        "required": ["persona", "texto"],
    },
), types.FunctionDeclaration(
    name="poner_radio",
    description=("Pone una radio por el parlante. Empieza cuando termines de hablar; ella la apaga "
                 "tocando el botón. Usala cuando pida la radio, música o una emisora."),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "emisora": {"type": "string",
                        "description": "nombre de la emisora de la lista; vacío para la de siempre"},
        },
    },
)]),
    # Búsqueda en Google (la hace Gemini, no la Pi): 5.000 búsquedas gratis por mes
    # y después USD 14 cada 1.000. Para preguntas puntuales; ver prompt/base.md.
    types.Tool(google_search=types.GoogleSearch())]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def instrucciones():
    """Arma el prompt: nombre + base + perfil y personas (privados) + fecha y hora.
    Gemini no sabe la fecha ni la hora: se las decimos al conectar."""
    partes = []
    nombre = telegram_bot.leer_env(telegram_bot.CONFIG / "ajustes.env").get("NOMBRE_ASISTENTE")
    if nombre:
        partes.append(f"Te llamás {nombre}. Si te preguntan tu nombre, decí que sos {nombre}.")
    partes.append(PROMPT_BASE.read_text().strip())
    gente = personas.para_el_prompt()
    if PERFIL.exists() or gente:
        sobre_ella = PERFIL.read_text().strip() if PERFIL.exists() else ""
        partes.append("Sobre ella y su gente:\n" + "\n".join(t for t in (gente, sobre_ella) if t))
    pendientes = avisos.todos()
    if pendientes:
        partes.append("Sus recordatorios (los sin fecha suenan todos los días):\n" + "\n".join(
            f"- {r['fecha'] + ' ' if r['fecha'] else ''}{r['hora']}: {r['texto']}" for r in pendientes))
    notas = memoria.para_el_prompt()
    if notas:
        partes.append(notas)
    llegados = mensajeria.recientes()
    if llegados:
        partes.append("Mensajes que le llegaron por Telegram en las últimas 24 horas (ya se los dijiste; "
                      "repetíselos si te pregunta):\n" + "\n".join(
                          f"- {m['hora']}, de {m['de']}: {m['texto']}" for m in llegados))
    lista = radios.emisoras()
    if lista:
        partes.append("Radios que podés poner con poner_radio:\n" + "\n".join(
            f"- {r['nombre']}: {r.get('descripcion', '')}" for r in lista))
    ahora = time.localtime()
    partes.append(f"Hoy es {DIAS[ahora.tm_wday]} {ahora.tm_mday} de {MESES[ahora.tm_mon - 1]} "
                  f"de {ahora.tm_year} y son las {ahora.tm_hour}:{ahora.tm_min:02d}.")
    return "\n\n".join(partes)


def configuracion():
    """La configuración de cada conexión, con el prompt recién leído."""
    return CONFIG.model_copy(update={"system_instruction": instrucciones()})


CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    tools=HERRAMIENTAS,
    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOZ))),
    # Transcripciones: lo que Gemini entendió y lo que dijo, para verlo en pantalla.
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
    # Detección de voz en el servidor. Sensible al empezar (habla bajito) y
    # poco apurada al terminar: con 4 s de silencio recién contesta, porque
    # hace pausas en medio de las frases y no hay que cortarla.
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
            end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
            silence_duration_ms=4000,
        ),
    ),
)


def clave_gemini():
    for linea in (Path.home() / ".config/asistente/secretos.env").read_text().splitlines():
        if linea.startswith("GEMINI_API_KEY="):
            return linea.split("=", 1)[1].strip()
    raise SystemExit("Falta GEMINI_API_KEY en ~/.config/asistente/secretos.env")


def volumen_rms(datos):
    """Volumen promedio de un bloque (raíz del promedio de los cuadrados)."""
    muestras = array.array("h", datos)
    return (sum(x * x for x in muestras) / len(muestras)) ** 0.5 if muestras else 0


def agregar_recordatorio(args):
    """Lo que pidió Gemini, con la fecha resuelta: sin fecha y sin "todos los días"
    es hoy, o mañana si esa hora ya pasó."""
    texto = (args.get("texto") or "").strip()
    if args.get("en_minutos"):
        # "En 10 minutos": la cuenta la hace la Pi con su reloj, no Gemini.
        # Redondeado al minuto más cercano (+30 s); como mínimo, el minuto que viene.
        cuando = time.localtime(time.time() + max(1, int(args["en_minutos"])) * 60 + 30)
        return {"ok": True, "anotado": avisos.agregar(time.strftime("%H:%M", cuando), texto,
                                                      time.strftime("%d/%m", cuando)), "repite": "una sola vez"}
    hora = (args.get("hora") or "").strip()
    try:
        t = time.strptime(hora, "%H:%M")
    except ValueError:
        raise ValueError("la hora tiene que ser HH:MM, de 00:00 a 23:59") from None
    if args.get("todos_los_dias"):
        return {"ok": True, "anotado": avisos.agregar(hora, texto), "repite": "todos los días"}
    fecha = (args.get("fecha") or "").strip()
    if not fecha:
        ahora = time.localtime()
        pedido = t.tm_hour * 60 + t.tm_min
        actual = ahora.tm_hour * 60 + ahora.tm_min
        if pedido > actual:
            cuando = time.time()                        # hoy
        elif actual - pedido <= 2:
            # Es "ya" (la hora de este minuto o de recién): que suene en el próximo minuto.
            proximo = time.localtime(time.time() + 60)
            hora, cuando = time.strftime("%H:%M", proximo), time.time() + 60
        else:
            cuando = time.time() + 86400                # esa hora ya pasó: mañana
        fecha = time.strftime("%d/%m", time.localtime(cuando))
    return {"ok": True, "anotado": avisos.agregar(hora, texto, fecha), "repite": "una sola vez"}


class PasaAltos:
    """Filtro de un polo que saca la "continua" (el corrimiento de la media)
    sin tocar la voz: y[n] = x[n] - x[n-1] + 0,995 * y[n-1]."""

    def __init__(self):
        self.x_ant = None
        self.y_ant = 0.0

    def __call__(self, datos):
        muestras = array.array("h", datos)
        if self.x_ant is None and muestras:
            self.x_ant = muestras[0]  # arranca desde el primer valor: sin salto inicial
        for i, x in enumerate(muestras):
            y = x - self.x_ant + 0.995 * self.y_ant
            self.x_ant, self.y_ant = x, y
            # Además de filtrar, amplificamos: así Gemini oye también la voz baja.
            muestras[i] = max(-32768, min(32767, int(y * GANANCIA_MIC)))
        return muestras.tobytes()


class Charla:
    def __init__(self, sesion, volumen):
        self.sesion = sesion
        self.volumen = volumen
        self.mic = None          # proceso arecord mientras escucha
        self.envio = None        # tarea que manda el micrófono a Gemini
        self.parlante = None     # proceso aplay mientras Gemini habla
        self.ignorar = False     # descartar el resto de una respuesta interrumpida
        self.respuesta = ""      # lo que va diciendo Gemini en esta respuesta
        self.automatico = False  # escuchando solo, esperando que conteste
        self.oyo_algo = False    # Gemini transcribió algo de lo que dijo ella
        self.ultima_actividad = time.monotonic()  # cuándo habló alguien por última vez
        self._candado = asyncio.Lock()            # abrir el micrófono, de a uno
        self.radio = None         # la Radio de main()
        self.radio_pendiente = None  # emisora a poner cuando termine de hablar
        self.tokens = Counter()  # consumo de esta conexión, por tipo
        self.inicio = time.monotonic()

    async def escuchar(self):
        """Arranca el micrófono. Se llama ANTES de conectar en el primer toque:
        lo que digas mientras conecta queda guardado en la tubería (pipe)."""
        await self.callar()
        await asyncio.to_thread(self.volumen.esperar_pitido)
        # start_new_session: el Ctrl+C le llega solo a Python, que cierra todo en orden.
        self.mic = await asyncio.create_subprocess_exec(
            "arecord", "-q", "-D", PLACA, "-t", "raw", "-f", "S16_LE",
            "-r", str(TASA_MIC), "-c", "1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True)
        luz("escuchando")
        print("🎤 Escuchando...", flush=True)

    def escuchando(self):
        return self.mic is not None and self.mic.returncode is None

    def empezar_envio(self, espera=None):
        self.automatico = espera is not None
        self.oyo_algo = False
        self.envio = tareas.lanzar(self._mandar_mic(espera), "micrófono")

    async def _mandar_mic(self, espera):
        """Manda el micrófono a Gemini, con dos controles propios además de
        la detección de voz de Gemini (que con ruido de fondo puede no darse
        cuenta de que terminó):
        - si no empieza a hablar en `espera` segundos (10 después de una
          pregunta, 15 después de un toque), corta;
        - si empezó y después hay FIN_SILENCIO segundos de silencio, da su
          turno por terminado para que Gemini conteste."""
        filtro = PasaAltos()
        mic = self.mic
        espera = ESPERA_TOQUE if espera is None else espera
        hablo = False
        ultimos = []   # ¿los últimos 5 bloques pasaron el umbral?
        callado = 0    # bloques seguidos en silencio desde que habló
        try:
            await mic.stdout.readexactly(DESCARTE)
            for bloque in range(ESCUCHA_MAX * 10):
                datos = filtro(await mic.stdout.readexactly(BLOQUE))
                await self.sesion.send_realtime_input(
                    audio=types.Blob(data=datos, mime_type=f"audio/pcm;rate={TASA_MIC}"))
                fuerte = volumen_rms(datos) > UMBRAL_VOZ
                if hablo:
                    callado = 0 if fuerte else callado + 1
                    if fuerte:
                        self.ultima_actividad = time.monotonic()
                    if callado >= FIN_SILENCIO * 10:
                        await self.sesion.send_realtime_input(audio_stream_end=True)
                        luz("pensando")
                        print("  (terminó de hablar)", flush=True)
                        return
                    continue
                # ¿Empezó a hablar? 3 de los últimos 5 bloques (medio segundo)
                # por encima del umbral, aunque no sean seguidos (la voz baja
                # sube y baja), o que Gemini ya haya transcripto algo.
                ultimos = (ultimos + [fuerte])[-5:]
                if sum(ultimos) >= 3 or self.oyo_algo:
                    hablo = True
                    self.automatico = False  # desde acá es una escucha normal
                    self.ultima_actividad = time.monotonic()
                    print("  (te escucho)", flush=True)
                elif (bloque + 1) / 10 >= espera:
                    await self.sesion.send_realtime_input(audio_stream_end=True)
                    luz("esperando")
                    print("(no contestó; tocá el botón para seguir)", flush=True)
                    return
            # Pasó el tiempo máximo sin respuesta: avisamos que se cortó el audio.
            await self.sesion.send_realtime_input(audio_stream_end=True)
            luz("esperando")
            print("(se terminó el tiempo de escucha)", flush=True)
        except asyncio.IncompleteReadError:
            pass  # arecord se cerró: lo paramos nosotros
        finally:
            if mic.returncode is None:
                mic.kill()
            await mic.wait()

    async def dejar_de_escuchar(self):
        # El códec de la placa usa un solo reloj: no puede grabar a 16 kHz y
        # reproducir a 24 kHz a la vez. Por eso siempre se apaga uno antes del otro.
        if self.mic and self.mic.returncode is None:
            self.mic.kill()
        if self.envio:
            await asyncio.gather(self.envio, return_exceptions=True)
            self.envio = None

    async def callar(self):
        await self.dejar_de_escuchar()
        await self.callar_parlante()

    async def callar_parlante(self):
        if self.parlante and self.parlante.returncode is None:
            self.parlante.kill()
            await self.parlante.wait()
        self.parlante = None

    async def abrir_microfono(self, espera=None):
        """Escuchar y mandar a Gemini, como una sola operación con candado: un toque
        y la escucha automática pueden llegar a la vez, y la placa es una sola."""
        async with self._candado:
            await self.escuchar()
            self.empezar_envio(espera)

    async def hablar(self, datos, formato):
        self.ultima_actividad = time.monotonic()
        if not self.parlante:
            await self.dejar_de_escuchar()
            tasa = re.search(r"rate=(\d+)", formato or "")
            self.parlante = await asyncio.create_subprocess_exec(
                "aplay", "-q", "-D", PLACA, "-t", "raw", "-f", "S16_LE",
                "-r", tasa.group(1) if tasa else "24000", "-c", "1",
                # stderr a DEVNULL: aplay avisa "underrun" cuando se queda sin datos
                # esperando el fin de la respuesta; es esperable y no es una falla.
                stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True)
            luz("hablando")
        try:
            self.parlante.stdin.write(datos)
            await self.parlante.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass

    async def fin_de_respuesta(self):
        if self.parlante:
            self.parlante.stdin.close()  # que termine de sonar lo que tiene
            await self.parlante.wait()
            self.parlante = None
        luz("esperando")

    def contar(self, uso):
        """Suma los tokens que Gemini informa en cada respuesta. Cada respuesta
        vuelve a contar como entrada todo lo anterior de la charla (el contexto):
        por eso conviene cerrar la conexión cuando nadie habla."""
        for detalle in uso.prompt_tokens_details or []:
            tipo = "audio_in" if detalle.modality.name == "AUDIO" else "texto_in"
            self.tokens[tipo] += detalle.token_count or 0
        for detalle in uso.response_tokens_details or []:
            tipo = "audio_out" if detalle.modality.name == "AUDIO" else "texto_out"
            self.tokens[tipo] += detalle.token_count or 0
        self.tokens["texto_out"] += uso.thoughts_token_count or 0

    def anotar_consumo(self):
        if not self.tokens:
            return
        usd = sum(self.tokens[t] * PRECIOS[t] / 1e6 for t in PRECIOS)
        minutos = (time.monotonic() - self.inicio) / 60
        linea = (f"{time.strftime('%Y-%m-%d %H:%M')}  {minutos:4.1f} min  "
                 + "  ".join(f"{t}={self.tokens[t]}" for t in PRECIOS) + f"  USD {usd:.4f}")
        with CONSUMO.open("a") as f:
            f.write(linea + "\n")
        print(f"💲 Esta charla: USD {usd:.4f} (anotado en {CONSUMO})", flush=True)

    async def usar_herramientas(self, llamadas):
        """Gemini pide ejecutar una función: la corremos y le devolvemos el resultado."""
        luz("pensando")
        respuestas = []
        for llamada in llamadas:
            args = llamada.args or {}
            if llamada.name == "cambiar_volumen":
                accion = args.get("accion")
                pasos = int(args.get("pasos") or 1)
                if accion == "subir":
                    nivel = self.volumen.subir(pasos)
                elif accion == "bajar":
                    nivel = self.volumen.bajar(pasos)
                else:
                    nivel = self.volumen.fijar(args.get("nivel") or self.volumen.nivel)
                resultado = {"nivel": nivel, "minimo": 1, "maximo": 10}
            elif llamada.name == "consultar_clima":
                try:
                    resultado = await asyncio.to_thread(clima.consultar)
                except Exception as e:  # sin internet, etc.: que lo diga, no que invente
                    resultado = {"error": f"no pude consultar el clima ({e})"}
            elif llamada.name == "pedir_llamada":
                try:
                    resultado = await asyncio.to_thread(
                        llamar.pedir, args.get("persona") or "", args.get("motivo") or "")
                except Exception as e:  # sin internet: que no prometa que avisó
                    resultado = {"error": f"no pude avisar ({e})"}
            elif llamada.name == "recordar":
                resultado = memoria.recordar(args.get("nota") or "")
            elif llamada.name == "olvidar":
                resultado = memoria.olvidar(args.get("sobre") or "")
            elif llamada.name == "agregar_recordatorio":
                try:
                    resultado = agregar_recordatorio(args)
                except ValueError as e:
                    resultado = {"error": str(e)}
            elif llamada.name == "borrar_recordatorio":
                borrados = avisos.borrar(sobre=args.get("sobre") or "")
                resultado = {"ok": True, "borrados": borrados} if borrados else {"error": "no encontré ese recordatorio"}
            elif llamada.name == "hora_actual":
                ahora = time.localtime()  # el reloj de la Pi: hora de Argentina, sincronizada
                resultado = {"hora": f"{ahora.tm_hour}:{ahora.tm_min:02d}",
                             "dia": DIAS[ahora.tm_wday],
                             "fecha": f"{ahora.tm_mday} de {MESES[ahora.tm_mon - 1]} de {ahora.tm_year}"}
            elif llamada.name == "mandar_mensaje":
                try:
                    resultado = await asyncio.to_thread(
                        mensajeria.mandar, args.get("persona") or "", args.get("texto") or "")
                except Exception as e:
                    resultado = {"error": f"no pude mandarlo ({e})"}
            elif llamada.name == "poner_radio":
                elegida = radios.buscar(args.get("emisora") or "")
                if elegida:
                    # No suena todavía: Gemini está por hablar y la placa reproduce
                    # una sola cosa por vez. Arranca al terminar la respuesta.
                    self.radio_pendiente = elegida["nombre"]
                    resultado = {"ok": True, "emisora": elegida["nombre"],
                                 "nota": "empieza apenas termines de hablar; decile que la apaga tocando el botón"}
                else:
                    resultado = {"error": "no tengo esa emisora",
                                 "disponibles": [r["nombre"] for r in radios.emisoras()]}
            elif llamada.name == "noticias":
                try:
                    resultado = await asyncio.to_thread(
                        noticias.buscar, args.get("tema") or "", bool(args.get("incluir_delicadas")))
                except Exception as e:
                    resultado = {"error": f"no pude traer las noticias ({e})"}
            else:
                resultado = {"error": f"no conozco la función {llamada.name}"}
            respuestas.append(types.FunctionResponse(id=llamada.id, name=llamada.name,
                                                     response=resultado))
        await self.sesion.send_tool_response(function_responses=respuestas)

    async def recibir(self):
        """Lee todo lo que manda Gemini mientras la conexión esté abierta."""
        while True:
            # receive() termina al final de cada respuesta: lo volvemos a llamar.
            async for msg in self.sesion.receive():
                if msg.usage_metadata:
                    self.contar(msg.usage_metadata)
                if msg.tool_call:
                    await self.usar_herramientas(msg.tool_call.function_calls)
                if msg.go_away:
                    print("(Gemini va a cerrar la conexión pronto)", flush=True)
                sc = msg.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    self.oyo_algo = True
                    self.ultima_actividad = time.monotonic()
                    print(f"  👵 {sc.input_transcription.text}", flush=True)
                if sc.interrupted:
                    # Ella empezó a hablar encima: se calla el parlante, pero el
                    # micrófono sigue abierto (es justo lo que hay que escuchar).
                    self.ignorar = False
                    await self.callar_parlante()
                for parte in (sc.model_turn.parts if sc.model_turn else []):
                    if parte.inline_data and not self.ignorar:
                        await self.hablar(parte.inline_data.data, parte.inline_data.mime_type)
                if sc.output_transcription and sc.output_transcription.text:
                    self.respuesta += sc.output_transcription.text
                    print(f"  🤖 {sc.output_transcription.text}", flush=True)
                if sc.turn_complete:
                    descartada = self.ignorar
                    self.ignorar = False
                    # ¿Le preguntó algo? Buscamos un "?" en todo lo que dijo.
                    pregunto = "?" in self.respuesta and not descartada
                    self.respuesta = ""
                    await self.fin_de_respuesta()  # espera a que termine de sonar
                    if self.radio_pendiente and self.radio:
                        self.radio.tocar(self.radio_pendiente)
                        self.radio_pendiente = None
                        print("(sonando la radio; un toque la apaga)", flush=True)
                    elif pregunto:
                        # Le preguntó algo: escuchamos solos, sin que toque el botón.
                        await self.abrir_microfono(espera=ESPERA_RESPUESTA)
                        print(f"(esperando su respuesta {ESPERA_RESPUESTA} s)", flush=True)
                    else:
                        print("(listo; tocá el botón para seguir)", flush=True)


async def main():
    cliente = genai.Client(api_key=clave_gemini(),
                           http_options=types.HttpOptions(api_version=VERSION_API))
    loop = asyncio.get_running_loop()
    toques = asyncio.Queue()
    # systemd apaga los servicios con la señal SIGTERM: la convertimos en una
    # cancelación, así se ejecutan los "finally" (cerrar audio, apagar luces).
    loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)

    # gpiozero llama a estas funciones desde otro hilo; call_soon_threadsafe
    # pasa el aviso al hilo de asyncio de forma segura.
    boton = Button(17, pull_up=True, bounce_time=0.05, hold_time=2)
    larga = False

    def mantenido():
        nonlocal larga
        larga = True
        loop.call_soon_threadsafe(toques.put_nowait, "larga")

    def soltado():
        nonlocal larga
        if not larga:
            loop.call_soon_threadsafe(toques.put_nowait, "corto")
        larga = False

    boton.when_held = mantenido
    boton.when_released = soltado

    # La ruedita: gpiozero mira el orden en que cambian los dos cables (A y B)
    # y nos dice para qué lado giró. Cada "clic" es un paso. El volumen se
    # cambia directo desde el hilo de gpiozero; Volumen tiene su propio candado.
    volumen = Volumen()
    volumen.al_cambiar = lambda nivel: luz("volumen", nivel)
    ruedita = RotaryEncoder(13, 26, max_steps=0)
    # Girar la ruedita también es "señal de que está bien" (dia se crea más abajo).
    ruedita.when_rotated_clockwise = lambda: (volumen.subir(), dia and dia.senal())
    ruedita.when_rotated_counter_clockwise = lambda: (volumen.bajar(), dia and dia.senal())

    atender.charla = None  # la charla en curso (la actualiza atender())
    radio = Radio()

    mensajes = recordatorios = dia = None   # se crean más abajo

    def placa_ocupada():
        """La placa de audio es una sola: ¿hay algo usándola? Todos esperan a que
        se libere (los recordatorios, los mensajes, el buen día) con la misma regla."""
        return (atender.charla is not None or alerta.activa
                or (mensajes is not None and mensajes.entregando)
                or (recordatorios is not None and recordatorios.confirmacion is not None)
                or (dia is not None and dia.saludando))

    # Mientras suena algo no pita: lo apagaría (un solo reloj).
    volumen.ocupado = lambda: radio.sonando() or placa_ocupada()

    print(f"Listo ({MODELO}, voz {VOZ}, volumen {volumen.nivel}/10). "
          "Tocá el botón y hablá; la ruedita cambia el volumen. Ctrl+C para salir.", flush=True)
    luz("esperando")

    # Órdenes del panel de control (panel.py), por UDP y solo dentro de la Pi.
    # Por ahora una: "volumen N". El volumen vive acá, así no se pisan.
    class Control(asyncio.DatagramProtocol):
        def datagram_received(self, datos, _origen):
            palabras = datos.decode(errors="ignore").split()
            if len(palabras) == 2 and palabras[0] == "volumen" and palabras[1].isdigit():
                volumen.fijar(int(palabras[1]))
            elif palabras == ["radio", "apagar"]:
                radio.parar()
                luz("esperando")

    await loop.create_datagram_endpoint(Control, local_addr=("127.0.0.1", 47475))

    # Los recordatorios corren en paralelo ("tarea" de asyncio) y esperan
    # cuando hay una charla o una emergencia en curso.
    # Los mensajes de la familia esperan si hay una charla, una emergencia o un
    # recordatorio; los recordatorios esperan si se está diciendo un mensaje.
    recordatorios = Recordatorios(cliente, ocupado=placa_ocupada)
    recordatorios.radio = radio  # un recordatorio pausa la radio y la vuelve a poner
    tareas.lanzar(recordatorios.bucle(), "recordatorios")
    vigilante = Vigilante(telegram_bot.leer_env(telegram_bot.CONFIG / "ajustes.env").get("NOMBRE_ASISTENTE", "El asistente"))
    tareas.lanzar(vigilante.vigilar(), "vigilante")
    mensajes = mensajeria.Mensajes(cliente, radio=radio, vigilante=vigilante, ocupado=placa_ocupada)
    tareas.lanzar(mensajes.escuchar(), "mensajes")
    dia = Dia(cliente, radio=radio, ocupado=placa_ocupada)   # buen día y chequeo de la mañana
    atender.dia = dia
    tareas.lanzar(dia.bucle(), "día")
    tareas.lanzar(vigilar_radio(radio), "radio")

    try:
        await atender(cliente, toques, volumen, radio, recordatorios, mensajes)
    finally:
        radio.parar()  # mpv corre aparte: si la charla se cierra, que no quede sonando


async def vigilar_radio(radio):
    """Si la radio se cortó sola (se cayó la transmisión o pasaron las 3 horas),
    que no queden la luz de radio ni el panel diciendo que suena."""
    while True:
        await asyncio.sleep(30)
        if radio.nombre and not radio.sonando():
            radio.parar()
            luz("esperando")


async def atender(cliente, toques, volumen, radio, recordatorios, mensajes):
    """El ciclo de toques: charla, emergencia y confirmación de recordatorios."""
    while True:
        toque = await toques.get()
        atender.dia.senal()  # tocó el botón: está bien
        if mensajes.atender_toque(toque):
            continue  # el toque era para contestar el mensaje que le llegó
        if toque == "larga":
            atender.dia.cancelar()     # la emergencia corta el saludo (y atender_toque, el mensaje)
        while mensajes.entregando or atender.dia.saludando:  # que termine (son segundos)
            await asyncio.sleep(0.2)
        if radio.sonando():
            radio.parar()  # cualquier toque apaga la radio (y sigue: hablar o emergencia)
        if toque == "larga":
            await alerta.emergencia(toques)
            continue
        if recordatorios.confirmar():
            continue  # el toque era para decir "listo" a un recordatorio
        charla = Charla(None, volumen)
        charla.radio = radio
        atender.charla = charla  # para volumen.ocupado y los recordatorios
        receptor = None
        emergencia = False
        await charla.escuchar()  # el micrófono arranca ya, antes de conectar
        try:
            # AsyncExitStack: como un "async with", pero nos deja ponerle un
            # límite de tiempo a la conexión (si no, podría quedar colgada).
            async with contextlib.AsyncExitStack() as pila:
                sesion = await asyncio.wait_for(
                    pila.enter_async_context(
                        cliente.aio.live.connect(model=MODELO, config=configuracion())),
                    timeout=CONEXION_MAX)
                charla.sesion = sesion
                charla.empezar_envio()
                receptor = tareas.lanzar(charla.recibir(), "receptor")
                while not receptor.done():
                    espera = asyncio.ensure_future(toques.get())
                    hecho, _ = await asyncio.wait({espera, receptor}, timeout=10,
                                                  return_when=asyncio.FIRST_COMPLETED)
                    if espera not in hecho:
                        espera.cancel()
                        if receptor.done():
                            break  # se cortó la conexión
                        # Sin toques no alcanza para cerrar: la charla sigue sola
                        # con la escucha automática. Se cierra cuando nadie habló
                        # en INACTIVIDAD segundos y no está escuchando ni hablando.
                        quieto = time.monotonic() - charla.ultima_actividad
                        if charla.escuchando() or charla.parlante or radio.sonando():
                            continue
                        if quieto > 20:
                            luz("esperando")  # por si quedó "pensando" y Gemini no contestó
                        if quieto < INACTIVIDAD:
                            continue
                        break
                    if radio.sonando():
                        radio.parar()
                    if espera.result() == "larga":
                        # Cerramos la charla primero: Gemini no tiene que hablar encima.
                        emergencia = True
                        break
                    if charla.escuchando() and not charla.automatico:
                        # Tocó de nuevo y todavía no hubo respuesta: corta.
                        # (Si estaba esperando solo su respuesta, el toque es
                        # "quiero hablar": sigue abajo y escucha normal.)
                        # Lo que llegue de esa pregunta se descarta.
                        await charla.dejar_de_escuchar()
                        charla.ignorar = True
                        luz("esperando")
                        print("(cortado; tocá de nuevo para empezar)", flush=True)
                        continue
                    # Toque mientras habla (o ya terminó): interrumpe y vuelve a escuchar.
                    charla.ignorar = charla.parlante is not None
                    await charla.abrir_microfono()
                if receptor.done() and not receptor.cancelled() and receptor.exception():
                    print(f"(se cortó la conexión: {receptor.exception()})", flush=True)
            luz("radio" if radio.sonando() else "esperando")
        except Exception as e:
            # Sin internet, sin saldo, o tardó demasiado: naranja y que lo diga.
            luz("error")
            motivo = "tardó más de {} s en conectar".format(CONEXION_MAX) \
                if isinstance(e, asyncio.TimeoutError) else e
            print(f"⚠️  Error con Gemini: {motivo}", flush=True)
            await charla.callar()
            await alerta.decir("no_conecta")
        finally:
            # Se ejecuta siempre, también con Ctrl+C: cerramos el receptor y
            # esperamos que termine, así no queda una tarea "huérfana" con error.
            if receptor:
                receptor.cancel()
                await asyncio.gather(receptor, return_exceptions=True)
            await charla.callar()
            charla.anotar_consumo()
            charla = atender.charla = None
        print("(conexión cerrada; el próximo toque la vuelve a abrir)", flush=True)
        if emergencia:
            await alerta.emergencia(toques)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nChau.")
    finally:
        luz("apagado")  # si la charla no corre, que no parezca lista
