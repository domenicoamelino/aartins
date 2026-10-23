# Validation at the 23 October move checkpoint

This is a development checkpoint, not an all-green release. Existing runtime
behavior was preserved; no further recap tuning was undertaken for the move.

- Current review/approval/speaker/report suite: 31 tests (19 workflow + 11 report
  guards + one move-checkpoint WAL backup/idle test). All 31 passed.
- Existing monitoring suite: 26 tests passed, fake delivery only. Real Telegram
  completion delivery was separately confirmed by the owner.
- Legacy root suite: 49 tests ran; four failures and 17 errors against the updated
  implementation. Many fake model responses lack the new verification format;
  old upload fixtures omit required expected_languages and old session response
  assertions expect fields absent from the current public response. Client metadata
  encoding/default changes also need reconciliation. Do not assume all failures
  are harmless fixture changes; triage API/CLI compatibility before release.
- Legacy ingestion suite: 27 tests ran; 16 failures and five errors. Old fixtures
  assume completed/unapproved root files are ingestible. This conflicts with the
  explicit immutable approval gate; current review tests cover approved snapshots,
  interrupted/resumed writes and replacement, but do not replace a full migration
  of the legacy suite.
- tools/check_all.py retains ALL suites, runs them independently and exits nonzero
  if any fails. tools/check_review.py provides the current checkpoint suite.
- Live review edits/approvals, nightly indexing/replacement and meeting dashboard
  acceptance are still pending. A passing offline test does not establish recap
  quality. The owner explicitly paused recap tuning at its present quality.
- No model inference, SSH session, Linux shutdown/startup or GitHub push was
  performed from this Windows workspace. Runtime source fingerprints and database
  snapshots are created by the user on MINISFORUM using move_checkpoint.py.

The repository contains no real recording/transcript/report from this session.
Runtime secrets, review databases, model cache and private checkpoints stay out
of Git. Existing source/units retain their repository layout; deployment paths
remain unchanged.
