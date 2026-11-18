git pull 받고 아래를 해줘. 배경: docs/open_items.md "Meeting with Stefan, 2026-11-17" 1번. Stefan 제안 = NobuiltYear를 모든 연도
같은 개수로 넣지 말고, 그 카운티의 연도 있는 기록 수(BUPR)가 늘어난 비율대로 연도마다 줄여서 넣기. 이건 이미 만든 피처 nby_age와 같은
정의 (NobuiltYear x f_c(year), f_c = 2010 카운티 BUPR_year 합 / BUPR_2015 합, 0-1로 자름, BUPR_2015 = 0이면 1; common.nby_age_setup,
<era>/features/nby_age_factor.csv, predict에서 재확인). 예전에는 v5.6 (필터 있음) 위에서 nby와 나란히 했고 nby보다 나빴음
(docs/conus_plan.md "NobuiltYear feature test: result"). 이번 = v5.7 (필터 없음)에서 nby를 nby_age로 바꾸기. 한 가지만 바꿈.
보고 규칙 (open_items): 카운티 지표는 항상 모든 TEST 카운티; kept / excluded t070은 옆에 라벨.

[1. 모델]
- configs/conus_rf_v3_all_nbya.yaml (version Dasy_CONUS_RF_v3_all_nbya): Dasy_CONUS_RF_v3_all_nby (v5.7)와 같은 split / fold /
  statuses / water mask / strips / 탐색 공간 / n_iter 60, exclude_counties 없음; 각 era = v5.7의 그 해 era에서 nby -> nby_age만 바꿈
  (nby_age 블록 = conus_rf_v3_u070_nbya.yaml과 같음, bupr_ref 2015). compare_with Dasy_CONUS_RF_v3_all_nby.
- 연도: 예전 nby_age 테스트와 같은 1910 / 1940 / 1960 / 1980 / 2010.
- 사전 확인: 같은 연도의 nby_age_factor.csv가 예전 Dasy_CONUS_RF_v3_u070_nbya의 것과 같아야 함 (카운티 집합이 다르면 공통 카운티의
  factor가 같은지; 다르면 멈춤).
- features / train / predict / tract validate (gap 카운티 = v5.6의 것, --gap-version, 예전과 같게).

[2. 비교 (v5.4, v5.6, v5.7, v5.7 + nby_age 대신 = 새 버전; 같은 연도, 같은 tract / 카운티)]
- v54_nby_compare.py 재사용 또는 같은 정의 (새 버전을 한 열로 추가): 카운티 TEST R2 / MdAPE / MAPE (모든 TEST 카운티 주 열, kept /
  excluded t070 라벨), county CV RMSE (CV 집합 표시; v5.7과 새 버전은 같은 CV 집합이라 직접 비교 가능), tract MdAPE (all, kept /
  excluded t070, gap / no-gap, 밀도 4묶음), BUI = 0 셀 인구 비율 / 그중 NobuiltYear > 0 셀 비율, nby / nby_age permutation + SHAP 순위,
  도시 gap 1 km 블록 (1980 / 2010).
- 참고 열: 예전 v5.6 + nby_age (Dasy_CONUS_RF_v3_u070_nbya) 숫자도 나란히 (기존 nobuilt_comparison.csv에서; 재계산하면 같아야 함).
- 연도별 f_c 분포 요약 (카운티 중앙값 / 10 / 90 분위, 1로 자른 수, BUPR_2015 = 0 수) -> 로그 + CSV (이른 연도 f_c가 1-6 % 수준이라
  nby_age가 사실상 0이 되는지 보려고).
- v5.7 숫자는 v54_nby_comparison.csv / v5.7 summary와 같아야 함 (다르면 멈춤).
- 출력: results/validation/conus/nobuilt/v57_nbya_comparison.csv (+ cells / city gaps / ranks / factor 요약 CSV), 로그에 요약표. 선택
  규칙: county CV RMSE (v5.7과 같은 CV 집합)로만 판단, 결정은 사용자. tract로 튜닝 안 함.

[공통]
- 로컬 테스트 (config = v5.7 era에서 nby -> nby_age만, 다른 피처 / 설정 동일; factor 재사용 대조; 비교 표 손계산; v5.7 숫자 대조),
  커밋, push.
- submit_conus.sh 모드 v57nbya (사전 확인 -> features / train / predict / validate -> 비교, 한 번 제출). 러너북 22절,
  docs/conus_plan.md 절 "v5.7 with nby_age instead of nby", CLAUDE.md, open_items 갱신.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
