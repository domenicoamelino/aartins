#!/usr/bin/env bash
set -euo pipefail
bundle=$(cd -- "$(dirname -- "$0")" && pwd)
target="$HOME/ai-platform/ingestion"
if [[ -e "$target" ]]; then
    echo "Target already exists: $target. No files were overwritten."
    exit 1
fi
cd "$bundle"
python3 -m unittest -v test_ingestion
umask 077
mkdir -p "$target"
for name in ingest_meetings.py README.md VALIDATION.txt meeting-ingestion.service meeting-ingestion.timer; do
    install -m 600 "$bundle/$name" "$target/$name"
done
echo "Installed new ingestion tool in $target"
echo 'No existing service was changed and nightly scheduling is not enabled.'
echo "Next: python3 $target/ingest_meetings.py configure"
