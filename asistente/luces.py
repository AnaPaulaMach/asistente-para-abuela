"""Le avisa a leds.py en qué estado está el asistente.

Manda una palabra por UDP a 127.0.0.1:47474. UDP no espera respuesta: si
leds.py no está corriendo, el mensaje se pierde y la charla sigue igual.

A mano, para probar:  python3 ~/asistente/luces.py escuchando
"""
import socket
import sys

_salida = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Atado a 127.0.0.1: el puerto de salida solo existe dentro de la Pi, no en el WiFi.
_salida.bind(("127.0.0.1", 0))


def luz(estado, dato=None):
    mensaje = f"{estado} {dato}" if dato is not None else estado
    try:
        _salida.sendto(mensaje.encode(), ("127.0.0.1", 47474))
    except OSError:
        pass


if __name__ == "__main__":
    luz(*sys.argv[1:3])
