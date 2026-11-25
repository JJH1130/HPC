git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "Cap allocation 1980: result". 1980 GHS-POP은 2010 센서스 입력을 거꾸로
외삽한 값이라 정답으로 부적절했음. 이번엔 GHS가 원본에 가까운 시기에서 "카운티 특성 -> 그룹 몫" 관계를 배우고, 그 관계를 과거 연도에
그 해 특성으로 적용 (연도마다 몫이 달라짐, Stefan 2026-11-25 "progression"), 그 해 tract로 검증. cap_allocation.py를 여러 연도로 일반화
(새 스크립트 말고 확장; 1980 결과 파일은 그대로 둠). 인구 모델 재학습 없음.

[0. 확인 + 데이터]
- GHSL 생성 방식 (JRC 문서, docs/data_sources.md Details에 출처와 함께): GHS-BUILT-S 관측 시기 = Landsat 1975 / 1990 / 2000 / 2014 +
  Sentinel-2 2018, 나머지는 보간; GHS-POP 인구 = GPWv4.11 센서스 입력 (미국 2010 센서스) + 추세. (출처:
  https://publications.jrc.ec.europa.eu/repository/bitstream/JRC144209/JRC144209_01.pdf). GPWv4.11 미국 입력 단위 (블록?)를 CIESIN
  문서로 확인 가능하면 기록, 못 하면 "unverified" 유지.
- GHS-BUILT-S R2023A 2014 (총 built surface) + 같은 epoch의 비주거 층 (bucket에 GHS_BUILT_S_NRES_E2014... 같은 파일이 있는지 listing으로
  확인; 있으면 받고, 없으면 총 면적만 쓰고 로그에 명시). external_download.sh에 추가 (크기 + sha256), data_sources.md 먼저.
- GHS-POP 2010은 이미 있음.

[1. 학습 연도와 목표 (몫 = 세 그룹 built / undated / no_record 비율, 1980과 같은 그룹 정의)]
- 목표 P (주): GHS-POP 2010 인구의 그룹 몫, HISDAC 그룹 = 2010 (BUI_2010, NOBUILT). 학습 피처 = 2010 카운티 특성.
- 목표 B (대안): GHS-BUILT-S 2014 주거 면적 (총 - 비주거; 비주거 없으면 총)의 그룹 몫, HISDAC 그룹 = 2010, 피처 = 2010. 센서스를 안 쓰는
  위성 자료라 tract와 순환 없음.
- cap 모델: 1980 run과 같은 고정 설정 (RF 두 개, y1 / y2 로그비, eps 1e-4, n_estimators 500, min_samples_leaf 5, max_features 0.5, seed 42).
  피처 = v5.7 그 해 county_features (1940 이전 연도는 res_share / rent_share 없음 -> 모든 연도에 공통인 피처만: bui, bldg_size, mu_ratio?,
  dist_built, elev, slope, nby + 그 해 셀 비율 3개; 공통 피처 목록을 1940 / 1960 / 1980 / 2010에 다 있는 것으로 정하고 로그에 출력).
  PLURAL 없음 (1960 없음, 1980 run에서 기여 없음). GHS 유래 피처 금지 (1980 run의 검사 그대로).
- 2010 학습: train 카운티 전체로 학습한 모델 = 과거 연도에 적용. 2010 자체에 적용할 때는 OOF (conus_split fold) + test는 train 전체 모델.
  2010 county CV (RMSE, 몫 MAE)를 cap_model 표에.

[2. 적용 연도와 방법 (연도 Y = 1940, 1960, 1980, 2010)]
- 그 해 셀 그룹 = BUI_Y, NOBUILT; 셀 마스크 / 카운티 인구 = v5.7 pop_Y.tif (질량 보존, P_c = census Y); 그룹 안 점수 = v5.7 셀 인구 (1980 run에서
  가장 나음; 다른 점수 없음).
- 방법:
  - v57: v5.7 자기 몫 (= v5.7, 확인용: 셀 / tract 결과 = v5.7, 1980 run의 동일성 검사 그대로).
  - P_transfer: 목표 P 모델에 Y년 피처 -> 몫.
  - P_scaled: P_transfer의 undated 몫 x f_c(Y) (f_c = 카운티 bupr_Y / bupr_2015, 0-1로 자름, bupr_2015 = 0이면 1;
    results/hisdac_uncertainty/county_record_uncertainty.csv, nby_age와 같은 정의), 줄어든 만큼 built / no_record에 비율대로 다시 배분 (합 1).
    2010은 f_c 거의 1.
  - B_transfer, B_scaled: 목표 B로 같은 두 가지.
  - 2010만 추가 (순환 참고, 사용자 요청): P_direct = GHS-POP 2010 몫 그대로, B_direct = GHS-BUILT 2014 몫 그대로.
- 확인: 모든 방법 카운티 합 = census Y; v57 = v5.7 (셀 + 그 해 tract_errors_Y.csv). 다르면 멈춤.

[3. 검증 (연도마다 tract, 1980 run과 같은 부분 / 같은 tract 집합 = v5.7 tract_errors_Y.csv의 평가 tract)]
- 부분: all, train / test, dens_*, kept / excluded t070, gap / no_gap, DEGURBA 카운티 구분 (1980 run의 county_missed_1980의 구분을 모든
  연도에 같이 씀 = 고정된 라벨, 1980 GHS 기준이라고 표에 명시). tract / 카운티 수 각 부분.
- d_mdape = 방법 - v5.7. 2010의 P_direct / P_transfer는 "circular (GHS-POP 2010 uses 2010 census)" 열 표시.
- 선택 규칙 없음 (보고용). 해석 없이 숫자만.

[4. 진단]
- 연도 x 방법 x DEGURBA 구분: 풀링한 그룹 몫 (built / undated / no_record) — 몫이 연도에 따라 어떻게 변하는지 (progression 확인).
- f_c 분포 (연도별 카운티 중앙값, 10 / 90 분위).

[출력]
- results/validation/conus/cap_transfer/: cap_model.csv (목표 P / B, 2010 CV), caps.csv (연도 x 카운티 x 방법 x 그룹), group_shares.csv,
  tract_metrics.csv (연도 x 방법 x 부분), tract_pop.csv.gz, tract_mdape.png (연도별 패널, 방법별 막대 + v5.7 선).

[공통]
- cap_allocation.py 확장 (예: 명령 transfer) + sbatch / submit 모드 captransfer (사전 확인: 새 GHS-BUILT 파일, 4개 연도 pop / tract_errors /
  컷아웃 BUI 층, county_record_uncertainty.csv; 잡 하나 또는 연도별 병렬). 1980 run의 코드 / 결과는 바뀌지 않아야 함 (기존 테스트 그대로 통과).
- 로컬 테스트: 합성 세계 2개 연도 — 학습 연도 모델을 다른 연도에 적용 (피처만 바뀌면 몫이 바뀜), scaled 손계산 (f_c 곱 + 재배분 합 1), v57 동일성,
  카운티 합 보존, 공통 피처 목록, GHS 유래 피처 금지.
- docs/conus_plan.md 절 "Cap transfer (learn 2010, apply 1940-1980)", 러너북 30절, CLAUDE.md, open_items, data_sources 갱신.
- Alpine 명령: (0) 다운로드 (로그인 노드), (1) 사전 확인 + 제출, (2) 로그 + 결과 커밋. 블록 끝마다 성공 표시 한 줄.
- 사용자에게 하는 보고는 한국어로.

[추가 2026-11-26 (사용자): PLURAL을 몫 안 배분에 넣음]
- cap 모델 피처에는 PLURAL 없음 (위 그대로). 대신 몫을 정한 뒤 빈 셀 그룹 안에서 나누는 점수에 PLURAL을 씀.
- 점수 (그룹 안): v57 (모든 그룹, 주) / plural_inv (built 그룹 = v57, undated / no_record 그룹 = 1 - PLURAL) / mixed (built + undated = v57,
  no_record = pq5) / pq5_unbuilt (built = v57, undated / no_record = pq5). 1980 run의 정의 그대로.
- PLURAL 격자 (컷아웃 PLURAL)와 pq5 예측은 1940 / 1980 / 2010만 있음 -> 1960은 v57 점수만 (표에 "no PLURAL grid" 표시).
- 조합 = 몫 방법 x 점수; tract 표 / 그림에 점수 축 추가. 확인 규칙 (카운티 합, v57 + v57 = v5.7)은 그대로.
