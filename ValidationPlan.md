# Validation Plan - F8 (Teams Realtime Translator)

## Objective
Close phase F8 with reproducible evidence from real Microsoft Teams sessions, using measurable latency and reliability metrics.

## Preconditions
- Virtual audio routing is configured (VB-Cable on Windows or BlackHole on macOS).
- `.env` contains:
  - `METRICS_ENABLED=1`
  - `METRICS_OUTPUT_PATH=./reports/session_metrics.jsonl`
  - `METRICS_SUMMARY_PATH=./reports/session_summary.json`
  - `METRICS_MIN_TEXT_LEN=8`
- Debug mode can be toggled from the overlay (`Debug` checkbox).

## Session Matrix (required)
1. Session A: 30 minutes, normal meeting pace.
2. Session B: 30 minutes, mixed speakers and accents.
3. Session C: 60 minutes, sustained load.
4. Session D: 30 minutes, stress case (background noise + language switches).

## Execution Checklist (per session)
1. Start the app and verify overlay status is `Listening to system audio...`.
2. Confirm metrics files are being updated in `./reports/`.
3. Record qualitative notes during the session:
   - missed fragments
   - duplicated lines
   - incorrect translations of technical terms
   - visible latency spikes
4. Stop the app and capture generated summary metrics.
5. Archive artifacts:
   - `session_metrics.jsonl` (or session-specific copy)
   - `session_summary.json`
   - short note with date, scenario, and observed issues

## Acceptance Criteria for F8
- Four sessions completed with saved artifacts.
- `session_summary.json` generated for each run.
- Metrics include segment timings and error events.
- Known issue list is produced with concrete evidence (timestamps + scenario).
- F8 status can move to `Completed`, and F9 prioritization is based on measured bottlenecks.

## Suggested Reporting Template
- Session ID:
- Date:
- Scenario:
- Avg latency (s):
- P95 latency (s):
- Issue rate (%):
- Top 3 observed issues:
