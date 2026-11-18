git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "PLURAL on v5.7: result" + "City boxes by density class: result". PLURAL을 넣으면
county CV는 좋아지는데 (-3 to -5 %) tract는 1980 / 2010에 2-6 pp 나빠짐 (시골 tract 가장 크게). SHAP: PLURAL이 셀 구분 피처
(nby / BUI / dist_built)의 비중을 가져감. 가설: PLURAL은 카운티 사이 구분 (카운티 예측)에는 좋지만, 셀 단위 값이 카운티 안 배분을
흐림. 검증 = PLURAL을 카운티 수준에서만 쓰기: 학습된 모델은 그대로, 예측할 때만 셀의 plural 값을 그 카운티의 plural (county_features의
값 = 학습에 쓴 값)으로 바꿈 -> 카운티 안에서는 모든 셀이 같은 plural. 재학습 없음.

[1. 예측 옵션]
- predict.py: model-config plural 블록에 cell_value: cell (기본, 지금과 같음) | county_mean. county_mean이면 셀 피처 plural = 그 셀의 2010
  카운티의 county_features.csv plural 값 (같은 era). 나머지 피처 / 질량 보존 / NoData 규칙 그대로. 기본값이면 출력 바이트 그대로 (테스트).
- 새 버전 2개 (재학습 없이 기존 모델 재사용): Dasy_CONUS_RF_v3_all_nby_pq5cm (= pq5의 모델 + cell_value county_mean),
  Dasy_CONUS_RF_v3_all_nby_plccm (= plc의 모델 + county_mean). config는 pq5 / plc config + cell_value: county_mean + model_from: <원래
  버전> (train 단계 없이 그 버전의 모델 파일 / county_features / breaks / cv_summary를 읽음; 모델 파일 해시를 로그에 기록, 원래 버전과
  같아야 함). 연도 1940 / 1980 / 2010.
- predict + tract validate (gap 카운티 = v5.6의 것, 이전과 같게).

[2. 진단 (같은 체인, 모델 없음)]
- 분산 분해: 연구 셀 전체에서 plural (bilinear 연속값과 pq5 class) / bui / nby / bldg_size의 분산을 카운티 사이 / 카운티 안으로
  나눈 비율 (카운티 안 비율 = sum over counties of within-county SS / total SS), 1940 / 1980 / 2010.
- 카운티 안 구분력: 카운티마다 건물 셀 (BUI > 0) 평균 가중치 / 빈 셀 (BUI = 0) 평균 가중치 (가중치 = 예측 인구 / 셀 면적, 질량 보존 후)
  의 카운티 중앙값 + 10 / 90 분위, 그리고 빈 셀 가운데 NobuiltYear > 0 / = 0을 나눠서도. 버전: v5.7, pq5, pq5cm, plc, plccm.
- BUI = 0 셀 인구 비율 (전체 / 그중 NobuiltYear > 0) 같은 다섯 버전.

[3. 비교]
- 다섯 버전 (v5.7, pq5, pq5cm, plc, plccm), 1940 / 1980 / 2010: tract MdAPE (all, kept / excluded t070, gap / no-gap, 밀도 4묶음),
  BUI = 0 셀 비율, 위 진단 표. 카운티 TEST / CV 숫자는 cm 버전이 원래 버전과 같아야 함 (같은 모델; 다르면 멈춤) -> 표에는 그대로 둠.
- v5.7 / pq5 / plc 숫자는 plural_v57_comparison.csv와 같아야 함 (다르면 멈춤).
- 해석 기준 (결과 보기 전에 고정, 로그에 출력): cm 버전의 tract MdAPE가 v5.7 수준 (차이 <= 0.5 pp)으로 돌아오면 = 셀 단위 PLURAL이 원인;
  원래 PLURAL 버전 수준에 머물면 = 카운티 예측 변화 자체가 원인. 선택이 아니라 원인 확인 (결정은 사용자).
- 출력: results/validation/conus/plural_grid_v57/countymean/ (comparison, variance_split, built_contrast, cells CSV), 로그 요약표.

[공통]
- 로컬 테스트 (cell_value 기본 = 바이트 그대로; county_mean이면 셀 plural = 카운티 값, 카운티 안 상수; model_from이 모델을 바꾸지 않음
  (해시); 분산 분해 / 구분력 손계산; 대조 멈춤), 커밋, push.
- submit_conus.sh 모드 pluralcm (사전 확인 -> 두 버전 predict / validate + 진단 병렬 -> 비교, 한 번 제출). 러너북 25절, docs/conus_plan.md
  절 "PLURAL at county level only", CLAUDE.md, open_items 갱신.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
