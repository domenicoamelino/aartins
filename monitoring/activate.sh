#!/usr/bin/env bash
set -euo pipefail
target="$HOME/ai-platform/ingestion-monitor"
units="$HOME/.config/systemd/user"
drop="$units/meeting-ingestion.service.d/monitor.conf"
unit="$units/meeting-monitor.service"
[[ -f "$target/monitor.json" ]] || { echo 'Run dashboard configure first.'; exit 1; }
[[ ! -e "$drop" && ! -e "$unit" ]] || { echo 'Monitor unit/drop-in already exists; nothing overwritten.'; exit 1; }
if systemctl --user is-active --quiet meeting-ingestion.service; then
    echo 'An ingestion service run is active. Finish it before activation.'
    exit 1
fi
python3 "$target/run_monitor.py" check
systemctl --user cat meeting-ingestion.service >/dev/null
umask 077
backup="$HOME/ai-platform/backups/meeting-monitor-$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$backup"
systemctl --user cat meeting-ingestion.service > "$backup/previous-ingestion-service.txt"
cp -p "$target/monitor.json" "$backup/monitor.json"
if [[ -f "$target/telegram-token.txt" ]]; then cp -p "$target/telegram-token.txt" "$backup/telegram-token.txt"; fi
was_active=false
if systemctl --user is-active --quiet meeting-ingestion.timer; then was_active=true; fi
echo "$was_active" > "$backup/timer-was-active.txt"
systemctl --user stop meeting-ingestion.timer
restore_on_error() {
    systemctl --user disable --now meeting-monitor.service >/dev/null 2>&1 || true
    rm -f -- "$drop" "$unit"
    systemctl --user daemon-reload
    if [[ "$was_active" == true ]]; then systemctl --user start meeting-ingestion.timer; fi
}
trap restore_on_error ERR
mkdir -p "$units/meeting-ingestion.service.d"
install -m 600 "$target/monitor.conf" "$drop"
install -m 600 "$target/meeting-monitor.service" "$unit"
systemctl --user daemon-reload
systemd-analyze --user verify "$unit" "$units/meeting-ingestion.service"
systemctl --user enable --now meeting-monitor.service
sleep 1
systemctl --user is-active --quiet meeting-monitor.service
if [[ "$was_active" == true ]]; then systemctl --user start meeting-ingestion.timer; fi
trap - ERR
echo "Backup: $backup"
echo 'Monitoring activated; existing timer schedule retained.'
echo 'Next: python3 ~/ai-platform/ingestion-monitor/private_web.py enable'
