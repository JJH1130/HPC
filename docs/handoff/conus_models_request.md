git pull 받고 아래를 해줘. 배경과 결정: docs/open_items.md "CONUS: hyperparameter sensitivity and source gaps" (Model family), docs/conus_plan.md "BUI fix + v1_bui / v3_bui result", Order 6.

[목적]
모든 연도(1900-2010)로 가기 전에 모델 종류를 정한다. RF, LightGBM, XGBoost, CatBoost 네 개를 같은 조건으로 비교.
- 피처: Dasy_CONUS_RF_v3_bui와 똑같이 (v1 피처 + elev, slope), BUI 처리된 컷아웃, 1920 / 1960 / 2010.
- split / fold: 같은 configs/conus_split.csv, folds_from Dasy_CONUS_RF_v3_bui. compare_with Dasy_CONUS_RF_v3_bui.
- 네 모델 모두 같은 탐색 예산(후보 60개)으로 새로 돌림. RF도 다시 (기존 Dasy_CONUS_RF_v3_bui는 후보 20개, 참고용으로 그대로 둠).
- 새 버전 이름: Dasy_CONUS_RF_v3_n60, Dasy_CONUS_LGBM_v3_n60, Dasy_CONUS_XGB_v3_n60, Dasy_CONUS_CAT_v3_n60.
  설정 파일 configs/conus_{rf,lgbm,xgb,cat}_v3_n60.yaml (conus_rf_v3_bui.yaml 복사 후 model / models / search.n_iter만 다르게).

[1. 환경]
- envs/hisdac/environment.yml에 xgboost, catboost 추가 (conda-forge, lightgbm은 이미 있음). docs/runbooks/Creating_Env_hisdac.md에
  갱신 절차(conda env update --prune) 반영, sbatch/test_env_hisdac.sh에 import 확인 추가. ad-hoc mamba install 금지.
- Alpine 명령 블록 맨 앞에 env 업데이트 + test_env_hisdac 확인을 넣어 줘 (이게 실패하면 나머지 제출하지 않게).

[2. train.py]
- MODELS 레지스트리에 lgbm, xgb, catboost 빌더 구현 (지금은 not_in_v1). sklearn API (LGBMRegressor, XGBRegressor, CatBoostRegressor)로
  RandomizedSearchCV / cross_val_predict / permutation_importance / SHAP(TreeExplainer)가 RF와 똑같이 돌게.
- 병렬은 search 쪽에서만: 각 모델 내부 스레드는 1 (n_jobs=1 / thread_count=1), 로그 끄기 (verbose=-1 / verbosity=0 / verbose=0,
  CatBoost allow_writing_files=False). random_state / random_seed 42. XGBoost tree_method hist.
- 조기 종료(early stopping)는 쓰지 않음 (RF와 같은 CV 절차 유지). 후보 수 n_iter 60 (네 모델 동일), scoring neg RMSE, 5 fold.
- 탐색 공간에 연속 분포 지원 추가 (config의 models.<name>.space). 값이 리스트면 지금처럼 그중 하나, 딕셔너리면 분포:
    {dist: loguniform, low: a, high: b}  -> scipy.stats.loguniform(a, b)
    {dist: uniform, low: a, high: b}     -> scipy.stats.uniform(a, b - a)
    {dist: randint, low: a, high: b}     -> scipy.stats.randint(a, b + 1)  (b 포함)
  연속 분포가 하나라도 있으면 후보 수 = n_iter (지금의 리스트 길이 곱 계산은 리스트만 있을 때만). era의 params: 고정값은 지금처럼 [v]로 덮어씀.
  기존 리스트 설정(MA configs/model.yaml 등)은 그대로 돌아야 함. 로그와 metrics.json에 공간 정의와 고른 값 기록.
