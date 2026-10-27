git pull 받고 아래를 해줘. 배경: docs/open_items.md 2026-10-28 (NTL test), docs/dasymetric_v3_2.md (MA에서 ntl을 뺀 근거: 14개 카운티),
docs/conus_plan.md "All census years result".

[목적]
MA에서는 카운티 14개라 NTL 효과를 제대로 못 봤음. CONUS(카운티 약 2,500개)에서 2000 / 2010에 NTL을 더하면 tract 배분이 나아지는지 확인.
변수는 원래 시대(era)별로 다르게 쓰기로 했으므로(1940 이전: Land_Use 없음, 2000 이후: NTL 있음), NTL은 2000 / 2010(나중에 2020)에만 들어감.

[1. NTL 컷아웃]
- configs/conus_study_area.yaml에 NTL 레이어 추가: MA configs/study_area.yaml과 같은 정의
  (Harmonized_DN_NTL_{YEAR}_*.tif, 30 arc-sec, nearest, int16), years [2000, 2010] (2020은 나중에 2020 단계에서).
- 기존 CONUS 컷아웃에 grid_cutout.sh --layers NTL로 추가 (다른 레이어 다시 만들지 않음).
- NTL QA: src/grid/ntl_qa.py를 CONUS 컷아웃에 돌려서 연도별 분포, NTL-BUI Spearman, 바다/국경 근처 이상치를 로그로 (MA의 DN >= 60 고정 규칙 실패는
  규칙 문제로 결론났으니 실패해도 체인은 계속 진행; 결과만 기록).

[2. 모델]
- configs/conus_rf_v3_ntl.yaml, 버전 Dasy_CONUS_RF_v3_ntl. conus_rf_v3_all.yaml과 같은 모델 / 탐색 공간 / n_iter 60 / split / status / water_mask / block_rows.
- years: [2000, 2010], era Y2000 / Y2010 = v3_all의 피처 + ntl
  ([bui, bldg_size, mu_ratio, dist_built, res_share, rent_share, elev, slope, ntl]). feature_groups에 Night lights: [ntl].
- compare_with: Dasy_CONUS_RF_v3_all (같은 split / fold).
- features는 2000 / 2010만 새로 계산 (ntl 추가). train / predict / validate (gap-share 0.05, 밀도 4묶음, train/test 부분).

[3. 비교]
- compare_models: Dasy_CONUS_RF_v3_all vs Dasy_CONUS_RF_v3_ntl, 2000 / 2010 ->
  results/validation/conus/ntl_comparison.csv (CV RMSE, TEST R2, tract MdAPE all / test / no_gap / 밀도별, 선택된 하이퍼파라미터).
- SHAP / permutation importance에서 ntl 순위를 로그에.
- county_maps 2010: 같은 4개 카운티(Chelan WA, Reno KS, Fremont CO, Macoupin IL)로 v3_all vs v3_ntl,
  + 건물 없는 셀(BUI = 0)에 놓인 인구 비율 (지금 county_maps.csv와 같은 지표).

[공통]
- 로컬 테스트(ntl이 있는 era / 없는 era 피처, NTL nodata 처리), 커밋, push.
- docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신. submit_conus.sh에 ntl 모드.
- Alpine 명령(사전 확인 + 체인 + 진행 확인 + 로그 커밋 + seff)을 블록마다 완전하게, 블록 끝에 무엇이 출력되면 성공인지 한 줄씩.
