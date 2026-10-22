# Start ingestion on the UM870

Keep each original file named `knowledge.md` in its own meeting folder. The ingestion tool gives new Open WebUI uploads unique names automatically.

1. Extract this package on the UM870 to `~/meeting-ingestion` (the folder containing install.sh).

2. Install:

   ```bash
   cd ~/meeting-ingestion
   bash -n install.sh
   bash install.sh
   ```

3. Have an Open WebUI API key ready. Reuse your existing key if you have one. If necessary, enable API keys in **Admin Panel > Settings > Authentication**, then create/retrieve the key in your **personal Settings > Account > API keys/Secrets**. Do not send the key in chat.

4. Configure; choose the existing **Meeting Archive** collection from the list:

   ```bash
   python3 ~/ai-platform/ingestion/ingest_meetings.py configure
   ```

5. Preview without changing Open WebUI:

   ```bash
   python3 ~/ai-platform/ingestion/ingest_meetings.py sync
   ```

6. When no recap/upload is running, apply one meeting and inspect status:

   ```bash
   python3 ~/ai-platform/ingestion/ingest_meetings.py sync --apply --limit 1
   python3 ~/ai-platform/ingestion/ingest_meetings.py status
   ```

An exact copy of your manually uploaded knowledge.md should be ADOPTED, without another embedding run. That adopted file keeps its existing name. New uploads receive a date/title/meeting-ID/version name.

Verify the file in Meeting Archive and ask a question with `#Meeting Archive`. Run sync again; it should report UNCHANGED. Once this works, the command below ingests all new/changed completed meetings on demand:

```bash
python3 ~/ai-platform/ingestion/ingest_meetings.py sync --apply
```

Nightly scheduling is optional and disabled until you follow the instructions in README.md. Keep thinking and retrieval-query generation Off; the tool does not change them. README.md also contains backup, rollback, failure-recovery and evidence-link limitations.
