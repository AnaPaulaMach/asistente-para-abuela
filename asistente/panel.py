#!/usr/bin/env -S sh -c 'exec "$HOME/asistente/venv/bin/python" "$0" "$@"'
"""Lo que el panel de control de la compu le pide a la Pi, por ssh.

    ~/asistente/venv/bin/python ~/asistente/panel.py estado
    ~/asistente/venv/bin/python ~/asistente/panel.py volumen 5
    ~/asistente/venv/bin/python ~/asistente/panel.py recordatorio-agregar   < "09:00 Tomar la pastilla"
    ~/asistente/venv/bin/python ~/asistente/panel.py recordatorio-borrar    < "09:00 Tomar la pastilla"
    ~/asistente/venv/bin/python ~/asistente/panel.py reiniciar
    ~/asistente/venv/bin/python ~/asistente/panel.py probar-luces

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
    texto = correr("journalctl", "-u", "asistente-charla", "--since", "today", "-o", "cat", "--no-pager")
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
    temp = re.search(r"([0-9.]+)", correr("vcgencmd", "measure_temp"))
    memoria = CONFIG / "memoria.md"
    try:
        volumen = int((CONFIG / "volumen").read_text())
    except (OSError, ValueError):
        volumen = None
    return {
        "nombre": leer_env(CONFIG / "ajustes.env").get("NOMBRE_ASISTENTE", "Asistente"),
        "servicios": {s: correr("systemctl", "is-active", f"asistente-{s}") for s in ("charla", "luces")},
        "encendida_horas": round(float(Path("/proc/uptime").read_text().split()[0]) / 3600, 1),
        "temperatura": float(temp.group(1)) if temp else None,
        "wifi": wifi,
        "volumen": volumen,
        "recordatorios": [{"hora": h, "texto": t} for h, t in recordatorios.leer()],
        "gasto": gasto(),
        "cumples": proximos_cumples(),
        "frases": ultimas_frases(),
        "notas": [l for l in memoria.read_text().splitlines() if l.strip()][-10:] if memoria.exists() else [],
        "hora": time.strftime("%H:%M"),
    }


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


def _linea_valida(texto):
    hora, _, resto = texto.strip().partition(" ")
    try:
        t = time.strptime(hora, "%H:%M")
    except ValueError:
        raise ValueError(f"la hora «{hora}» no es válida: escribila como 09:30") from None
    if not resto.strip():
        raise ValueError("falta el texto del recordatorio")
    return f"{t.tm_hour:02d}:{t.tm_min:02d} {resto.strip()}"


def recordatorio_agregar(texto):
    linea = _linea_valida(texto)
    archivo = recordatorios.ARCHIVO
    previo = archivo.read_text() if archivo.exists() else ""
    archivo.write_text(previo + ("" if previo.endswith("\n") or not previo else "\n") + linea + "\n")
    return {"agregado": linea}


def recordatorio_borrar(texto):
    buscado = _linea_valida(texto)
    archivo = recordatorios.ARCHIVO
    lineas = archivo.read_text().splitlines()
    for i, linea in enumerate(lineas):
        if linea.strip() and not linea.startswith("#"):
            try:
                if _linea_valida(linea) == buscado:
                    del lineas[i]
                    archivo.write_text("\n".join(lineas) + "\n")
                    return {"borrado": buscado}
            except ValueError:
                continue
    raise ValueError("no encontré ese recordatorio")


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
        else:
            raise ValueError(f"no conozco la orden {orden}")
        print(json.dumps({"ok": True, **r}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
