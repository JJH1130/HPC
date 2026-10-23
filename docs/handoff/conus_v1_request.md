git pull 받고, docs/conus_plan.md(CONUS 계획)를 먼저 읽은 뒤 아래를 해줘. 결정 사항은 docs/open_items.md 결정 기록(2026-10-23)에 있어.
매사추세츠 설정(configs/study_area.yaml, configs/model.yaml의 v4_1)은 재현용으로 그대로 두고, CONUS는 별도 설정 파일로 만들어줘.

[고정 사항]
- 격자: HISDAC-US 원래 격자 그대로 (250 m, ESRI:102039). HISDAC 레이어는 리샘플링 없이 그대로 읽고, 창 = HISDAC 래스터의 CONUS 전체 범위.
  물(JRC + GDW), 거리(PLURAL place), 그 밖의 외부 레이어만 이 격자에 맞춰 옮김 (MA와 같은 규칙).
- 이름: Dasy_CONUS_RF_v1 (피처 = MA v3.4 세트: bui, bldg_size, mu_ratio, dist_built, 1940년부터 res_share, rent_share; 연도별 GDW 물 마스크),
  Dasy_CONUS_RF_v2 (= v1 + d_10k, d_20k, d_50k, d_100k, d_250k, 1940년부터). 지형은 이번에 안 넣음.
- 연도: 시범으로 1920, 1960, 2010만. 전체는 나중에 1900-2010 센서스 연도. 2020은 나중에 NHGIS에서.
- 모델: 연도별 RF 하나씩 (해마다 카운티 약 3,000개). 연도별 모델이라 year 피처는 뺌. 탐색 공간은 지금 model.yaml과 같게.
- 인구 입력: Stefan CSV를 2010 카운티 경계에 붙인 것 (std_county_check가 만든 counties_std_2010.gpkg, data/census_std/의 CSV).
  CSV 값이 없는 카운티(1900년 291개 등)는 학습과 배분에서 제외하는 status로 처리 (지금 county_selection은 pop<=0이면 멈춤).
  그 카운티 셀은 NoData. 알려진 오류는 conus_plan.md "Known input errors" 참고, 일단 감수.
- train/test: 각 주 안에서 카운티를 무작위 80:20 (주별 층화, 시드 고정), 튜닝 전에 한 번만.
  분할표(2010 FIPS 또는 GISJOIN -> train/test)와 train 안의 5-fold(카운티 단위 GroupKFold) 표를 git에 기록되는 파일로 저장하고
  모든 연도, 모든 버전(v1, v2)에서 재사용. test 카운티는 학습과 튜닝에 안 쓰고, 배분에는 그 카운티 총인구를 그대로 씀.
  보고: train CV 점수 + test 점수 한 번. 밀도 층화나 반복 분할은 하지 않음.
- 검증: tract_validate를 CONUS로 확장, train 카운티와 test 카운티를 따로 보고. tract 범위: 1920 14개 카운티, 1960 302개, 2010 전국.

[해야 할 일]
1. 규모 점검: conus_plan.md "Scale checks" 표의 단계별로(cutout, water_frac, place_dist, county_features, train, predict, validate)
   창 전체 배열을 메모리에 올리는 곳, 시간이 오래 걸릴 곳을 코드에서 찾아줘. MA 창은 1711 x 2842 셀, CONUS는 HISDAC 격자 실제 크기로 계산.
   단계별 메모리/시간/디스크 추정치를 표로 정리해서 conus_plan.md에 추가.
2. 필요한 곳은 블록(타일) 단위나 병렬로 고쳐줘. 특히:
   - predict: 연도당 약 1억 셀 x RF 수백~1000그루가 가장 무거움. 블록 단위 + 병렬, 사용하는 카운티 안의 셀만 예측.
   - dist_built: 창 전체 distance transform 메모리.
   - water_frac: JRC CONUS 타일 21개, GDW 미국 전체.
3. CONUS 설정 파일, sbatch 스크립트(자원은 추정치에 맞게, #SBATCH --account=ucb852_asc1 유지), 러너북 섹션
   (docs/runbooks/에 CONUS 실행 절차) 작성.
4. 바로 전체 CONUS를 돌리지 말고, 먼저 작은 시험 실행(예: 한 개 주 또는 1960년 한 해의 일부)으로
   시간과 메모리를 실제로 재는 단계를 러너북 맨 앞에 넣어줘. 그 결과를 보고 1920/1960/2010 시범 실행으로 넘어가는 순서.
5. 로컬에서 가능한 테스트는 합성 데이터로 돌리고, 커밋 후 push. 내가 Alpine에 붙여넣을 명령(사전 확인 + 시험 실행 체인 + 로그 커밋)을 줘.
6. CLAUDE.md, docs/open_items.md, docs/data_sources.md 필요한 곳 갱신.

막히는 결정(예: CONUS 창 정의, 상태값 이름, 파일 위치)이 있으면 conus_plan.md 원칙에 맞게 가장 단순한 쪽으로 정하고, 정한 내용을 요약해서 알려줘.
