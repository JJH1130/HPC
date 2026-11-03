git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "NobuiltYear feature test: result". v5.6 + nby가 county CV를 다섯 해 모두 개선
(RMSE 3.5-7.1 %), 모든 TEST 카운티 기준 카운티 R2를 v5.4 수준으로 되돌림 (1980 0.858 vs 0.861). 질문: nby가 불확실성을 피처로 처리한다면
카운티를 빼는 필터(t070, 1,020개 제외) 없이도 되는가? = v5.4 + nby (필터 없음). 한 가지만 바꿈 = v5.4 + 피처 하나.
보고 규칙 (open_items): 카운티 지표는 항상 모든 TEST 카운티 (필터로 빠진 것 포함); kept-only 숫자는 옆에 라벨 붙여서만.

[1. 모델]
- configs/conus_rf_v3_all_nby.yaml (version Dasy_CONUS_RF_v3_all_nby): Dasy_CONUS_RF_v3_all (v5.4)과 같은 split / fold / statuses /
  water mask / strips / 탐색 공간 / n_iter 60, exclude_counties 없음, 각 era = v5.4의 그 해 era + nby (nobuilt 테스트와 같은 NOBUILT
  레이어, 같은 셀 정의). 연도 1910 / 1940 / 1960 / 1980 / 2010. compare_with Dasy_CONUS_RF_v3_all.
- features / train / predict / tract validate (gap 카운티 = v5.6의 것, --gap-version, nobuilt 테스트와 같게).

[2. 비교 (네 버전: v5.4, v5.6, v5.6 + nby, v5.4 + nby; 같은 연도, 같은 tract / 카운티)]
- 카운티 TEST R2 / MdAPE / MAPE: 모든 TEST 카운티 (= split의 test 전부, 네 버전 같은 집합; exp(y_hat) x area_km2 vs census, 배분 전,
  metrics_over_time.py와 같은 정의) -> 주 표. 옆에 kept t070 / excluded t070 TEST 카운티 나눠서 (라벨).
- county CV RMSE / R2: 표에 넣되 열 이름에 CV 카운티 집합 표시 (필터 버전은 excluded가 CV에 없어 필터 유무끼리 직접 비교 불가) — 선택
  근거로 쓰지 않음을 로그 / CSV 주석에.
- tract MdAPE: all, kept / excluded t070, gap / no-gap, 밀도 4묶음, 면적 비례.
- BUI = 0 셀 인구 비율, 그중 NobuiltYear > 0 셀 비율 (nobuilt_cells.csv와 같은 정의). nby permutation / SHAP 순위.
- 도시 gap 1 km 블록 (Boston / Denver / Chicago, 1980 / 2010; external_city_meeting.py 기준 그대로), v5.6 / v5.6 + nby 줄은 기존
  nobuilt_city_gaps.csv와 같아야 함 (다르면 멈춤).
- 출력: results/validation/conus/nobuilt/v54_nby_comparison.csv (+ cells / city gaps / ranks CSV), 로그에 요약표. 기존 nobuilt 결과 파일은
  그대로 둠. 선택 규칙 없음 (사용자가 판단), tract로 튜닝 안 함.

[3. 진단 하나 (모델 없음, 가벼움): 연도 없는 기록이 오래된 건물 쪽인가]
- nby_age가 nby보다 못했음 -> "연도 없는 기록 = 같은 카운티 연도 있는 기록과 같은 시대 분포" 가정이 틀렸을 수 있음.
- 셀 단위: 건물 있는 셀 (BUPR_2015 > 0 또는 NobuiltYear > 0) 중 NobuiltYear > 0 셀과 = 0 셀의 HISDAC FBUY (첫 건축 연도,
  $HISDAC_DIR/FBUY/) 분포 비교 (분위수, 10년 구간 비율). NobuiltYear > 0이고 BUPR_2015 = 0인 셀 (연도 있는 기록 없음)은 따로 개수.
  카운티 단위: ratio_A_nby vs 그 카운티 연도 있는 기록 중 1940년 이전 비율 (BUPR_1940 / BUPR_2015)의 Spearman.
- results/hisdac_uncertainty/undated_age_diag.csv + 로그. 진단만 (피처 / 설정에 반영 안 함).

[공통]
- 로컬 테스트 (exclude 없는 config 로드, era = v5.4 era + nby, 기존 config 결과 그대로; 비교 표 손계산; FBUY 진단 합성 격자 손계산),
  커밋, push.
- submit_conus.sh 모드 v54nby (features / train / predict / validate -> 비교 + 진단, 한 번 제출). 러너북 20절, docs/conus_plan.md 절
  "v5.4 + NobuiltYear (no filter)", CLAUDE.md, open_items 갱신.
- CURC 정기 점검: 2026-11-04 (수) 06:30-18:30 MT. 제출 시점에서 점검 시작 전에 끝나지 않을 wall time의 잡은 점검 후까지 대기함 -> 사전
  확인에서 남은 시간과 체인 예상 시간을 같이 출력하고, 안 맞으면 "점검 후 실행됨"을 알려줄 것 (제출 자체는 그대로 해도 됨).
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
