"""El clima para el asistente, con Open-Meteo (gratis, sin cuenta ni clave).

Las coordenadas van en ~/.config/asistente/ajustes.env (CLIMA_LAT y CLIMA_LON), no en
el código: así el repositorio no dice dónde vive nadie.
Devuelve un resumen corto que Gemini convierte en una frase.
"""
import json
import urllib.parse
import urllib.request

from telegram_bot import CONFIG, leer_env

# Códigos de clima de la OMM que usa Open-Meteo, en castellano.
CIELO = {
    0: "despejado", 1: "casi despejado", 2: "algo nublado", 3: "nublado",
    45: "con neblina", 48: "con neblina",
    51: "con llovizna", 53: "con llovizna", 55: "con llovizna",
    56: "con llovizna", 57: "con llovizna",
    61: "con lluvia débil", 63: "con lluvia", 65: "con lluvia fuerte",
    66: "con lluvia", 67: "con lluvia",
    71: "con nieve", 73: "con nieve", 75: "con nieve", 77: "con nieve",
    80: "con algún chaparrón", 81: "con chaparrones", 82: "con chaparrones fuertes",
    85: "con nieve", 86: "con nieve",
    95: "con tormenta", 96: "con tormenta y granizo", 99: "con tormenta y granizo",
}


def consultar():
    ajustes = leer_env(CONFIG / "ajustes.env")
    if "CLIMA_LAT" not in ajustes or "CLIMA_LON" not in ajustes:
        return {"error": "no está configurado el lugar"}
    parametros = urllib.parse.urlencode({
        "latitude": ajustes["CLIMA_LAT"],
        "longitude": ajustes["CLIMA_LON"],
        "current": "temperature_2m,apparent_temperature,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "America/Argentina/Buenos_Aires",
        "forecast_days": 2,
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{parametros}", timeout=10) as r:
        datos = json.load(r)
    ahora, dias = datos["current"], datos["daily"]

    def dia(i):
        return {
            "cielo": CIELO.get(dias["weather_code"][i], "variable"),
            "maxima": round(dias["temperature_2m_max"][i]),
            "minima": round(dias["temperature_2m_min"][i]),
            "probabilidad_de_lluvia": dias["precipitation_probability_max"][i],
        }

    return {
        "ahora": {
            "temperatura": round(ahora["temperature_2m"]),
            "sensacion_termica": round(ahora["apparent_temperature"]),
            "cielo": CIELO.get(ahora["weather_code"], "variable"),
        },
        "hoy": dia(0),
        "manana": dia(1),
    }


if __name__ == "__main__":
    print(json.dumps(consultar(), ensure_ascii=False, indent=2))
