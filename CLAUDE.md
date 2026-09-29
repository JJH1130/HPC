# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repository is an early-stage project (MIT licensed, Jaeheon Jung) for computational work on CU
Boulder's Alpine HPC cluster. Structure so far: `sbatch/` (Slurm submission scripts + `cluster_env.sh`,
the one place this repo's Alpine paths live), `logs/` (tracked job logs pulled back from the cluster),
`src/` (project code), and `environment.yml` (the `analysis` conda env: numpy, pandas,
matplotlib, JupyterLab; conda-forge only). On Alpine the env lives at
`/projects/jaju1407/software/envs/analysis`; build/update steps are in
`docs/runbooks/Creating_Cluster_Envs.md`, and `sbatch/test_env_analysis.sh` checks it. Locally:
`conda env create -f environment.yml`. A second env, `hisdac` (rasterio/geopandas/LightGBM/SHAP
stack for the HISDAC_US_V2 work), is defined in `envs/hisdac/environment.yml`, lives at
`/projects/jaju1407/software/envs/hisdac`, is built per `docs/runbooks/Creating_Env_hisdac.md`, and
is checked by `sbatch/test_env_hisdac.sh`. First pipeline stage: `src/census/prepare_census.py` (NHGIS
county pop + boundaries → `counties_{YEAR}.gpkg` in ESRI:102039; manual fixes in `configs/nhgis_*.csv`, rules in `docs/census_preprocessing.md`),
run by `sbatch/census_prepare.sh` per `docs/runbooks/Preparing_Census.md`. Raw/processed data live under
`/projects/jaju1407/data` (`$DATA_ROOT` in `sbatch/cluster_env.sh`), not in git. Second stage: `src/grid/make_cutout.py`
(study area in `configs/study_area.yaml` → HISDAC layers clipped to one shared 250 m window + per-year
county zone grids), run by `sbatch/grid_cutout.sh` per `docs/runbooks/Making_Cutout.md`, rules in
`docs/cutout.md`. HISDAC is read from `$HISDAC_DIR` (PetaLibrary, read only); cutouts go to
`$HISDAC_SCRATCH/cutouts/<name>` (scratch, 90-day purge). Env changes go through the yml files + `conda env update
--prune`, never ad-hoc `mamba install`. There are no build/lint/test commands yet beyond
`python <CURC_Alpine skill>/scripts/check_sbatch.py sbatch/*.sh` to lint sbatch scripts.

When more code is added, update this file with:
- Commands to build, lint, and run tests (including running a single test)
- The high-level architecture/module layout, focused on things not obvious from reading one file

## 작업 방식: Claude ↔ Alpine 클러스터

이 저장소의 코드는 CU Boulder Alpine HPC 클러스터에서 `sbatch`로 실행된다. **Claude는 클러스터에 직접
접속할 수 없다** (SSH, `sbatch`, `/scratch`, 로그 열람 전부 불가) — 사용자가 유일한 다리다.

워크플로:
1. Claude가 로컬 저장소에서 코드, sbatch 스크립트, 러너북을 작성한다.
2. 사용자가 로컬에서 커밋/푸시 → 클러스터에서 `git pull` → Claude가 준 명령어를 Alpine 터미널에 그대로
   붙여넣어 실행한다.
3. 잡이 `logs/`에 로그를 쓴다 (작은 결과 파일은 결과 폴더로).
4. 사용자가 클러스터에서 `logs/`(+작은 결과물)를 커밋·푸시하면, Claude가 로컬에서 `git pull`해서 읽고
   분석한다.

Claude는 로그/결과를 직접 pull해서 읽기 전까지는 잡이 실행됐다거나 성공했다거나 어떤 수치가 나왔다고
단정하지 않는다.

클러스터 관련 작업(온보딩, sbatch 스크립트 작성, conda 환경, 하드웨어/파티션 선택, 잡 체이닝, 스토리지
경로, 러너북 작성, 잡 상태 확인·트러블슈팅 등)은 `CURC_Alpine` 스킬을 따른다.

클러스터 온보딩(로그인, GitHub SSH, `/projects` clone 등) 절차는 `docs/runbooks/Cluster_Setup.md`
참고.
