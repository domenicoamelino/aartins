# Baseline validation — 21 October 2026

The reusable checkout passed **41 offline tests**: 30 reporter tests, four Pipe tests and seven worker tests. Added checks cover selected languages reaching ASR/reporting, user settings as dictionary/object, invalid setting rejection, idempotency and additive migration of an existing jobs database. They ran from the repository root with Python's unittest runner. ASR, Ollama and the Open WebUI dependency interfaces are simulated; this run does not imply an on-server redeployment.

User-confirmed runtime milestones in this project:

- A complete CLI transcript-to-report run produced a satisfactory readable report.
- A background audio job could be tracked and its completed report read from the archive.
- Open WebUI 0.12.3 reached the worker health endpoint from its host-network container.
- The Nginx loopback proxy and Tailscale route were tested successfully.
- A report-writing failure was recovered after installing reporter 2.2.4.
- The updated Pipe returned recap-only output; the user confirmed the result works.

The following are not established by this baseline: clean-machine provisioning, an exact full dependency lock, alternate-model quality, a one-hour recording benchmark, automatic backup restoration, cross-meeting retrieval or knowledge-base ingestion.

Before marking a deployed update accepted, record its Git commit, model tag/digest, test recording, observed processing time and checked output. Keep real meeting content and detailed deployment inventory in private storage outside Git.
