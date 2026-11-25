#!/bin/bash
# Suma una red WiFi a la Pi sin borrar las que ya conoce. NetworkManager se
# conecta sola a la que tenga cerca (por ejemplo, la de tu casa y la de
# tu abuela). Se corre en la Pi:
#     ssh -t pi bash ~/asistente/agregar-wifi.sh
# Ojo: la Pi Zero 2 W solo ve redes de 2,4 GHz.
set -euo pipefail

read -rp "Nombre de la red WiFi (2,4 GHz): " SSID
[ -n "$SSID" ] || { echo "Falta el nombre."; exit 1; }
while true; do
  read -rsp "Clave del WiFi (no se muestra): " CLAVE; echo
  [ ${#CLAVE} -ge 8 ] && [ ${#CLAVE} -le 63 ] && break
  echo "La clave WPA tiene que tener entre 8 y 63 caracteres."
done
# Se guarda la clave derivada (PSK de 64 caracteres), no la clave en texto plano.
PSK=$(wpa_passphrase "$SSID" "$CLAVE" | sed -n 's/^\s*psk=\([0-9a-f]\{64\}\)$/\1/p'); unset CLAVE
[ -n "$PSK" ] || { echo "No pude calcular la PSK."; exit 1; }

sudo nmcli connection delete "$SSID" >/dev/null 2>&1 || true   # si ya existía, se reemplaza
sudo nmcli connection add type wifi ifname wlan0 con-name "$SSID" ssid "$SSID" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" connection.autoconnect yes >/dev/null
unset PSK
echo "Listo: la Pi ahora conoce estas redes y usa la que tenga cerca:"
nmcli -t -f NAME,TYPE connection show | awk -F: '$2 == "802-11-wireless" {print "  - " $1}'
