git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "1980 missed cells: result" + open_items "Meeting with Stefan, 2026-11-25".
v5.7은 카운티 안에서 건물 셀 / 날짜 없는 기록 셀 / 기록 없는 셀 사이 배분이 GHS와 다름 (근교 undated 셀에 너무 적게, 아주
시골 no_record 셀에 너무 많이). 시험: 카운티마다 세 그룹의 몫 (cap)을 먼저 정하고, 그 몫 안에서만 셀 점수로 나눔. 1980 한 해,
CONUS, 새 학습 없음 (작은 cap 모델 하나만), 1980 tract로 검증.

[0. 정의 (missed_cells.py와 같게)]
- 셀 = v5.7 pop_1980.tif 마스크; 그룹 built (BUI_1980 > 0) / undated (BUI = 0, NOBUILT > 0) / no_record (BUI = 0, NOBUILT = 0).
- 카운티 c, 그룹 g의 몫 s_cg (세 그룹 합 1), 카운티 인구 P_c = census 1980 (v5.7 카운티 합과 같음). 셀 i의 인구
  = P_c * s_cg * score_i / sum_{j in c,g} score_j. 그룹에 셀이 없으면 그 몫 0, 나머지 그룹으로 다시 정규화 (로그에 카운티 수).
  점수 합이 0인 그룹 (예: 점수가 다 0) -> 그 그룹 안 고르게 (로그에 카운티 수). 결과 카운티 합 = P_c (확인, 다르면 멈춤).

[1. 몫 (cap) 3가지]
- (a) v57: v5.7이 실제로 준 그룹 몫 (county_missed_1980.csv의 v57 share와 같아야 함, 확인).
- (b) ghs: GHS-POP 1980 그룹 몫 (county_missed_1980.csv의 ghs undated / no_record share, built = 1 - 둘). 참고용 상한 (1980 이전엔 못 씀).
- (c) model: 카운티 특성으로 GHS 몫을 예측하는 작은 모델, 다른 카운티로만 학습 (out-of-fold).
  - 목표: 두 로그비 y1 = log(s_undated / s_built), y2 = log(s_no_record / s_built) (GHS 몫; 0은 같은 작은 eps로, eps 값은 결과 보기 전 고정
    = 1e-4, 로그에 출력). 예측 후 softmax로 세 몫 복원 (합 1). 그룹 셀이 없는 카운티는 그 그룹 0.
  - 피처 (카운티 값, 1980): v5.7 county_features (bui, bldg_size, mu_ratio, dist_built, res_share, rent_share, elev, slope, nby) + plural
    (Dasy_CONUS_RF_v3_all_nby_plc Y1980 county_features의 plural = 연속값 카운티 평균) + 카운티 셀 비율 (built / undated / no_record 셀 수 비율)
    + DEGURBA level 1 카운티 구분 (one-hot; missed_cells의 것).
  - 모델: RandomForestRegressor 두 개 (y1, y2), 하이퍼파라미터 결과 보기 전 고정: n_estimators 500, min_samples_leaf 5, max_features 0.5,
    random_state 42. 튜닝 없음.
  - out-of-fold: configs/conus_split.csv의 fold (train 카운티 5 fold) -> 각 train 카운티는 자기 fold 밖으로 학습한 모델로 예측; test 카운티는
    train 카운티 전체로 학습한 모델로 예측. 어떤 카운티도 자기 GHS 값을 보지 않음 (테스트).
  - cap 모델 성능 (county CV, tract 아님): y1 / y2의 OOF RMSE, 몫의 MAE (그룹별), 피처 중요도 (permutation, OOF) -> cap_model_1980.csv.
  - (c-noplural): 같은 모델에서 plural만 뺀 것도 (PLURAL이 몫 예측에 보태는지; 같은 고정 설정).

[2. 몫 안 배분 점수 5가지]
- v57: v5.7 셀 인구 (= v5.7 가중치; 그룹 안 비율만 씀).
- pq5: Dasy_CONUS_RF_v3_all_nby_pq5 pop_1980 셀 인구.
- mixed: built 그룹 v57, undated 그룹 v57, no_record 그룹 pq5.
- even: 그룹 안 고르게 (셀 면적 같음).
- plural_inv: 1 - PLURAL (컷아웃 PLURAL 1980, bilinear); built 그룹은 v57 (PLURAL은 빈 셀 그룹에만).
- 조합: 몫 {v57, ghs, model, model_noplural} x 점수 {v57, pq5, mixed, even, plural_inv} = 20개.
- 확인: (a) v57 몫 + v57 점수 = v5.7 그대로 -> 셀 값이 v5.7 pop_1980과 같고 (상대 1e-9), 그 tract 결과가
  results/validation/conus/Dasy_CONUS_RF_v3_all_nby/tract_errors_1980.csv와 같아야 함 (다르면 멈춤).

[3. 검증 (1980 tract, tract_validate.py와 같은 방법 / 같은 tract / 같은 부분)]
- 조합마다 tract MdAPE / MAPE / R2: all, 밀도 4묶음 (dens_*), kept / excluded t070, gap / no-gap (v5.6 gap 카운티, 이전과 같게), 그리고
  카운티 DEGURBA 구분 (city / town_suburb / rural)별. d_mdape = 조합 - v5.7.
- tract 결과는 보고용 (원칙: 선택은 카운티 CV로만). 선택 규칙 없음, 사용자가 결정.
- 1980 tract는 대부분 대도시권만 덮음 -> 로그와 표에 tract가 있는 카운티 수 / 구분별로 명시.

[4. 진단 (같은 잡)]
- 그룹별 capture (missed_cells의 capture와 같은 방식, 카운티 안 줄세우기, k = 5 / 10 / 20 %): 그룹 undated, no_record 각각에서 점수
  v57, pq5, plural_inv, nobuilt (undated만), even(= k)가 GHS-POP 인구를 얼마나 담는지. GHS 자체 = 상한.
- 조합별 빈 셀 몫 (전체, 카운티 구분별) vs GHS.

[출력]
- results/validation/conus/cap_allocation_1980/: cap_model_1980.csv, caps_1980.csv (카운티 x 몫 방법 x 그룹), tract_metrics_1980.csv
  (조합 x 부분), group_capture_1980.csv, tract_errors_1980_<cap>_<score>.csv (조합마다, tract_validate 형식) 또는 하나의 긴 표.
- 그림 하나: 조합별 tract MdAPE (all + 카운티 구분별), v5.7 선 표시.
- 래스터는 scratch에만 (필요하면), git에는 CSV / PNG만.

[공통]
- 새 스크립트 src/validation/cap_allocation.py (run; --check = 입력만), sbatch/cap_allocation.sh, submit_conus.sh 모드 cap1980 (사전 확인 +
  잡 하나). missed_cells.py의 strip / 그룹 / 마스크 코드와 tract_validate.py의 tract 합 코드를 재사용 (새로 짜지 말 것).
- 로컬 테스트 tests/test_cap_allocation.py: 합성 세계에서 배분 손계산 (몫 x 점수 비율, 카운티 합 보존, 빈 그룹 재정규화, 점수 0 -> 고르게);
  (a)+v57 = 원래 지도 그대로; OOF가 자기 카운티를 보지 않음 (자기 값을 바꿔도 자기 예측 불변); softmax 복원 합 1; capture 손계산.
- docs/conus_plan.md 절 "Cap allocation 1980", 러너북 29절, CLAUDE.md, open_items 갱신.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
- 해석은 하지 말고 숫자만.