- 탐색 범위:
  rf:   n_estimators randint 200-1000, max_depth [null, 5, 10, 15, 20, 30], min_samples_leaf randint 1-10,
        max_features [sqrt, 0.33, 0.5, 0.75, 1.0]
  lgbm: n_estimators randint 200-2000, learning_rate loguniform 0.01-0.2, num_leaves randint 7-63,
        min_child_samples randint 5-50, subsample uniform 0.5-1.0 (fixed subsample_freq 1), colsample_bytree uniform 0.5-1.0,
        reg_lambda loguniform 1e-3 - 10, reg_alpha loguniform 1e-3 - 10
  xgb:  n_estimators randint 200-2000, learning_rate loguniform 0.01-0.2, max_depth randint 3-8,
        min_child_weight randint 1-10, subsample uniform 0.5-1.0, colsample_bytree uniform 0.5-1.0,
        reg_lambda loguniform 1e-3 - 10, reg_alpha loguniform 1e-3 - 10
  catboost: iterations randint 300-2000, learning_rate loguniform 0.01-0.2, depth randint 4-8,
        l2_leaf_reg loguniform 0.1-10, rsm uniform 0.5-1.0, subsample uniform 0.5-1.0 (fixed bootstrap_type Bernoulli)
- 모델 저장/로드(predict.py)도 세 모델 다 되게. 예측 방식(w = exp(yhat), 카운티 질량 보존)은 그대로.

[3. 예측 / 검증]
- 예측은 지금처럼 CONUS 전체 (연도당 약 3분이라 병목 아님; 배분이 카운티 전체 셀 합으로 나누는 방식이라 tract 지역만 예측할 수 없음).
- tract 검증은 기존과 동일 (train / test 부분, 밀도 4묶음).
- 추가: tract 지표를 "BUI 공백 카운티 제외" 버전으로도. 공백 카운티 = 카운티 BUI 바닥면적 / 인구 (county mean bui x (n_cells - n_masked) / pop)가
  그해 전국 중앙값의 5% 미만 (county_features.csv로 계산; 2010 기준 416개). metrics에 gap 카운티 tract 수와 함께 all / no_gap 둘 다.
  기존 Dasy_CONUS_RF_v3_bui도 validate만 다시 돌려서 같은 표를 얻게 (20개 vs 60개 후보 비교용).

[4. 비교 표]
- src/validation/compare_models.py (가벼운 잡 또는 체인 끝): n60 4개 + 기존 RF v3_bui = 5개 버전 x 3개 연도로 results/validation/conus/model_comparison.csv:
  CV RMSE (mean, sd), CV R2, TEST RMSE, TEST R2, tract MdAPE / MAE / R2 (all, train part, test part, no_gap, 밀도 4묶음별 MdAPE),
  선택된 하이퍼파라미터, train 시간. 로그에도 연도별 요약 표.
- county_maps: 2010, 같은 4개 카운티(Chelan WA, Reno KS, Fremont CO, Macoupin IL)로 n60 4개 모델.

[5. 자원]
- submit_conus.sh에 models 모드 추가: env check -> (RF, LGBM, XGB, CAT n60 각각 train / predict / validate)
  + RF v3_bui validate 재실행 -> compare_models -> county_maps. features는 v3_bui와 같으니 v3_bui 것을 복사/링크해서 다시 계산하지 않아도 됨 (단순한 쪽으로).
- 후보가 3배이고 부스팅 시간은 RF와 다를 수 있으니 train wall time은 RF 측정치(20개 후보 9분)보다 여유 있게(예: 2시간), 나머지는 bui 체인 값 그대로.

[공통]
- 테스트: 분포 설정 파싱(리스트 / loguniform / uniform / randint, era params 덮어쓰기, 기존 리스트 설정 그대로)과, 세 모델이 작은 합성 데이터에서 search -> fit -> 저장 -> 로드 -> 예측 -> 질량 보존이 되는지,
  gap 카운티 제외 지표가 맞는지 추가. 로컬 hisdac env에 xgboost/catboost가 없으면 설치는 yml로.
- docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신. 로컬 테스트, 커밋, push 후 Alpine 명령(env 업데이트 확인 + 체인 + 로그 커밋 + seff)을
  하나의 완전한 블록으로, 블록마다 끝에 무엇이 출력되면 성공인지 한 줄씩.
