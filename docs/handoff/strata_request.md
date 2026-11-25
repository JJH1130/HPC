git pull 받고 아래를 해줘. 사용자에게 하는 보고는 한국어로. 배경: open_items "Meeting with Stefan, 2026-11-25" point 5 (strata) +
"Ideas of the user (2026-11-26)" (strata by PLURAL x cell group; NTL as a within-group score). Stefan left the strata design to us.
docs/conus_plan.md "Cap transfer: result": v5.7's split of people between cell groups is about right; the remaining tract error is
WHICH cells inside a group get people. Test: split cells into area type (from PLURAL, per year) x cell group, keep v5.7's people per
(county, type, group) and only change the order inside each stratum with another model's weights. No change to v5.7 itself.

[0. New models (normal features / train / predict / validate chain, like earlier variants)]
- Era Y2010 of configs/conus_rf_v3_all_nby.yaml (v5.7) + one addition each, same search / split / folds / statuses / water mask:
  - Dasy_CONUS_RF_v3_all_nby_ntl   = + ntl  (DMSP NTL layer of the CONUS cutout, as Dasy_CONUS_RF_v3_ntl)
  - Dasy_CONUS_RF_v3_all_nby_ntlv  = + ntlv (VIIRS-like NTLV, as Dasy_CONUS_RF_v3_ntlv)
  - Dasy_CONUS_RF_v3_all_nby_pq5ntl  = + ntl + plural (the pq5 plural block of conus_rf_v3_all_nby_pq5.yaml)
  - Dasy_CONUS_RF_v3_all_nby_pq5ntlv = + ntlv + plural
  2010 only (PLURAL grid 1940 / 1980 / 2010; NTL from 1992). Their own full-version results (county CV / all-TEST, tracts) go in the
  table next to v5.7 and pq5 as reference rows (compare_models.py as before).
- Existing: v5.7 (Dasy_CONUS_RF_v3_all_nby) and pq5 (Dasy_CONUS_RF_v3_all_nby_pq5) pop_{1940,1980,2010}.tif.

[1. Strata (years 1940, 1980, 2010)]
- Cell group (as missed_cells / cap_allocation): built (BUI_Y > 0) / undated (BUI_Y = 0, NOBUILT > 0) / no_record.
- Area type per cell from PLURAL_Y (cutout layer PLURAL, bilinear; 0 = urban, 1 = rural): urban / peri_urban / rural by two
  breaks t1 < t2, fixed ONCE from 2010 and used for every year (PLURAL is computed per year from that year's places, so the same
  breaks give era-specific classes):
  - calibration source = GHS-SMOD 2010 cell classes (scheme A, per 250 m cell: urban 30 / peri_urban 21-23 / rural 11-13; water 10
    and cells without a class left out), over the 2010 study cells (v5.7 mask);
  - rule (fixed before results): t1 = the PLURAL value whose share of cells below it equals the SMOD urban cell share; t2 = the value
    whose share below it equals the urban + peri_urban share (quantile matching on cell counts). Log t1, t2, the 2010 confusion
    matrix PLURAL class vs SMOD class (counts and agreement), and the class shares per year.
  - GHS-SMOD enters only these two numbers (no cell values of GHS-POP anywhere); say so in the log / docs.
- Strata = 3 types x 3 groups = 9 per year. Report cells and v5.7 people per stratum and year.

[2. Allocation]
- Caps = v5.7's own people per (county, type, group) (= v5.7 exactly when the score is v57 everywhere; check, else stop).
- Inside a stratum of a county: people x score_i / sum(score) with score = that model's cell people (pop_Y.tif). Zero score sum
  -> keep v5.7 (log counts). County sums = census (check).
- Candidate scores per year: 1940 / 1980: v57, pq5. 2010: v57, pq5, ntl, ntlv, pq5ntl, pq5ntlv (the new models).

[3. Selection and report (rule fixed before results; tracts are not used to report what they chose)]
- Tracts = v5.7's evaluated tracts of the year (tract_errors_Y.csv), split by the county TRAIN / TEST label of conus_split.csv.
- Per year and stratum: swap only that stratum's score (all others v57), tract MdAPE on TRAIN-county tracts; choose the score with
  the lowest MdAPE if it beats v57 by more than 0.1 pp, else v57. Then one combined allocation with every stratum's chosen score.
- Report on TEST-county tracts: v5.7 vs combined vs each single full model (pq5, and 2010 the four new) -> MdAPE / MAPE for all, dens_*,
  gap / no_gap, kept / excluded t070, fixed 1980 county class; tract area type = the type holding most of the tract's cells.
- Also the per-stratum table (TRAIN MdAPE of every score, chosen score, TEST d_mdape of that single swap) so the effect of each
  stratum is visible. No further selection.

[Outputs]
- results/validation/conus/strata/: breaks.csv (t1, t2, shares, confusion), strata_cells.csv, stratum_scores.csv (year x stratum x score,
  TRAIN / TEST MdAPE), chosen.csv, test_metrics.csv (year x method x part), strata_mdape.png; new versions' usual result files.

[Common]
- New script src/validation/strata.py (+ breaks step), sbatch/strata.sh; submit_conus.sh mode strata = 4 new versions
  (features / train / predict / validate, side by side) -> strata job (after all four) ; pre-check (layers NTL / NTLV / PLURAL / SMOD,
  configs). Reuse the cap_allocation / missed_cells strip, group and tract code.
- Local tests (synthetic): quantile-matched breaks by hand; v57 everywhere = v5.7 cells and tract file; swap inside one stratum moves
  people only within that (county, type, group); county sums; selection uses only TRAIN tracts (changing a TEST tract leaves the choice
  unchanged); the 0.1 pp rule; configs = v5.7 Y2010 + one addition (mutations stop).
- docs/conus_plan.md section "Strata (PLURAL area type x cell group)", runbook section 32, CLAUDE.md, open_items.
- Alpine commands: (1) pre-check + submit (one submit), (2) progress, (3) logs + results commit + sacct / seff; a success line at the
  end of each block. Numbers only, no interpretation.
