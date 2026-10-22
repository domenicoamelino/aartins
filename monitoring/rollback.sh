#!/usr/bin/env bash
set -euo pipefail
target="$HOME/ai-platform/ingestion-monitor"
units="$HOME/.config/systemd/user"
drop="$units/meeting-ingestion.service.d/monitor.conf"
if systemctl --user is-active --quiet meeting-ingestion.service; then
    echo 'An ingestion service run is active. Finish it before rolling back monitoring.'
    exit 1
fi
if [[ -f "$drop" ]] && ! cmp -s "$drop" "$target/monitor.conf"; then
    echo 'Monitor drop-in has changed; nothing removed. Review it before rollback.'
    exit 1
fi
python3 "$target/private_web.py" disable
was_active=false
if systemctl --user is-active --quiet meeting-ingestion.timer; then was_active=true; fi
systemctl --user stop meeting-ingestion.timer
trap 'systemctl --user daemon-reload; if [[ "$was_active" == true ]]; then systemctl --user start meeting-ingestion.timer; fi' EXIT
systemctl --user disable --now meeting-monitor.service
rm -f -- "$drop"
# Leave the disabled dashboard unit, history, configuration and credentials for recovery.
systemctl --user daemon-reload
if [[ "$was_active" == true ]]; then systemctl --user start meeting-ingestion.timer; fi
trap - EXIT
echo 'Original ingestion command restored. Timer schedule, ingestion state and all meeting files retained.'
echo 'Run history and monitor settings remain in ~/ai-platform/ingestion-monitor.'
