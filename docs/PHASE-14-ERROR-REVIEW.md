# PHASE 14 — ERROR REVIEW

Date: 2026-10-20. Status: COMPLETE — delivered for review. Nothing was deployed.

Checkpoint 7 requires a review queue for the ways a screenshot evaluation can
go wrong, and a way for authorised reviewers to correct labels **without
rewriting original predictions**. This document describes the queue, the
detection rules, and the separation of concerns that keeps corrections honest.

## The queue

Model: `ReviewQueueItem` (`apps/screenshot_eval/models.py`).
Service: `ReviewQueueService` (`apps/screenshot_eval/services/review.py`).
Page: `/dashboard/review-queue/` (`templates/dashboard/review_queue.html`).
Command: `python manage.py scan_review_queue [--owner <user>]`.

Each item links to the case, recognition and/or prediction it concerns, and
carries `kind`, `state`, `summary`, a `detail` JSON blob, and the reviewer
correction fields.

## Problem kinds (as required)

| Kind | Raised when |
| --- | --- |
| `misidentified_pattern` | a recognition disagrees with the case's human label (`matches_label is False`) |
| `incorrect_breakout` | a recognition is `INVALIDATED` (recorded invalidations) |
| `false_support_resistance` | a support/resistance annotation is `skipped`/`qualitative` for unreliable coordinates |
| `missing_confirmation_candle` | a recognition is `AWAITING_CONFIRMATION` |
| `wrong_timeframe` | the case timeframe is `unknown` or conflicts with the analysis metadata |
| `contradictory_evidence` | a recognition carries recorded `contradictions` |
| `incorrect_outcome` | a verified outcome is `incorrect` |
| `vision_model_uncertainty` | the analysis observation confidence is below the low-confidence threshold |
| `incomplete_formation` | a recognition is `FORMING` |

## States

`open` → `in_review` → `resolved` / `dismissed`.

`ReviewQueueService.scan` is **idempotent**: an already-open item for the same
`(kind, linked record)` is returned unchanged and is not counted as newly
created (asserted by test).

## Corrections never rewrite originals

The single most important rule of Checkpoint 7. When a reviewer resolves an
item:

- the correction (`correction` JSON) and the `resolution_note` are stored **on
  the queue item**;
- the original `ScreenshotRecognition` / `ForwardPaperPrediction` rows are
  **never mutated**;
- a locked prediction stays locked — its direction, status and digest are
  unchanged (asserted by test `test_review_correction_never_rewrites_prediction`).

This lets the forward-testing metrics keep the honest record of what was
predicted while still capturing reviewer judgement for later analysis.

## Authorisation

- `ReviewQueueService.resolve` requires the owner or a staff reviewer; another
  user raises `PermissionError` (asserted by test).
- The resolve view enforces the same owner/staff check (`404` otherwise).
- The scan view scopes to the owner for non-staff users.

## Escalation from evaluation errors

`scan` also raises `incorrect_outcome` items from verified outcomes that came
back `incorrect`, so a systematic recognition problem surfaces in the same queue
as a one-off mislabel.

## Honesty

- The queue never resolves itself; only a human reviewer resolves or dismisses.
- A dismissed item is recorded as dismissed, not deleted.
- Corrections are advisory inputs to future dataset labels; they do not
  retroactively change any prediction or outcome that has already been recorded.

See `docs/PHASE-14-FORWARD-TESTING.md` and `docs/PHASE-14-COMPLETION-REPORT.md`.
