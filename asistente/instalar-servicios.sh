#!/bin/bash
# Instala (o actualiza) los dos servicios para que el asistente arranque solo.
# Se corre en la Pi, una vez:  bash ~/asistente/instalar-servicios.sh
set -euo pipefail
cd "$(dirname "$0")"
for s in asistente-luces asistente-charla; do
  sed -e "s|@USUARIO@|$USER|g" -e "s|@CASA@|$HOME|g" "systemd/$s.service" \
    | sudo tee "/etc/systemd/system/$s.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now asistente-luces asistente-charla
systemctl is-active asistente-luces asistente-charla
