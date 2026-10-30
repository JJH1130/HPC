git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "PLURAL grid test result" (PLURAL 효과 없음, 제외) 와 docs/open_items.md
"Meeting with Stefan, 2026-10-28" (tract MdAPE를 1920-2020 모든 연도로, 1번 카운티 TEST MdAPE, 2번 고정 tract 세트).
v5.6 = Dasy_CONUS_RF_v3_u070 을 최종 버전으로 모든 센서스 연도에 돌린다. 사용자는 제출 후 잠을 자므로 Alpine 블록은
제출 한 번에 끝까지 이어지게(의존성 체인) 만들 것.

[1. v5.6 나머지 연도]
- configs/conus_rf_v3_u070.yaml 에 1900, 1910, 1930, 1950, 1970, 1990, 2000 era 추가 (one era per year, 전부 13개 연도).
  각 era의 피처 목록 = configs/conus_rf_v3_all.yaml 의 같은 연도 era와 동일 (1940 이전은 Land_Use 없음 등 그대로 복사).
  split / fold / exclude_counties (excluded_counties_t070.csv) / 탐색 공간 / n_iter 60 그대로.
- y2020, plural 때처럼 --years 1900 1910 1930 1950 1970 1990 2000 으로 같은 버전에 추가. 기존 6개 연도
  (1920 1940 1960 1980 2010 2020) 결과는 바이트 단위로 바뀌면 안 됨 (cv_summary / reallocation_qa / water_mask_by_year /
  metrics_by_year 의 기존 행 포함).
- 컷아웃 / 카운티 입력은 v5.4 전체 연도 때 이미 1900-2020 다 있음. 없는 게 있으면 사전 확인에서 멈추고 알려줄 것.
- tract 검증: tract가 있는 연도 전부 (1910-2020; 1900은 tract 없으면 skip 기록).

[2. 집계 / 비교 (v5.4 = Dasy_CONUS_RF_v3_all 과 나란히)]
- compare_models.py: v5.6 연도별 summary_by_year.csv + 그림, --repro-with 없이 v5.4와 같은 연도 비교
  (tract MdAPE all / kept_t070 / excluded_t070 / gap / no-gap / 밀도 4묶음, CV / TEST R2).
- metrics_over_time.py: v5.6의 county_metrics_by_year.csv (TEST / CV 카운티 MdAPE, MAPE, R2), fixed_tract_metrics.csv
  (1910 / 1920 / 1940 / 1960 고정 세트), mdape_over_time.png. 그림에 v5.4 선도 같이 (점선).
- 출력: results/validation/conus/Dasy_CONUS_RF_v3_u070/ (v5.4와 같은 파일 이름).

[공통]
- 로컬 테스트 (era 추가 시 기존 era 보존은 test_plural의 --years 검사 재사용 가능), 커밋, push.
- submit_conus.sh 에 모드 v56all (features -> train -> predict -> validate 연도 전부, 그 뒤 compare_models, metrics_over_time).
- docs/conus_plan.md, docs/runbooks/Running_CONUS.md (14절), CLAUDE.md 갱신. 버전 표의 v5.6 행은 결과 보고 Claude가 고침.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 커밋 + sacct / seff + "OLD YEARS 0 / 0" 확인. 블록 끝마다 성공 표시 한 줄.
