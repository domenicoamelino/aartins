#!/usr/bin/env bash
set -euo pipefail
bundle=$(cd -- "$(dirname -- "$0")" && pwd)
target="$HOME/ai-platform/ingestion-monitor"
[[ -f "$HOME/ai-platform/ingestion/config.json" && -f "$HOME/ai-platform/ingestion/ingest_meetings.py" ]] || { echo 'Existing configured ingestion installation not found.'; exit 1; }
[[ ! -e "$target" ]] || { echo "Target exists; nothing overwritten: $target"; exit 1; }
cd "$bundle"
python3 -m unittest -v test_monitor test_telegram
umask 077
mkdir -p "$target"
for name in run_monitor.py telegram_notify.py dashboard.html meeting-monitor.service monitor.conf activate.sh private_web.py rollback.sh README.md START-HERE.md VALIDATION.txt; do
    install -m 600 "$bundle/$name" "$target/$name"
done
echo "Installed new monitor files in $target"
echo 'Existing ingestion configuration, API key, state, worker, proxy and timer were not changed.'
echo "Next: python3 $target/run_monitor.py configure"
