#!/usr/bin/env -S sh -c 'exec "$HOME/asistente/venv/bin/python" "$0" "$@"'
"""Lo que el panel de control de la compu le pide a la Pi, por ssh.

    ~/asistente/venv/bin/python ~/asistente/panel.py estado
    ~/asistente/venv/bin/python ~/asistente/panel.py volumen 5
    ~/asistente/venv/bin/python ~/asistente/panel.py recordatorio-agregar   < "09:00 Tomar la pastilla"
    ~/asistente/venv/bin/python ~/asistente/panel.py recordatorio-borrar    < "09:00 Tomar la pastilla"
    ~/asistente/venv/bin/python ~/asistente/panel.py reiniciar
    ~/asistente/venv/bin/python ~/asistente/panel.py probar-luces
    ~/asistente/venv/bin/python ~/asistente/panel.py radio-apagar

Siempre contesta UNA línea en JSON (un formato de texto que otro programa lee
fácil). Los textos van por la entrada estándar y no como argumentos: así un
apóstrofo o una comilla en un recordatorio no rompen nada.
"""
import contextlib
import io
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

CASA = Path.home() / "asistente"
CONFIG = Path.home() / ".config" / "asistente"
CONTROL = ("127.0.0.1", 47475)   # la charla escucha órdenes acá (solo dentro de la Pi)
sys.path.insert(0, str(CASA))

import luces          # noqa: E402
import personas       # noqa: E402
import recordatorios  # noqa: E402
from telegram_bot import leer_env  # noqa: E402


def correr(*comando):
    return subprocess.run(comando, capture_output=True, text=True).stdout.strip()


def gasto():
    hoy = time.strftime("%Y-%m-%d")
    total = {"hoy": 0.0, "mes": 0.0, "charlas_hoy": 0}
    archivo = CASA / "consumo.log"
    for linea in archivo.read_text().splitlines() if archivo.exists() else []:
        usd = re.search(r"USD ([0-9.]+)", linea)
        if not usd:
            continue
        if linea.startswith(hoy[:7]):
            total["mes"] += float(usd.group(1))
        if linea.startswith(hoy):
            total["hoy"] += float(usd.group(1))
            total["charlas_hoy"] += 1
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in total.items()}


def proximos_cumples(cuantos=4):
    datos = personas.cargar()
    hoy = time.localtime()
    lista = []
    for p in [datos.get("ella", {})] + datos.get("persona", []):
        fecha = personas._cumple(p)
        if not p.get("nombre") or not fecha:
            continue
        dia, mes = (int(x) for x in fecha.split("/"))
        este_anio = time.mktime((hoy.tm_year, mes, dia, 0, 0, 0, 0, 0, -1))
        hoy0 = time.mktime((hoy.tm_year, hoy.tm_mon, hoy.tm_mday, 0, 0, 0, 0, 0, -1))
        dias = round((este_anio - hoy0) / 86400)
        if dias < 0:
            dias = round((time.mktime((hoy.tm_year + 1, mes, dia, 0, 0, 0, 0, 0, -1)) - hoy0) / 86400)
        lista.append({"nombre": p.get("apodo") or p["nombre"], "fecha": fecha, "dias": dias})
    return sorted(lista, key=lambda c: c["dias"])[:cuantos]


def ultimas_frases(cuantas=8):
    """La charla de hoy, desde el registro: junta los pedacitos de cada turno."""
    # Solo las últimas líneas del día (no todo el registro): alcanza para las últimas frases.
    texto = correr("journalctl", "-u", "asistente-charla", "--since", "today", "-n", "400", "-o", "cat", "--no-pager")
    turnos = []
    for linea in texto.splitlines():
        quien = "ella" if linea.startswith("  👵") else "asistente" if linea.startswith("  🤖") else None
        if not quien:
            continue
        dicho = linea[4:].strip()
        if turnos and turnos[-1]["quien"] == quien:
            turnos[-1]["texto"] += " " + dicho
        else:
            turnos.append({"quien": quien, "texto": dicho})
    return turnos[-cuantas:]


