#!/usr/bin/env python3
"""Etapa a: prueba del botón de emergencia (GPIO17).

Avisa cuando se aprieta y se suelta, y distingue una pulsación corta de una
larga (2 s o más). La pulsación larga va a ser la alerta de emergencia (etapa e).
Se corta con Ctrl+C.
"""
from signal import pause
from time import monotonic

from gpiozero import Button

# pull_up=True: el pin queda en 1 por una resistencia interna y el botón lo
# lleva a 0 (tierra) al apretarlo; por eso es "activo en bajo".
# bounce_time: el contacto metálico "rebota" unos milisegundos al apretarlo;
# ignoramos cambios más rápidos que 50 ms para contar una sola pulsación.
# hold_time: cuánto hay que mantenerlo para que cuente como pulsación larga.
boton = Button(17, pull_up=True, bounce_time=0.05, hold_time=2)

inicio = 0.0


def apretado():
    global inicio
    inicio = monotonic()
    print("Apretaste el botón...", flush=True)


def mantenido():
    print("  ¡Pulsación LARGA! (acá va a ir la alerta de emergencia)", flush=True)


def soltado():
    duracion = monotonic() - inicio
    tipo = "larga" if duracion >= boton.hold_time else "corta"
    print(f"  Lo soltaste: {duracion:.2f} s, pulsación {tipo}", flush=True)


boton.when_pressed = apretado
boton.when_held = mantenido
boton.when_released = soltado

print("Probá el botón: toques cortos y uno largo (2 s). Ctrl+C para salir.", flush=True)
try:
    pause()
except KeyboardInterrupt:
    # Ctrl+C llega como una excepción; la atrapamos para salir sin el error largo.
    print("\nChau.")
