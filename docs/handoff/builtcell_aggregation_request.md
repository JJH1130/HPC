git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "County feature aggregation: diagnosis result" (Stefan item 5). 지금 카운티 피처
bui / bldg_size / mu_ratio / res_share / rent_share = 마스크 안 모든 셀 평균 -> 사실상 건물 비율(Spearman 0.86-0.95)이고, 셀 값과 의미가
다름 (학습 때 1,000, 셀에는 10,000). 이번 변형: 두 성분을 나눔 = 건물 셀만의 평균 + 새 피처 built_local. 사용자와 정한 정의는 아래 그대로.

[1. 피처 정의 (셀 / 카운티가 항상 같은 규칙: 카운티 값 = 셀 값의 평균, 정의상 정확히)]
- built_local (새 피처, 창 크기 k = 3 / 5 / 9):
  - 셀 값 = k x k 창 안에서 "마스크 안" 셀 중 건물 셀(BUI > 0)의 비율. 마스크 = 그해 county_features가 쓰는 것과 같은 것
    (used 카운티 + water_mask: yearly). 창 안의 마스크 밖 셀(바다, 미국 밖, 물 마스크, 카운티 없는 셀)은 분자 / 분모 모두에서 뺌
    (빈 땅으로 세지 않음). 옆 카운티의 마스크 안 셀은 셈 (경계 셀은 옆 카운티 건물 영향을 받는 게 맞음).
  - 카운티 값 = 그 카운티 마스크 안 셀들의 built_local 평균 (단순 건물 셀 수 / 셀 수가 아님).
  - 전체 창 기준으로 계산 (strip이면 위아래 (k-1)/2 행 halo, strip = 전체 창 테스트). 셀 피처 계산은 county_features / predict에서 같은 함수.
- bui, bldg_size, mu_ratio, res_share, rent_share:
  - 셀 값 = 지금 그대로 (common.cell_features).
  - 카운티 값 = **건물 셀(BUI > 0)만의 평균** (지금은 마스크 안 모든 셀 평균). 건물 셀이 0개인 카운티: 값 0 + 로그에 개수 (학습엔 그대로 둠).
- dist_built, elev, slope: 지금 그대로 (모든 셀 평균).
- 빈 셀(BUI = 0)의 처리: 이번엔 바꾸지 않음 (모델에 맡김). 빈 셀에 배분된 인구 비율은 v5.6과 나란히 기록.
- 구현: 카운티 집계 방식을 피처마다 config에서 고를 수 있게 (예: era 옆에 `aggregation: {bui: built_mean, ..., built_local: {window: 5}}`),
  기본값 = 지금 방식 (기존 config / 결과는 바이트 그대로).

[2. 변형 (v5.6 = Dasy_CONUS_RF_v3_u070 기준, 1960 / 2010)]
- Dasy_CONUS_RF_v3_u070_bc3, _bc5, _bc9: v5.6 피처 (같은 이름) + built_local, 위 집계. 같은 split / fold / 제외 카운티 / 탐색 공간 / n_iter 60.
- 창 크기 선택 규칙 (결과 보기 전 고정): 1960 + 2010 평균 카운티 CV RMSE가 가장 낮은 k. 0.005 이내면 작은 k. tract로 고르지 않음.
  tract 결과는 세 개 다 표에 보이되, "선택된 k"는 CV로만.

[3. 평가 (v5.6과 같은 tract / 카운티)]
- tract MdAPE / MAPE (10명 이상): 전체, kept / excluded t070, gap / no-gap, 밀도 4묶음, 면적 비례 기준선.
- 카운티: CV RMSE / R2, TEST MdAPE (배분 전) / R2 (v5.6과 같은 TEST 카운티).
- 범위 밖 셀 재측정 (aggregation_diag 재사용, 새 정의로): 건물 셀의 범위 밖 인구 비율 피처별, v5.6과 나란히.
- 빈 셀(BUI = 0)에 배분된 인구 비율 (전체, v5.6과 나란히).
- 피처 순위 (permutation / SHAP), built_local 포함.
- 지도: 2010, 4개 카운티 (Chelan WA, Reno KS, Fremont CO, Macoupin IL), v5.6 vs 선택된 k.
- 출력: results/validation/conus/builtcell/builtcell_comparison.csv + 그림 (연도 x 변형 tract MdAPE, v5.6 기준선) + 선택 결과 한 줄 (RULE RESULT).

[공통]
- 로컬 테스트: 작은 합성 격자에서 built_local = 손계산 (중앙 / 경계 / 모서리 / 마스크 셀 섞인 창), 카운티 값 = 셀 값 평균 (정확히),
  건물 셀 평균 손계산, strip = 전체 창, 기본 집계 = 기존 결과 그대로, predict에서 질량 보존.
- submit_conus.sh 모드 builtcell (features -> train -> predict -> validate 세 변형 병렬 -> 비교), 러너북 16절, docs/conus_plan.md 절
  "Built-cell aggregation test", CLAUDE.md, open_items 갱신. 커밋, push.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
