#!/usr/bin/env python3
"""Etapa d: las luces del asistente (16 LEDs WS2812 en GPIO12).

Corre aparte, con sudo, porque la librería rpi_ws281x escribe directo en el
hardware de la Pi. Escucha mensajes de una palabra por UDP en 127.0.0.1:47474
(los manda charla.py, o a mano: python3 ~/asistente/luces.py escuchando) y dibuja
el estado 30 veces por segundo.

    sudo ~/leds-venv/bin/python ~/asistente/leds.py

Estados: esperando, escuchando, pensando, hablando, volumen N, error,
emergencia, cuenta N, recordatorio, radio, mensaje, apagado.
"""
import math
import signal
import socket
import time

from rpi_ws281x import Color, PixelStrip

CANTIDAD = 16
QUIETOS = {"escuchando", "volumen", "apagado"}   # estados sin animación
PUERTO = 47474
# Brillo global (0-255), en ajustes.env (LUCES_BRILLO). Bien bajo: que se vea
# sin encandilar. Con menos de 8 los colores mezclados (rosa, lila) se pierden,
# porque a cada canal le quedan muy pocos escalones.
BRILLO = 8

ROSA = (255, 40, 120)
AZUL = (0, 60, 255)
VERDE = (0, 255, 60)
NARANJA = (255, 90, 0)
ROJO = (255, 0, 0)
BLANCO = (255, 255, 255)
LILA = (150, 60, 255)
CELESTE = (0, 170, 255)
BLANCO_CALIDO = (255, 170, 90)

def _ajuste(nombre):
    """Un valor de ajustes.env, o None."""
    try:
        for linea in open("/home/" + _usuario() + "/.config/asistente/ajustes.env"):
            if linea.startswith(nombre + "="):
                return linea.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


# De noche, "esperando" es una luz blanca cálida, tenue y fija: compañía para no
# estar a oscuras (y para ver por dónde camina). Horas en ajustes.env (NOCHE=21-7).
def _horas_de_noche():
    try:
        desde, hasta = _ajuste("NOCHE").split("-")
        return int(desde), int(hasta)
    except (AttributeError, ValueError):
        return 21, 7


def _usuario():
    # leds.py corre como root: el usuario dueño de la carpeta del programa.
    import os
    import pwd
    return pwd.getpwuid(os.stat(__file__).st_uid).pw_name


_noche = (None, False)  # (minuto, resultado): se revisa una vez por minuto, no en cada cuadro


