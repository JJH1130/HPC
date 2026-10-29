git pull 받고 아래를 해줘. 배경: docs/open_items.md "Meeting with Stefan, 2026-10-28" (1, 2, 2020, 4번)과 그 아래 "Settled with the user".
버전 이름: v5.4 = Dasy_CONUS_RF_v3_all (RF, v3 피처, 60 후보). 세 부분(A, B, C)은 서로 독립 - 하나가 실패해도 나머지가 돌게.

[A. 검증 지표 확장 - 다시 학습하지 않음, 기존 v5.4 결과로]
A1. 카운티 MdAPE (TEST 카운티): 각 연도 모델의 test_predictions.csv(배분 전 예측 log 밀도)로 예측 카운티 인구 =
    exp(yhat) x 면적(km2, 학습 target과 같은 면적 정의)을 만들어 센서스 인구와 비교. MdAPE, MAPE, R2(지금 TEST R2와 같은 값이
    나오는지 확인용), 카운티 수. CV(out-of-fold) 예측으로도 같은 지표를 train 카운티에 대해. 1900-2010 (+2020, B가 끝나면).
A2. 고정 tract 집합: tract가 있는 모든 연도(1910-2010, B 후 2020 포함)에 공통으로 tract가 있는 카운티의 tract만
    (각 연도의 그해 tract; 카운티 목록과 수를 로그와 CSV로). 1910이 포함되면 카운티가 너무 적을 수 있으니 시작 연도별
    변형도 같이: 1910+, 1920+, 1940+, 1960+ 공통 카운티 집합 각각. 지표: MdAPE, MAPE(10명 미만 제외), 면적 비례 기준선.
A3. 결과: results/validation/conus/Dasy_CONUS_RF_v3_all/ 에 county_metrics_by_year.csv, fixed_tract_metrics.csv,
    그림 하나 (연도별 MdAPE: 전체 tract / 고정 집합들 / 카운티 TEST, 면적 비례 기준선).
A4. 작은 버그: 인구 지도 PNG 제목 "Population per 1 km cell"과 색 막대 "people per 250 m cell"이 서로 다름. 실제로 그린 값에
    맞게 하나로 통일 (지도 다시 그리기는 B의 2020과 함께, 기존 연도는 재생성 필요 없으면 생략하고 이유 기록).

[B. 2020 추가]
- 카운티 입력: NHGIS 2020 카운티 인구를 2010 카운티 폴리곤에 매칭 (Stefan CSV는 2010까지). 2010->2020 사이 경계 변화
  (예: Connecticut 2022 planning regions는 2020 센서스엔 해당 없음 - 확인; Bedford city VA 2013 Bedford County 병합,
  Shannon SD -> Oglala Lakota 2015 이름/FIPS 변경, Alaska 제외 등)는 GISJOIN/FIPS 매핑으로 처리하고 처리 내역을 CSV로.
  status 규칙은 지금 conus_counties.py와 같게. NHGIS 2020 카운티 자료가 Alpine에 있는지 먼저 확인, 없으면 받는 방법.
- 컷아웃 2020: BUI(+ bui_fix), BUPL, BUPR, BUA, Land_Use 2020이 있는지 확인 (LU README는 1940-2015라고 함; 2020이 없으면
  2015를 쓰고 기록할지, 어떻게 할지 근거와 함께 제안 - 내가 정함), water_frac 2020 (GDW), DEM 재사용.
- 모델: v5.4와 같은 설정으로 Y2020 era (같은 split / fold / 탐색 공간 / n_iter 60). 별도 버전으로 덮어쓰지 말고
  Dasy_CONUS_RF_v3_all에 2020을 추가하는 게 단순하면 그렇게 (기존 연도 결과는 바뀌면 안 됨 - 재현 확인).
- tract 검증 2020, summary_by_year.csv / mdape_by_year.png를 1900-2020으로 갱신.

[C. HISDAC 기록 불확실성 진단 - 학습은 아직 안 함]
C1. BUPR_contemp.tif 받기: Harvard Dataverse doi:10.7910/DVN/45B8IU (BUPR 아카이브 안; README: 건축연도 유무와 무관한 모든
    ZTRAX 기록, ~2016). Dataverse API로 파일 목록 확인 후 그 파일만 받을 수 있으면 그것만. docs/data_sources.md에 먼저 등록.
    $DATA_ROOT/raw/hisdac_extra/ 에.
C2. 확인: CRS / 격자가 HISDAC 연도별 레이어와 같은지(같으면 그대로, 아니면 정렬), NobuiltYear.tif가 개수인지 0/1인지
    (값 분포), 셀 단위로 BUPR_contemp - BUPR_2015 와 NobuiltYear 비교 (같은가, 음수 셀이 얼마나 있나 - README상 contemp는
    ZTRAX만, 연도별은 ZTRAX + Parcel Atlas + Open City Model이라 다를 수 있음).
C3. 카운티별(2010 폴리곤, 우리 zone 격자) 연도 없는 기록 비율 두 가지:
    A = (contemp - BUPR_2015) / contemp (고정, 연도 무관; 음수는 0으로 하고 개수 기록)
    B_year = NobuiltYear / (BUPR_year + NobuiltYear) (연도별 상한; NobuiltYear가 개수일 때만)
    -> results/hisdac_uncertainty/county_record_uncertainty.csv
C4. 공백 카운티 가설: 지금의 BUI 공백 카운티(1인당 BUI < 중앙값 5 %, 2010 416개)가 비율 A가 높은 카운티인지 - 두 집합의 겹침,
    비율 A 분포 비교, 주별 요약.
C5. 임계값 표: 비율 A 임계값 0.1, 0.2, ..., 0.9 각각에서 남는 카운티 수, 인구 비율, train/test 카운티 수(split 기준), 주별 분포,
    그리고 연도별(B_year) 버전도. 그림: 임계값 vs 남는 카운티 수 / 인구 비율.
    학습 / imputation은 이 표를 보고 내가 임계값 후보와 선택 규칙을 정한 뒤에 따로 요청.

[공통]
- 로컬 테스트, 커밋, push. docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신.
- Alpine 명령: (1) 사전 확인(+ 필요한 다운로드), (2) 제출, (3) 로그 커밋 + seff 블록. 블록마다 끝에 성공 표시 한 줄.
  다운로드가 오래 걸리면 tmux 안에서 하도록 안내.
