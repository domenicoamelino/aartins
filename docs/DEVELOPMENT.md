# Development notes

## Baseline and checks

Python 3.10+ is the code target. Run tests from repository root:

```bash
python -m unittest discover -s tests -v
```

The suite covers reporter extraction/schema/provenance, writing/resume/context bounds, worker HTTP/SQLite flow with simulated Whisper/Ollama, and Pipe control flow/recap-only responses using stub dependencies. It is not an installed Open WebUI/browser test. Every model/prompt change also needs a short real recording test. Use synthetic fixtures for committed tests; keep actual meeting recordings out of Git.

`requirements-asr.txt` records faster-whisper 1.2.1. This is not a complete lock: exact Python/PyAV/CTranslate2 and other resolved dependencies must be captured privately from the server before attempting a clean rebuild. The reporter itself is stdlib. Open WebUI provides the Pipe's httpx/pydantic dependencies. Do not run pip installation against the accepted environment merely because a requirements file exists.

## Working convention

1. Make changes in the checkout, with runtime secrets/data elsewhere.
2. Run offline tests and review the diff.
3. Commit the change with a concrete description.
4. Deploy only reviewed files; see adoption guide.
5. Validate real runtime behavior, retain rollback copy and note the deployed commit.

The initial PoC snapshot commit uses a local automation identity, not the user's authorship identity. Configure your own `git config user.name` and `git config user.email` for future commits. Project source is MIT licensed; upstream software and model weights have their own terms.

## Known constraints worth preserving in issue tracking

- Only one processing thread; no cancellation endpoint, automatic retention or automatic failed-job retry.
- Restart recovery repeats interrupted jobs from audio; writing-failure recovery is manual and not concurrency locked.
- Recovery helper requires a failed job with transcript and analysis manifest. It leaves that job failed if recovery fails; do not run duplicate recoveries.
- API returns completed report/transcript to the authenticated Pipe even though chat displays only recap.
- Long-running Pipe request may be interrupted by client/server behavior; status reconnect remains necessary.
- Evidence refs/quotes and kind checks are structural safeguards, not a full semantic verifier.
- Old report messages are immutable chat history; replacing a Function does not rewrite them.
- No automatic deploy/publish from Git. No remote repository or cloud CI is configured.
- Full-server provisioning and dependency/image lock await verified server inventory.
