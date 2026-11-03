# Where we stopped (2026-11-04, KST ~07:30 / MT 11-03 ~15:30)

Current task: v5.4 + nby without the filter (`docs/handoff/v54_nby_request.md`).

- PowerShell part: DONE and pushed (7d57127 WIP, 306cadf final: config `conus_rf_v3_all_nby.yaml`,
  `v54_nby_compare.py`, `undated_age_diag.py`, submit mode `v54nby`, tests, runbook section 20).
  A fresh PowerShell session: `git pull`, `git status` (commit anything left uncommitted), run
  `python tests/test_v54nby.py`, and check that every item of the request is in place. Nothing more to build unless
  something is missing.
- Alpine part: NOT confirmed yet. Run `docs/runbooks/Running_CONUS.md` section 20:
  - If `logs/conus_v54nby_jobs.txt` does not exist on Alpine, the chain was never submitted -> block 1.
  - If it exists -> block 2 (progress), then block 3 once every job left `squeue`.
  - CURC maintenance 2026-11-04 06:30-18:30 MT: jobs that cannot finish before it wait until after it (expected).
- After block 3 is pushed: Claude (cloud) pulls and analyzes; then the meeting doc is updated
  (section 7 = NobuiltYear results; sections 4 PLURAL / 5 built-cell county tables recomputed on ALL TEST counties).
