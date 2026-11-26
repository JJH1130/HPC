# Where we stopped (2026-11-26)

Running on Alpine (submitted 2026-11-26, 18 jobs, `bash sbatch/submit_conus.sh strata`, runbook section 32): four new 2010
versions (`Dasy_CONUS_RF_v3_all_nby_{ntl,ntlv,pq5ntl,pq5ntlv}` = v5.7 + NTL / NTLV / + PLURAL pq5) features -> train ->
predict -> validate, then `compare_models` and the strata job (PLURAL area type x cell group, v5.7's people per county
stratum, order inside a stratum by another model; scores chosen on TRAIN-county tracts, reported on TEST-county tracts).
Design: `docs/handoff/strata_request.md`, `docs/conus_plan.md` "Strata (PLURAL area type x cell group)".
When the user pushes: read `results/validation/conus/strata/` + the new versions' results + logs, record in
`docs/conus_plan.md`, and give the user a reminder of what was run plus the interpretation (Korean).

Done since the 2026-11-25 meeting (all in `docs/conus_plan.md`): 1980 missed cells; cap allocation 1980 (GHS-POP 1980 =
back-cast, worse); cap transfer (2010 GHS caps ~ v5.7, caps add nothing); unit ratios A + B (v5.7 follows household-size
decline; odd allocated ratios flag error-prone counties); scratch backup to `/projects/jaju1407/data/scratch_backup/hisdac/`.
Next after strata: report to Stefan (cap results + strata).