def estado():
    wifi = next((l.split(":", 1)[1] for l in correr("nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi").splitlines()
                 if l.startswith("yes:")), "")
    try:  # el archivo del sistema: sin lanzar un programa
        temp = round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
    except (OSError, ValueError):
        temp = None
    memoria = CONFIG / "memoria.md"
    try:
        volumen = int((CONFIG / "volumen").read_text())
    except (OSError, ValueError):
        volumen = None
    return {
        "nombre": leer_env(CONFIG / "ajustes.env").get("NOMBRE_ASISTENTE", "Asistente"),
        "servicios": dict(zip(("charla", "luces"),
                              correr("systemctl", "is-active", "asistente-charla", "asistente-luces").split())),
        "encendida_horas": round(float(Path("/proc/uptime").read_text().split()[0]) / 3600, 1),
        "temperatura": temp,
        "wifi": wifi,
        "volumen": volumen,
        "recordatorios": [{"fecha": r["fecha"] or "", "hora": r["hora"], "texto": r["texto"]}
                          for r in recordatorios.todos()],
        "gasto": gasto(),
        "cumples": proximos_cumples(),
        "frases": ultimas_frases(),
        "notas": [l for l in memoria.read_text().splitlines() if l.strip()][-10:] if memoria.exists() else [],
        "radio": radio_sonando(),
        "hora": time.strftime("%H:%M"),
    }


def radio_sonando():
    """El nombre de la radio que suena, o "" (la charla lo anota al ponerla)."""
    archivo = CONFIG / "radio-sonando"
    if archivo.exists() and correr("pgrep", "-x", "mpv"):
        return archivo.read_text().strip()
    return ""


def volumen(nivel):
    nivel = max(1, min(10, int(nivel)))
    if correr("systemctl", "is-active", "asistente-charla") == "active":
        # La charla guarda el nivel en memoria: se lo pedimos a ella, así no se pisan.
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(f"volumen {nivel}".encode(), CONTROL)
    else:
        from volumen import Volumen
        with contextlib.redirect_stdout(io.StringIO()):  # que su "🔊 Volumen" no ensucie el JSON
            Volumen().fijar(nivel)
    return {"volumen": nivel}


def recordatorio_agregar(texto):
    """'09:00 texto' (todos los días) o '27/11 17:00 texto' (una sola vez)."""
    r = recordatorios._parsear(texto)
    if r is None:
        raise ValueError("escribilo como «09:30 texto» o «27/11 09:30 texto»")
    return {"agregado": recordatorios.agregar(r["hora"], r["texto"], r["fecha"])}


def recordatorio_borrar(texto):
    if not recordatorios.borrar(exacto=texto.strip()):
        raise ValueError("no encontré ese recordatorio")
    return {"borrado": texto.strip()}


def probar_luces():
    for e in ("escuchando", "hablando", "recordatorio", "esperando"):
        luces.luz(e)
        time.sleep(1.2)
    return {"luces": "probadas"}


def main():
    orden = sys.argv[1] if len(sys.argv) > 1 else "estado"
    try:
        if orden == "estado":
            r = estado()
        elif orden == "volumen":
            r = volumen(sys.argv[2])
        elif orden == "recordatorio-agregar":
            r = recordatorio_agregar(sys.stdin.read())
        elif orden == "recordatorio-borrar":
            r = recordatorio_borrar(sys.stdin.read())
        elif orden == "reiniciar":
            subprocess.run(["sudo", "systemctl", "restart", "asistente-charla"], check=True)
            r = {"reiniciado": True}
        elif orden == "probar-luces":
            r = probar_luces()
        elif orden == "radio-apagar":
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"radio apagar", CONTROL)
            r = {"radio": "apagada"}
        else:
            raise ValueError(f"no conozco la orden {orden}")
        print(json.dumps({"ok": True, **r}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
