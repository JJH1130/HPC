# Where we stopped (2026-11-04)

Current task: v5.7 all years (`docs/handoff/v57_all_years_request.md`; `docs/conus_plan.md` "v5.7 all years").

- Code part: DONE and pushed (config 13 eras, `kept_years_check.py` + `sbatch/kept_years_check.sh`, all-TEST county
  columns + `--check-against` in `compare_models.py` / `metrics_over_time.py`, `external_city_meeting.py --version
  --version-label --base-dir`, `external_compare.py evaluate --reference --compare-versions --check-with`, submit mode
  `v57all`, runbook section 21, tests `tests/test_v57all.py` + additions in `test_external_city_meeting.py` /
  `test_external_compare.py`; all suites passed locally). The five tracked years already match
  `v54_nby_comparison.csv` locally (v5.7 1980: all-TEST R2 0.908, tract MdAPE 26.9 %).
- Alpine part: NOT run yet. `docs/runbooks/Running_CONUS.md` section 21:
  - If `logs/conus_v57all_jobs.txt` does not exist on Alpine, the chain was never submitted -> block 1.
  - If it exists -> block 2 (progress), then block 3 once every job left `squeue`.
- After block 3 is pushed: Claude pulls and analyses (KEPT YEARS OK, the MATCH lines, v5.7 1900-2020 next to v5.4 /
  v5.6 on all TEST counties, meeting maps v5.7, external v57); then the meeting doc is updated.