def es_de_noche():
    global _noche
    minuto = int(time.time() // 60)
    if _noche[0] != minuto:
        desde, hasta = _horas_de_noche()
        hora = time.localtime().tm_hour
        _noche = (minuto, hora >= desde or hora < hasta)
    return _noche[1]


def escalar(color, factor):
    return tuple(int(c * max(0.0, min(1.0, factor))) for c in color)


def ola(t, periodo):
    """Sube y baja suave entre 0 y 1 (un coseno), como una respiración."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * t / periodo)


def dibujar(estado, extra, t):
    """Devuelve la lista de 16 colores para este instante."""
    if estado == "esperando":
        if es_de_noche():
            return [escalar(BLANCO_CALIDO, 0.35)] * CANTIDAD
        return [escalar(ROSA, 0.15 + 0.45 * ola(t, 4))] * CANTIDAD
    if estado == "escuchando":
        return [AZUL] * CANTIDAD
    if estado == "pensando":
        # Una "cabeza" que gira con una cola que se va apagando.
        cabeza = (t * 16) % CANTIDAD
        return [escalar(AZUL, 1 - ((cabeza - i) % CANTIDAD) / 6) for i in range(CANTIDAD)]
    if estado == "hablando":
        return [escalar(VERDE, 0.45 + 0.55 * ola(t, 1.2))] * CANTIDAD
    if estado == "volumen":
        prendidos = round(int(extra or 0) * CANTIDAD / 10)
        return [BLANCO if i < prendidos else (0, 0, 0) for i in range(CANTIDAD)]
    if estado == "radio":
        # Un punto rosa que da la vuelta despacio sobre un rosa tenue: "está sonando".
        punto = (t / 4 * CANTIDAD) % CANTIDAD
        return [escalar(ROSA, max(0.12, 1 - min(abs(i - punto), CANTIDAD - abs(i - punto)) / 3))
                for i in range(CANTIDAD)]
    if estado == "mensaje":
        return [escalar(CELESTE, 0.3 + 0.7 * ola(t, 1.2))] * CANTIDAD
    if estado == "recordatorio":
        return [escalar(LILA, 0.3 + 0.7 * ola(t, 1.5))] * CANTIDAD
    if estado == "error":
        return [escalar(NARANJA, ola(t, 2))] * CANTIDAD
    if estado == "emergencia":
        return [ROJO if (t * 2) % 1 < 0.5 else (0, 0, 0)] * CANTIDAD
    if estado == "cuenta":
        # Cuenta regresiva para cancelar: el anillo rojo se achica de a un segundo.
        prendidos = round(int(extra or 0) * CANTIDAD / 10)
        brillo = 0.5 + 0.5 * ola(t, 1)
        return [escalar(ROJO, brillo) if i < prendidos else (0, 0, 0) for i in range(CANTIDAD)]
    return [(0, 0, 0)] * CANTIDAD  # apagado o desconocido


def main():
    try:
        brillo = max(1, min(255, int(_ajuste("LUCES_BRILLO") or BRILLO)))
    except ValueError:
        brillo = BRILLO
    tira = PixelStrip(CANTIDAD, 12, 800000, 10, False, brillo, 0)
    tira.begin()

    entrada = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    entrada.bind(("127.0.0.1", PUERTO))  # solo acepta mensajes de la misma Pi
    entrada.settimeout(1 / 30)

    # systemd (etapa f) para los programas con SIGTERM: lo convertimos en
    # KeyboardInterrupt para apagar las luces al salir, igual que con Ctrl+C.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))

    estado, extra = "esperando", None
    temporal = None  # (estado, extra, hasta): volumen y emergencia duran un rato
    anterior = None  # el último cuadro mandado: si no cambió, no se manda de nuevo
    print("Luces listas. Ctrl+C para salir.", flush=True)
    try:
        while True:
            try:
                palabras = entrada.recv(64).decode().split()
                if palabras:
                    nuevo, dato = palabras[0], (palabras[1] if len(palabras) > 1 else None)
                    if nuevo == "volumen":  # dura 2 s y vuelve a lo que estaba
                        temporal = (nuevo, dato, time.monotonic() + 2)
                    else:
                        estado, extra = nuevo, dato
                    print(f"→ {nuevo} {dato or ''}", flush=True)
            except socket.timeout:
                pass
            ahora = time.monotonic()
            if temporal and ahora > temporal[2]:
                temporal = None
            actual, dato = (temporal[0], temporal[1]) if temporal else (estado, extra)
            cuadro = dibujar(actual, dato, ahora)
            if cuadro != anterior:   # en los estados quietos no hay nada que mandar
                for i, (r, g, b) in enumerate(cuadro):
                    tira.setPixelColor(i, Color(r, g, b))
                tira.show()
                anterior = cuadro
            # Estados quietos: se revisa 4 veces por segundo en vez de 30 (un
            # mensaje nuevo igual se atiende enseguida: recv lo despierta).
            quieto = actual in QUIETOS or (actual == "esperando" and es_de_noche())
            entrada.settimeout(0.25 if quieto else 1 / 30)
    except KeyboardInterrupt:
        pass
    finally:
        for i in range(CANTIDAD):
            tira.setPixelColor(i, Color(0, 0, 0))
        tira.show()
        print("Luces apagadas.")


if __name__ == "__main__":
    main()
