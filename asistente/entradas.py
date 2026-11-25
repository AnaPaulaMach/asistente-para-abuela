"""El botón y la ruedita, con libgpiod: el sistema avisa cuando un pin cambia.

Antes usábamos gpiozero, que con su librería lgpio tiene un hilo revisando los
pines todo el tiempo (4-5 % de un núcleo aunque nadie toque nada). Acá el
kernel despierta al programa solo cuando hay un cambio, a través del mismo
bucle de asyncio: en reposo, 0 %.

- Botón (GPIO17, a masa al apretar): toque corto o pulsación larga (2 s).
- Ruedita (GPIO13 y GPIO26): la misma tabla de estados que usa gpiozero, que
  ya andaba bien con este encoder (tolera rebotes y "medio pasos").
"""
from datetime import timedelta

import gpiod
from gpiod.line import Bias, Direction, Edge

CHIP = "/dev/gpiochip0"
BOTON, RUEDITA_A, RUEDITA_B = 17, 13, 26
LARGA = 2.0   # segundos apretado para que sea la emergencia

# Copiada de gpiozero (RotaryEncoder.TRANSITIONS). El índice es
# (A activo << 1) | (B activo); al completar una vuelta da '+1' o '-1'.
TRANSICIONES = {
    "idle": ["idle", "ccw1", "cw1", "idle"],
    "ccw1": ["idle", "ccw1", "ccw3", "ccw2"],
    "ccw2": ["idle", "ccw1", "ccw3", "ccw2"],
    "ccw3": ["-1", "idle", "ccw3", "ccw2"],
    "cw1": ["idle", "cw3", "cw1", "cw2"],
    "cw2": ["idle", "cw3", "cw1", "cw2"],
    "cw3": ["+1", "cw3", "idle", "cw2"],
}


class Entradas:
    def __init__(self, loop, al_tocar, al_girar):
        """al_tocar("corto"|"larga") y al_girar(+1|-1) se llaman en el bucle de asyncio."""
        self.loop, self.al_tocar, self.al_girar = loop, al_tocar, al_girar
        entrada = dict(direction=Direction.INPUT, edge_detection=Edge.BOTH, bias=Bias.PULL_UP)
        self.pedido = gpiod.request_lines(CHIP, consumer="asistente", config={
            # El kernel filtra los rebotes del botón (50 ms) antes de avisar.
            BOTON: gpiod.LineSettings(debounce_period=timedelta(milliseconds=50), **entrada),
            (RUEDITA_A, RUEDITA_B): gpiod.LineSettings(**entrada),
        })
        # Con pull-up, "activo" es cuando el pin está en 0 (conectado a masa).
        valores = self.pedido.get_values([RUEDITA_A, RUEDITA_B])
        self.activo = {RUEDITA_A: valores[0].value == 0, RUEDITA_B: valores[1].value == 0}
        self.estado = "idle"
        self.mantenido = None     # el temporizador de la pulsación larga
        self.fue_larga = False
        loop.add_reader(self.pedido.fd, self._leer)

    def _leer(self):
        for ev in self.pedido.read_edge_events():
            bajo = ev.event_type == ev.Type.FALLING_EDGE   # pasó a 0: activo
            if ev.line_offset == BOTON:
                self._boton(apretado=bajo)
            else:
                self.activo[ev.line_offset] = bajo
                self._ruedita()

    def _boton(self, apretado):
        if apretado:
            if self.mantenido is None:
                self.fue_larga = False
                self.mantenido = self.loop.call_later(LARGA, self._larga)
        elif self.mantenido is not None:
            self.mantenido.cancel()
            self.mantenido = None
            if not self.fue_larga:
                self.al_tocar("corto")

    def _larga(self):
        self.fue_larga = True       # al soltar ya no cuenta como toque corto
        self.al_tocar("larga")

    def _ruedita(self):
        indice = (self.activo[RUEDITA_A] << 1) | self.activo[RUEDITA_B]
        nuevo = TRANSICIONES[self.estado][indice]
        if nuevo in ("+1", "-1"):
            self.estado = "idle"
            self.al_girar(1 if nuevo == "+1" else -1)
        else:
            self.estado = nuevo

    def cerrar(self):
        self.loop.remove_reader(self.pedido.fd)
        self.pedido.release()
