git pull 받고 아래를 해줘. 배경과 결정: docs/open_items.md "CONUS: hyperparameter sensitivity and source gaps" (Model family), docs/conus_plan.md "BUI fix + v1_bui / v3_bui result", Order 6.

[목적]
모든 연도(1900-2010)로 가기 전에 모델 종류를 정한다. RF, LightGBM, XGBoost, CatBoost 네 개를 같은 조건으로 비교.
- 피처: Dasy_CONUS_RF_v3_bui와 똑같이 (v1 피처 + elev, slope), BUI 처리된 컷아웃, 1920 / 1960 / 2010.
- split / fold: 같은 configs/conus_split.csv, folds_from Dasy_CONUS_RF_v3_bui. compare_with Dasy_CONUS_RF_v3_bui.
- RF는 이미 있는 Dasy_CONUS_RF_v3_bui 결과를 그대로 씀 (다시 돌리지 않음).
- 새 버전 이름: Dasy_CONUS_LGBM_v3_bui, Dasy_CONUS_XGB_v3_bui, Dasy_CONUS_CAT_v3_bui. 설정 파일 configs/conus_{lgbm,xgb,cat}_v3_bui.yaml
  (conus_rf_v3_bui.yaml 복사 후 model / models 블록만 다르게).

[1. 환경]
- envs/hisdac/environment.yml에 xgboost, catboost 추가 (conda-forge, lightgbm은 이미 있음). docs/runbooks/Creating_Env_hisdac.md에
  갱신 절차(conda env update --prune) 반영, sbatch/test_env_hisdac.sh에 import 확인 추가. ad-hoc mamba install 금지.
- Alpine 명령 블록 맨 앞에 env 업데이트 + test_env_hisdac 확인을 넣어 줘 (이게 실패하면 나머지 제출하지 않게).

[2. train.py]
- MODELS 레지스트리에 lgbm, xgb, catboost 빌더 구현 (지금은 not_in_v1). sklearn API (LGBMRegressor, XGBRegressor, CatBoostRegressor)로
  RandomizedSearchCV / cross_val_predict / permutation_importance / SHAP(TreeExplainer)가 RF와 똑같이 돌게.
- 병렬은 search 쪽에서만: 각 모델 내부 스레드는 1 (n_jobs=1 / thread_count=1), 로그 끄기 (verbose=-1 / verbosity=0 / verbose=0,
  CatBoost allow_writing_files=False). random_state / random_seed 42. XGBoost tree_method hist.
- 조기 종료(early stopping)는 쓰지 않음 (RF와 같은 CV 절차 유지). 후보 수 n_iter 20, scoring neg RMSE, 5 fold - RF와 동일.
- 탐색 범위 (config의 models.<name>.space):
  lgbm: n_estimators [200, 500, 1000, 2000], learning_rate [0.01, 0.03, 0.05, 0.1], num_leaves [7, 15, 31, 63],
        min_child_samples [5, 10, 20, 40], subsample [0.7, 0.85, 1.0] (fixed subsample_freq 1), colsample_bytree [0.5, 0.75, 1.0],
        reg_lambda [0, 1, 5]
  xgb:  n_estimators [200, 500, 1000, 2000], learning_rate [0.01, 0.03, 0.05, 0.1], max_depth [3, 4, 6, 8],
        min_child_weight [1, 3, 5, 10], subsample [0.7, 0.85, 1.0], colsample_bytree [0.5, 0.75, 1.0], reg_lambda [0, 1, 5]
  catboost: iterations [300, 500, 1000, 2000], learning_rate [0.01, 0.03, 0.05, 0.1], depth [4, 6, 8], l2_leaf_reg [1, 3, 5, 10]
- 모델 저장/로드(predict.py)도 세 모델 다 되게. 예측 방식(w = exp(yhat), 카운티 질량 보존)은 그대로.

[3. 예측 / 검증]
- 예측은 지금처럼 CONUS 전체 (연도당 약 3분이라 병목 아님; 배분이 카운티 전체 셀 합으로 나누는 방식이라 tract 지역만 예측할 수 없음).
- tract 검증은 기존과 동일 (train / test 부분, 밀도 4묶음).
- 추가: tract 지표를 "BUI 공백 카운티 제외" 버전으로도. 공백 카운티 = 카운티 BUI 바닥면적 / 인구 (county mean bui x (n_cells - n_masked) / pop)가
  그해 전국 중앙값의 5% 미만 (county_features.csv로 계산; 2010 기준 416개). metrics에 gap 카운티 tract 수와 함께 all / no_gap 둘 다.
  기존 RF v3_bui도 validate만 다시 돌려서 같은 표를 얻게.

[4. 비교 표]
- src/validation/compare_models.py (가벼운 잡 또는 체인 끝): 4개 버전 x 3개 연도로 results/validation/conus/model_comparison.csv:
  CV RMSE (mean, sd), CV R2, TEST RMSE, TEST R2, tract MdAPE / MAE / R2 (all, train part, test part, no_gap, 밀도 4묶음별 MdAPE),
  선택된 하이퍼파라미터, train 시간. 로그에도 연도별 요약 표.
- county_maps: 2010, 같은 4개 카운티(Chelan WA, Reno KS, Fremont CO, Macoupin IL)로 4개 모델.

[5. 자원]
- submit_conus.sh에 models 모드 추가: env check -> (LGBM, XGB, CAT 각각 features 재사용 가능하면 재사용 / train / predict / validate)
  + RF validate 재실행 -> compare_models -> county_maps. features는 v3_bui와 같으니 v3_bui 것을 복사/링크해서 다시 계산하지 않아도 됨 (단순한 쪽으로).
- 부스팅 search 시간은 RF와 다를 수 있으니 train wall time은 RF 측정치(9분)의 여유 있게(예: 1시간), 나머지는 bui 체인 값 그대로.

[공통]
- 테스트: tests/test_conus_dasymetric.py에 세 모델이 작은 합성 데이터에서 search -> fit -> 저장 -> 로드 -> 예측 -> 질량 보존이 되는지,
  gap 카운티 제외 지표가 맞는지 추가. 로컬 hisdac env에 xgboost/catboost가 없으면 설치는 yml로.
- docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신. 로컬 테스트, 커밋, push 후 Alpine 명령(env 업데이트 확인 + 체인 + 로그 커밋 + seff)을
  하나의 완전한 블록으로, 블록마다 끝에 무엇이 출력되면 성공인지 한 줄씩.
