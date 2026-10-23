# MVP closure checkpoint — 23 October 2026

Decision: freeze recap tuning for now. The current quality is acceptable to the
owner for continuing workflow validation, with the limitations below. This is
not a claim of factual correctness or complete end-to-end acceptance.

## Current implementation and evidence

| Area | State |
|---|---|
| Local upload, metadata and EN/NL/IT selections | Implemented; exercised in server tests |
| Word-timed transcription and CPU diarization | Implemented; two clusters receive words when count is 2 |
| Automatic speaker count | Earlier isolated benchmark detected two; current full upload auto-mode still needs acceptance |
| Speaker identity | Anonymous estimates only; manual cluster/turn corrections implemented, live acceptance pending |
| Telegram completion | User confirmed delivery |
| Review commands, revision history and explicit approval | Implemented; offline tests pass, live acceptance pending |
| Approval-only ingestion and revision replacement | Implemented; offline tests pass, live nightly acceptance pending |
| Meeting review/edit dashboard | NOT implemented. Existing monitoring dashboard only shows ingestion runs |
| Recap quality | Owner accepts for now; incomplete coverage and unsupported interpretations remain possible |

The latest supplied candidate (20:38, 23 October) is a separate candidate, not
an automatically published Open WebUI revision. It is not approved. Preserve
its folder alongside the source. No test recap should be approved merely to
make the dashboard status green.

Current reporter is 2.6.3-claim-guards. Candidate generation leaves current review
and indexed revisions unchanged. The backend and Pipe use a separate version
number; do not infer the entire workflow version from the reporter alone.

## Closure sequence after the move

1. Restore connectivity and verify health using MOVE-RUNBOOK.md. No upgrade or
   deployment during restart. Confirm existing jobs and review records survived.
2. Review one existing completed meeting in Open WebUI using the same account:
   `review JOB_ID`, `transcript JOB_ID`, `changes JOB_ID`. Record current revision.
3. Test speaker mapping/correction and recap feedback using COMMANDS-REVIEW.md.
   Confirm the new revision appears, old revision survives, and a stale revision
   mutation is rejected. Check ownership with a second account if available.
4. Save a reviewed replacement recap with explicit known corrections. Approve
   exactly its current revision. Plain conversational 'okay' must not approve.
   Unapproved meetings must remain excluded from ingestion.
5. Run ingestion read-only (`sync` without --apply) and inspect its plan. Then
   manually start the existing user meeting-ingestion.service once. Verify the
   exact approved content in Open WebUI Knowledge and inspect the run result.
6. Revise the same indexed meeting without approval. Confirm the old approved
   revision stays indexed. Approve the replacement, run ingestion again, and
   verify replacement without duplicate indexed content.
7. Enable the existing nightly timer only after the manual test succeeds. Check
   the next run and verify the following morning's indexing/logs/notification.
8. Build the authenticated meeting dashboard using this proven workflow:
   meeting list, processing/review/indexed status and errors; open report and
   transcript; edit speaker mapping and recap; Save and close creates a draft;
   Approve for knowledge base is separate. Show current vs approved vs indexed
   revision. Processing/indexed states reflect actual system results, not free
   manual status changes. Include per-meeting links in Open WebUI and Telegram.
9. Acceptance: one new short recording through upload -> processing -> Telegram
   -> dashboard review/edit -> explicit approval -> nightly indexing -> approved
   replacement. Verify service restart recovery and owner isolation too.

## Open issues retained, not silently solved

- ASR names/technical words can be wrong; labels do not identify real people.
- 78 low-confidence fragments and eight zero-duration fragments in the saved
  two-speaker test; no fabricated timestamp repair was applied.
- Recap coverage and factuality are not consistently validated by local model
  verification. Phrase-specific English guards are not multilingual guarantees.
- Personal history is excluded from narrative synthesis pending identity review;
  the latest real output still leaked personal background. This remains open.
- Three participants cannot be inferred from a names list. Known count means
  TOTAL speakers, including the user; blank means automatic, 1 constrains to one.
- Dashboard security, direct meeting URLs and indexed revision presentation are
  outstanding implementation work, not already deployed functionality.
- Direct filesystem editing does not constitute approval. Reviews bind exact
  immutable content hashes; use supported review operations.
- Legacy indexed material is not retroactively deleted or approved. Legacy
  pre-review pending operations can require manual reconciliation.

The old candidate archives are useful diagnostics, not a need to keep installing
old packages. Keep runtime source, databases and secrets on MINISFORUM; Git holds
code and documentation only. Prior runbooks remain historical where they differ
from this checkpoint.
