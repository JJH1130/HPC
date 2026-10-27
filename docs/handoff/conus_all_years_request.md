git pull 받고 아래를 해줘. 배경과 결정: docs/conus_plan.md "Model family result", Order 7; docs/open_items.md 2026-10-27 (Model family: RF).

[목적]
CONUS 기본 모델(RF, v3 피처, 후보 60개)을 1900-2010 전체 센서스 연도(10년 간격, 12개 연도)로 실행. 2020은 다음 단계 (Stefan CSV가 2010까지라 별도 county 입력 필요).

[1. 설정]
- configs/conus_rf_v3_all.yaml, 버전 이름 Dasy_CONUS_RF_v3_all. conus_rf_v3_n60.yaml과 같은 모델/탐색 공간/n_iter 60/split/use_status/train_status/water_mask yearly/block_rows.
- years: 1900, 1910, ..., 2010. 연도마다 era 하나 (연도별로 따로 튜닝 + 학습, 지금과 같은 방식).
  - 1900-1930: [bui, bldg_size, mu_ratio, dist_built, elev, slope] (Land_Use가 1940부터라 res_share / rent_share 없음 - 지금 Y1920과 같음)
  - 1940-2010: [bui, bldg_size, mu_ratio, dist_built, res_share, rent_share, elev, slope]
- compare_with: Dasy_CONUS_RF_v3_n60 (겹치는 1920/1960/2010). 같은 seed, 같은 피처, 같은 fold라 결과가 n60과 같아야 함 - 재현성 점검으로
  로그에 세 연도의 선택된 하이퍼파라미터 / CV RMSE / tract MdAPE가 n60과 같은지 한 줄씩 출력 (다르면 원인 기록).
- configs/conus_study_area.yaml의 years를 12개 연도로 (기존 3개 연도 산출물은 다시 만들지 않고 재사용하면 좋음 - 단순한 쪽으로).

[2. 입력 단계 (없는 연도만)]
- census_conus: 1900-2010 전체 (filled_nhgis가 쓰는 NHGIS counties_{YEAR}.gpkg가 모든 연도에 있는지 사전 확인; 없으면 어떤 연도가 없는지 알려주고
  그 연도는 filled 없이 진행할지 멈출지 판단 근거를 줘).
- grid_cutout (새 9개 연도: 1900, 1910, 1930, 1940, 1950, 1970, 1980, 1990, 2000), Land_Use는 1940+만. bui_fix를 새 연도에 적용 (QA CSV 연도별).
  zones는 2010 폴리곤이라 연도마다 같음.
- water_frac yearly (GDW 완공 연도 기준)를 새 연도에. QA 포인트 그대로.
- DEM은 이미 있음. place_dist 불필요 (v3에 거리 없음).
- 스크래치 용량: 새 연도 9개 x 레이어 수로 예상 용량을 사전 확인에서 출력 (df / du).

[3. 학습 / 예측 / 검증]
- features / train / predict는 연도별로 (잡 배열이든 연도 묶음이든 단순한 쪽으로; 이전 측정치: 3개 연도 기준 features 3분, RF 60개 train 23분, predict 13분, validate 4분).
- tract 검증: 1910-2010 (1900은 tract 없음). 밀도 4묶음, train/test 부분, gap 카운티 (--gap-share 0.05), 면적 비례 기준선.
- compare_models로 1개 버전 x 12개 연도 표: results/validation/conus/Dasy_CONUS_RF_v3_all/summary_by_year.csv
  (CV RMSE, CV R2, TEST R2, 선택된 하이퍼파라미터, tract 수와 카운티 수, MdAPE all / test / no_gap / 밀도별, 기준선 MdAPE, gap 카운티 수).
- 그림 하나: 연도별 tract MdAPE (모델 vs 기준선, no_gap 선 포함) + 연도별 tract 카운티 수 (results/validation/conus/Dasy_CONUS_RF_v3_all/).
- 연도별 CONUS 인구 지도 PNG (map-years 전체, 지금과 같은 스타일).
- 질량 보존 QA (reallocation_qa)가 모든 연도에서 통과하는지 로그 요약.

[공통]
- MA 설정과 기존 결과는 그대로. 로컬 테스트(필요하면 1900-1930 era 피처 / tract 없는 1900 처리), 커밋, push.
- docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신. submit_conus.sh에 all 모드.
- Alpine 명령(사전 확인 + 체인 + 진행 확인 + 로그 커밋 + seff)을 하나의 완전한 블록씩, 블록마다 끝에 무엇이 출력되면 성공인지 한 줄씩.
  계산 노드에서 해야 하는 단계가 있으면 어느 줄부터 어느 줄까지인지 명확히.
