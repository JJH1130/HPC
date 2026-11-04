git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "v5.4 + NobuiltYear (no filter): result" + 버전 표. 사용자 결정 (2026-11-04):
v5.7 = Dasy_CONUS_RF_v3_all_nby (v5.4, 필터 없음, + nby)를 다음 기준 버전으로 채택 (모든 TEST 카운티에서 매년 1등). 지금은 5개 연도
(1910 / 1940 / 1960 / 1980 / 2010)만 있음 -> 나머지 8개 연도 추가해서 13개 연도 1900-2020 전부. v5.6 all years (v56all 모드)와 같은 방식.
보고 규칙 (open_items): 카운티 지표는 항상 모든 TEST 카운티; kept / excluded t070은 옆에 라벨.

[1. 모델: 같은 버전에 연도 추가]
- configs/conus_rf_v3_all_nby.yaml: era를 v5.4의 13개 era 전부 (Y1900-Y2020) + nby로 (각 era = v5.4 그 해 era + nby, 1900-1930은
  Land_Use 없는 v5.4 era 그대로). years 1900-2020. 기존 5개 era 정의는 바이트 그대로 (바뀌면 안 됨).
- 실행은 --years 1900 1920 1930 1950 1970 1990 2000 2020 (8개)만: features / train / predict. 이미 있는 5개 연도의 출력과
  cv_summary / water_mask_by_year / reallocation_qa 행은 그대로 남아야 함 (기존 --years 동작; 사전 확인에서 5개 연도 metrics.json 해시
  기록 -> 끝난 뒤 같은지 확인, 다르면 로그에 DIFFERS).
- 2020: county 입력 = v5.4 Y2020과 같은 NHGIS 2020 on 2010 polygons.

[2. 검증 + 요약 (v56all 체인과 같은 구성)]
- tract validate: tract 있는 모든 연도 1910-2020 (이미 한 5개 연도도 다시 해도 되고 건너뛰어도 됨; 결과가 같아야 함), gap 카운티 =
  v5.6의 것 (--gap-version, nobuilt / v54nby와 같게).
- compare_models.py: v5.7 13개 연도 summary_by_year.csv + 그림, v5.4 / v5.6과 나란히 (--exclusions excluded_counties_t070.csv로 tract
  kept / excluded 부분도). 카운티 TEST 열은 모든 TEST 카운티 기준이 주 열 (v5.6은 test + excluded TEST; v54_nby_compare와 같은 정의).
- metrics_over_time.py --compare-with Dasy_CONUS_RF_v3_all (+ v5.6도 같이 가능하면): 카운티 MdAPE / MAPE / R2 (모든 TEST 카운티) +
  고정 tract 집합 (1910+ / 1940+ / 1960+) -> results/validation/conus/Dasy_CONUS_RF_v3_all_nby/.
- 5개 연도 숫자는 v54_nby_comparison.csv와 같아야 함 (v5.7 all-TEST R2 1980 0.908, tract all 1980 26.9 %): 다르면 멈춤.

[3. 미팅 도시 그림 v5.7판 (선택이 아니라 같이)]
- external_city_meeting.py를 v5.7로 (설정에서 버전만 바꾸는 옵션, 예: --version / config 키), 같은 3개 도시 x 1980 / 2010, 같은 고정 축 /
  gap 기준 -> results/validation/conus/external/city_maps_meeting_v57/ (기존 city_maps_meeting/ = v5.6판은 그대로). rho / 총인구 /
  gap 표를 v5.6판과 나란히 CSV 하나로 (meeting_summary_v56_v57.csv). v5.6판 숫자는 기존과 같아야 함 (다르면 멈춤).
- external_compare evaluate도 v5.7 열 추가 (reference = v5.7, compare_versions에 v5.6 / v5.4; extract는 다시 안 함) ->
  external_comparison_v57.csv + 그림 (기존 v56 파일 그대로).

[공통]
- 로컬 테스트 (13 era config = v5.4 era + nby, 기존 5 era 그대로; --years가 기존 연도 행 보존; 모든 TEST 카운티 요약 손계산; 도시 그림
  버전 옵션), 커밋, push.
- submit_conus.sh 모드 v57all (사전 확인 -> 8개 연도 features / train / predict -> 모든 tract 연도 validate -> compare_models +
  metrics_over_time; 도시 그림 + external evaluate는 predict 뒤 나란히; 한 번 제출). 러너북 21절, docs/conus_plan.md 절 "v5.7 all years",
  CLAUDE.md, open_items 갱신.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
