git pull 받고 아래를 해줘. 배경: CONUS v5.4(= Dasy_CONUS_RF_v3_all, RF, v3 피처, 60 후보)의 tract 오차를 기존 인구 격자 자료와
같은 tract, 같은 지표로 비교해서 우리 결과가 어느 수준인지 보이려는 것. 버전 이름 규칙: CONUS = v5 계열 (docs/open_items.md 2026-10-28).

[대상 자료와 연도] (US 1910-2010 tract 중 겹치는 연도만)
- GHS-POP R2023A (EU JRC): 1980, 1990, 2000, 2010. 100 m (Mollweide) 우선; 용량이 너무 크면 CONUS 타일만 받거나 3 arc-sec(WGS84) 판.
- WorldPop (Univ. of Southampton): USA 100 m, unconstrained top-down, 2000, 2010 (usa_ppp_{YEAR}.tif 계열; UN-adjusted 아닌 것).
- GPW v4.11 population count (CIESIN / NASA SEDAC): 2000, 2010, 30 arc-sec, UN-adjusted 아닌 것.
- GRUMP v1 population count (CIESIN / NASA SEDAC): 1990, 2000, 30 arc-sec.
- Fang & Jawitz (2018), Scientific Data, doi:10.1038/sdata.2018.67: 카운티 입력 1 km 재구성 1910-2010 (1960 없음), figshare.
  모델 M3, M5 둘 다 (논문에서 M3 = 가장 효율적, M5 = tract 오차 최소). 입력 조건이 우리와 같은(카운티) 유일한 비교 대상.
- 각 자료를 docs/data_sources.md에 먼저 등록(요약 행 + Details: 인용, 버전, 라이선스, 다운로드 URL).
- **각 자료가 미국에서 입력으로 쓴 센서스 단위(블록 / 블록그룹 / tract / 카운티)를 공식 문서에서 확인해 Details와 결과 표에 기록**
  (출처 URL 포함). tract보다 세밀한 입력을 쓴 자료는 tract 검증에서 유리하므로 결과 해석에 필요. 확인 못 하면 "unverified"로.

[다운로드]
- sbatch/external_download.sh (로그인 노드에서 실행, 잡 아님; ntlv_download.sh와 같은 방식): 공개 자료(GHS-POP, WorldPop, Fang & Jawitz)를
  $DATA_ROOT/raw/external/<product>/ 로, 체크섬/크기 확인.
- GPW, GRUMP는 NASA Earthdata 로그인이 필요할 수 있음: ~/.netrc 방식으로 받는 명령을 주고, 안 되면 내가 노트북에서 받아 올리는
  방법(scp)도 같이. 이 둘이 없어도 나머지 체인은 돌아가게 (없는 자료는 건너뛰고 로그에 표시).

[tract 집계와 평가] src/validation/external_compare.py + sbatch/external_compare.sh
- 각 자료의 픽셀 인구를 자료의 원래 좌표계에서 tract 폴리곤으로 합산(부분 겹침은 면적 비율; exactextract 같은 정확한 방법,
  env 변경은 envs/hisdac/environment.yml + conda env update로만). 우리 결과처럼 재투영 / 리샘플은 하지 않음.
- tract 집합: 우리 tract 검증과 같은 tract (tracts_{YEAR}.gpkg, 같은 필터), 그중 자료가 NoData 없이 덮는 tract만.
  공정 비교를 위해 v5.4도 같은 tract 부분집합에서 다시 계산(tract_errors_{YEAR}.csv 재사용).
- 지표: MdAPE, MAPE (인구 10명 미만 tract 제외), p90 APE, 밀도 4묶음 MdAPE, BUI 공백 카운티 / 나머지 MdAPE, tract 수, 커버 비율.
  면적 비례 기준선도 같은 부분집합에서.
- 출력: results/validation/conus/external/external_comparison.csv (자료 x 연도, 입력 단위 열 포함),
  그림 하나: 연도별 tract MdAPE (v5.4, 면적 비례, 각 자료).

[공통]
- 로컬 합성 테스트(작은 격자 + 폴리곤으로 부분 겹침 합산 = brute force, NoData tract 제외, 부분집합에서 v5.4 재계산), 커밋, push.
- docs/conus_plan.md("External comparison"), docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신.
- 사용자는 실행 후 자리를 비울 예정: Alpine 명령은 (1) 다운로드 + 확인 블록, (2) 사전 확인 + 체인 제출 블록,
  (3) 나중에 돌아와서 할 로그 커밋 + seff 블록으로, 블록마다 끝에 성공 표시 한 줄. 체인은 자료 하나가 실패해도 나머지가 끝까지 가게.
