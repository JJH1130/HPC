git pull 받고 아래를 해줘. 사용자가 미팅 전에 결과를 보려고 함 (가능하면 오늘 안에 Alpine 결과). 배경: docs/conus_plan.md
"External comparison with v5.6: result" (도시 gap 1 km 셀: v5.6 << GHS-POP인 곳은 BUI = 0이지만 NobuiltYear > 0인 셀이 4-9배 많음,
Denver 1980 77 % vs 10 %). 아이디어: NobuiltYear(연도 없는 기록 수)를 셀 피처로 주면 "BUI는 0이지만 연도 없는 건물이 있는 셀"을
모델이 구분할 수 있음. 한 가지만 바꿈 = v5.6 + 피처 하나.

[1. 레이어]
- NobuiltYear = $HISDAC_DIR/FBUY/NobuiltYear.tif (static, ~2016, 셀당 연도 없는 기록 수). grid_check.csv로 우리 격자와 같음 확인됨.
  CONUS cutout에 static 레이어 NOBUILT로 추가 (make_cutout --layers, DEM처럼 연도 없음). docs/data_sources.md HISDAC 행에 사용처 추가.

[2. 피처 두 변형 (각각 v5.6 피처 + 하나; 셀 값 정의 -> 카운티 값 = 마스크 안 셀 평균, 지금 방식 그대로)]
- nby: 셀 NobuiltYear 그대로 (모든 연도 같은 값).
- nby_age: 셀 NobuiltYear x f_c(year), f_c(year) = 그 셀이 속한 2010 카운티의 BUPR_year 합 / BUPR_2015 합 (0-1로 자름;
  BUPR_2015 합 = 0이면 f = 1). 가정 = 연도 없는 기록도 그 카운티의 연도 있는 기록과 같은 시대 분포 (1번 필터 비율과 같은 가정).
  BUPR_year = 그해 cutout BUPR 레이어; BUPR_2015 = HISDAC 원본 (uncertainty_filter와 같은 방식으로 2010 zone 합). f_c는
  <era>/features/nby_age_factor.csv로 남기고 predict에서 같은 값 사용 (다르면 멈춤).
- configs/conus_rf_v3_u070_nby.yaml, conus_rf_v3_u070_nbya.yaml: v5.6과 같은 split / fold / exclude_counties (t070) / 탐색 공간 /
  n_iter 60, 연도 1960 / 1980 / 2010.

[3. 평가 (v5.6과 같은 tract / 카운티; plural_compare / builtcell_compare 재사용)]
- 카운티: TEST R2 / MdAPE (필터 후 남은 TEST 카운티, 세 버전 같은 집합), CV RMSE.
- tract MdAPE: all, kept / excluded t070, gap / no-gap, 밀도 4묶음, 면적 비례.
- BUI = 0 셀에 배분된 인구 비율 (전체), 그중 NobuiltYear > 0 셀에 간 비율.
- 피처 순위 (permutation / SHAP)에서 nby / nby_age 순위.
- 도시 gap 1 km 셀 재측정: external_city_meeting.py의 gap 기준 그대로 (v5.6 / GHS-POP < 0.25, GHS >= 1,000 / km2), Boston / Denver /
  Chicago 1980 / 2010 (1960은 GHS 없음)에서 각 변형의 gap 셀 수와 그 셀들의 인구 (GHS 대비) -> v5.6과 나란히. 그림은 필요 없음.
- 출력: results/validation/conus/nobuilt/nobuilt_comparison.csv (+ 위 항목 CSV), 로그에 요약표.
- 선택 규칙 없음 (두 변형 다 보고, 판단은 사용자). tract로 튜닝하지 않음.

[공통]
- 로컬 테스트 (nby_age 손계산: f_c, 자르기, BUPR_2015 = 0; 카운티 값 = 셀 평균; predict에서 factor 불일치 시 멈춤; 기존 config 결과 그대로),
  커밋, push.
- submit_conus.sh 모드 nobuilt (cutout 레이어 -> 두 변형 features / train / predict / validate 병렬 -> 비교 + 도시 gap 재측정, 한 번 제출).
  러너북 19절, docs/conus_plan.md 절 "NobuiltYear feature test", CLAUDE.md, open_items 갱신.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
