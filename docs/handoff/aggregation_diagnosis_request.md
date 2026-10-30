git pull 받고 아래를 해줘. 배경: docs/open_items.md "Meeting with Stefan, 2026-10-28" 5번 (카운티 피처 집계: 지금은 마스크 안 모든 셀의
평균이라 빈 셀(0)이 섞임 -> bui / bldg_size / mu_ratio가 사실상 "건물 있는 셀 비율"을 잼, Spearman 0.97-0.99; 대안: 중앙값,
건물 셀 집중도 지수, 인구가 몰린 부분만). 모델은 카운티 평균으로 학습하고 셀에 적용하므로(change of support) 셀 값이 카운티
학습 범위 밖에 있을 가능성이 큼. 이번엔 **진단만** (학습 / 예측 없음). 결과를 보고 대안 변형을 정함 (Claude + 사용자).

[대상] v5.6 = Dasy_CONUS_RF_v3_u070, 1960과 2010. 피처: bui, bldg_size, mu_ratio, dist_built, res_share, rent_share, elev, slope
(common.cell_features 그대로, 같은 마스크 / 같은 used 카운티 / 같은 strip 처리). 학습 카운티 = 그 era의 train (제외 카운티 빼고) +
TEST는 따로 표시. 예측 래스터는 scratch의 v5.6 predictions 사용 (없으면 사전 확인에서 멈춤).

[1. 범위 밖 셀 (extrapolation)] 피처별로
- 카운티 학습 범위 = 학습 카운티 피처 값의 min / max (+ p01 / p99도).
- 셀 중 그 범위 밖(아래 / 위 따로)인 비율, 그 셀들에 v5.6이 배분한 인구 비율.
- 모든 피처가 범위 안인 셀 비율 / 인구 비율 (전체), 건물 셀(BUI > 0)과 빈 셀(BUI = 0) 따로.
- 셀 분포 vs 카운티 분포 분위수표 (p01 p10 p50 p90 p99 max), 빈 셀은 따로 0 비율.

[2. 다른 집계를 카운티별로 계산 (셀 = 같은 정의)]
- 지금 평균 (확인용: county_features.csv와 같아야 함, 다르면 멈춤).
- 건물 셀만의 평균 (BUI > 0 셀; bui, bldg_size, mu_ratio, res_share, rent_share, elev, slope), 건물 셀 비율 (built_share).
- 건물 셀만의 중앙값 (같은 피처), 전체 셀 중앙값 (0이 몇 개 카운티에서 나오는지 확인용).
- 집중도: 카운티 BUI 합에서 상위 10 % 셀(건물 셀 기준)이 차지하는 비율, 건물 셀 BUI의 Gini.
- 출력: results/aggregation/conus/county_aggregates_{1960,2010}.csv (GISJOIN, train/test/excluded, pop, area, y = log 밀도, 위 값 전부).

[3. 요약 (로그 + CSV)]
- 학습 카운티에서 각 집계값과 y의 Spearman, 그리고 집계값끼리 Spearman (지금 평균 vs 건물 셀 평균 vs 중앙값 vs built_share).
  -> results/aggregation/conus/aggregate_correlations.csv
- 카운티별 tract 오차와의 관계: v5.6 tract_errors_{YEAR}.csv에서 카운티별 tract MdAPE (tract 5개 이상 카운티)를 붙여서,
  집중도 / built_share / 범위 밖 인구 비율(카운티별)과의 Spearman, 그리고 집중도 4분위별 tract MdAPE 표.
  -> results/aggregation/conus/tract_error_by_county_{YEAR}.csv + aggregate_vs_tract_error.csv
- 그림 하나: 피처별 셀 분포(건물 셀) vs 학습 카운티 평균 분포 (log x축, 2010), results/aggregation/conus/cell_vs_county_2010.png.

[공통]
- 새 스크립트 src/validation/aggregation_diag.py + sbatch/aggregation_diag.sh (CONFIG=configs/conus_rf_v3_u070.yaml, --years 1960 2010),
  strip 처리 (strip = 전체 창, 테스트로 확인), 메모리 / 시간은 county_features 잡과 비슷하게.
- 로컬 테스트 tests/test_aggregation_diag.py (작은 합성 격자: 평균 = county_features 방식, 건물 셀 평균 / 중앙값 / 상위 10 % / Gini 손계산,
  범위 밖 비율 손계산, strip = 전체).
- submit_conus.sh 모드 aggdiag (잡 하나), docs/conus_plan.md 절 "County feature aggregation: diagnosis", 러너북 15절, CLAUDE.md 갱신. 커밋, push.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
