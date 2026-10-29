git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "HISDAC record uncertainty: diagnosis", docs/open_items.md 2026-10-30,
meeting 2026-10-28 item 4 (Stefan): 기록이 불확실한 카운티를 학습/평가에서 빼고, 깨끗한 카운티로 배운 모델로 그 카운티 인구를 배분
(imputation). 임계값은 민감도 분석으로 고르되 tract로 고르지 않음 (아래 선택 규칙).

[1. 카운티 필터 - 연도와 무관한 고정 집합 하나 (2010 카운티 폴리곤)]
- 비율 A: ratio_A_nby = NobuiltYear / (BUPR_2015 + NobuiltYear)  (results/hisdac_uncertainty/county_record_uncertainty.csv)
  -> 임계값 t 이상이면 제외. 테스트할 t: 0.9, 0.7, 0.5.
- 고정 규칙 2개 (튜닝하지 않음, 모든 t에 공통으로 적용):
  - 기록 누락: (BUPR_2015 + NobuiltYear) / pop_2010 < 전국 중앙값의 5 %  (예: DuPage IL, Otero; 지금 기준 3곳)
  - 면적 누락: BUI_2015 합 / BUPR_2015 합 < 전국 중앙값의 5 %  (예: Tehama CA, Codington SD; 약 37곳)
    (내가 2010 county_features로 대충 본 값: 1인당 기록 중앙값 1.37, 기록당 BUI 중앙값 ~1,600 sq ft. 정식으로는 2015
    HISDAC 레이어에서 카운티 합으로 계산해서 기록)
- 제외 집합은 모든 연도에 같게. 카운티 목록과 이유(ratio / records / area)를 CSV로:
  results/hisdac_uncertainty/excluded_counties_t{090,070,050}.csv, 요약(카운티 수, 인구 비율, train/test 수, 주별, gap 카운티 겹침).
- 참고(로그만): NobuiltYear 값이 짝수가 홀수보다 훨씬 많음 -> 중복 집계 가능성. 고치지 말고 그대로 사용, 로그에 한 줄.

[2. 모델 - v5.4와 같은 설정, 학습/평가에서만 카운티를 뺌]
- 버전 3개: Dasy_CONUS_RF_v3_u090, _u070, _u050. conus_rf_v3_all.yaml과 같은 피처 / 모델 / 탐색 공간 / n_iter 60 / split 표.
  제외 카운티는 CV 학습, 하이퍼파라미터 탐색, TEST 평가에서 모두 빠짐 (split 표와 fold는 그대로 두고 그 카운티 행만 제외).
  하이퍼파라미터는 남은 카운티로 연도마다 다시 탐색.
- 연도: 1920, 1960, 2010, 2020 (임계값을 고른 뒤 고른 것만 전체 연도로 돌릴 예정).
- 예측/배분: 제외 카운티 포함 모든 카운티에 (제외 카운티 = imputation). 질량 보존 그대로.
- "필터 없음" 기준은 기존 Dasy_CONUS_RF_v3_all(v5.4) 결과를 그대로 씀 (다시 돌리지 않음).

[3. 평가 - 네 모델(v5.4, u090, u070, u050)을 같은 카운티 집합에서 비교]
- (a) 공통 TEST 집합: 가장 엄격한 기준(u050 + 고정 규칙)에서도 남는 TEST 카운티. 배분 전 카운티 예측(exp(yhat) x 면적,
  metrics_over_time.py와 같은 정의) vs 센서스: MdAPE, MAPE, R2(log 밀도), 카운티 수.
- (b) imputation 공통 집합: u090 기준 제외 카운티 중 TEST split 카운티 (어느 모델도 학습에 안 쓴 카운티). 같은 지표.
  참고로 각 모델의 자기 제외 카운티 전체에 대한 같은 지표도 (모델마다 집합이 다르므로 비교용 아님, 표에 표시).
- (c) tract MdAPE / MAPE: 전체, 남은 카운티의 tract, 제외 카운티의 tract, gap / no-gap. 선택에는 쓰지 않음.
- 출력: results/validation/conus/uncertainty_filter/filter_comparison.csv (모델 x 연도 x 평가집합), 그림 하나
  (임계값 vs (a), (b) MdAPE, 연도별), 요약 로그.
- 선택 규칙(결과 보기 전에 고정, 로그와 conus_plan에 적어 둘 것): 네 연도 평균으로 (a)와 (b)의 카운티 MdAPE 평균이 가장 낮은 것.
  1 %p 안의 차이면 카운티를 더 많이 남기는 쪽(큰 t, 필터 없음 포함). 규칙에 따른 결론을 로그에 한 줄로 출력하되, 최종 결정은 내가 함.

[공통]
- 로컬 테스트(필터 집합 계산, 제외 카운티가 학습/TEST에서 빠지고 예측에는 포함, 공통 집합 정의, 질량 보존), 커밋, push.
- docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신. submit_conus.sh에 uncfilter 모드 (세 버전 병렬).
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 커밋 + seff. 블록 끝마다 성공 표시 한 줄.
