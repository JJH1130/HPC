git pull 받고 아래를 해줘. 배경: Stefan 미팅 2026-11-25 (docs/open_items.md "Meeting with Stefan, 2026-11-25", Next steps 1 + 2).
1980년에 HISDAC이 놓친 셀 (HISDAC상 건물 없음 BUI_1980 = 0인데 GHS-POP 1980에는 사람이 있는 셀)이 어디에 얼마나 있는지,
v5.7이 거기에 얼마나 줬는지, PLURAL / remoteness가 그 셀을 얼마나 골라내는지 진단. 모델 / 학습 / 예측 변경 없음, 1980년 한 해.
CONUS 전체 (2010 카운티, 학습에 쓰는 status 그대로).

중요 원칙: 임의 문턱 쓰지 않음. "놓친 셀"을 GHS-POP > x 로 자르지 말고, HISDAC 빈 셀 위의 GHS-POP 인구를 연속값(질량)으로 다룸.
구간이 필요한 곳은 DEGURBA (GHS-SMOD 1980, 이미 받음)만 씀.

[0. 데이터: GHS-BUILT-S R2023A 1980]
- JRC GHS-BUILT-S R2023A (built-up surface, m2 per cell), 100 m Mollweide, 1980. 같은 JRC S3 bucket (ghs-built-s/r2023a/54009/100m/1980/);
  bucket listing으로 정확한 파일 이름 / 크기 확인 후 sbatch/external_download.sh에 PRODUCTS=ghs_built 추가 (기존 ghs_pop / ghs_smod와 같은
  방식: 크기 확인, sha256 기록, 로그인 노드). docs/data_sources.md에 먼저 행 + Details (인용 Pesaresi & Politis 2023, URL, 버전, 단위).
- configs/external_grids.yaml에 ghs_built 항목 (path, years [1980]).

[1. 우리 250 m 격자로 옮기기 (strip 단위, CONUS 전체)]
- GHS-POP 1980, GHS-BUILT 1980: external_city_maps.to_grid와 같은 방식 (k x k sub-point, 합 보존)으로 우리 250 m 셀에. CONUS 전체를
  block_rows strip씩 (configs/conus_rf_v3_all_nby.yaml / conus_study_area.yaml의 값). strip 결과 = 창 전체 결과 (테스트).
- 셀 마스크 = v5.7 pop_1980.tif가 값을 가진 셀 (연구 셀, 물 마스크 후). 마스크 밖으로 떨어진 GHS 인구는 따로 합산해서 로그 (해안 / 국경 / 물).
- 같이 읽을 것: BUI_1980 (컷아웃), NOBUILT (컷아웃), PLURAL 1980 (컷아웃 layer PLURAL, bilinear), 카운티 zone 1980, v5.7 / v5.7 + PLURAL
  pq5 / v5.4 pop_1980.tif, GHS-SMOD 1980 (degurba_boxes.smod_on_cells, 1 km 블록 다수결 = 구간 A와 같게).
- remoteness: 컷아웃에 1980 PLACEDIST (place_dist d_10k ... d_250k)가 있으면 같이 씀; 없으면 이번엔 PLURAL만 (로그에 명시, 새 레이어
  만들지 않음).

[2. 셀 그룹 (DEGURBA boxes와 같은 정의)]
- built = BUI_1980 > 0; unbuilt = BUI_1980 = 0, 그 안을 undated (NOBUILT > 0) / no_record (= 0).
- 셀 구분: GHS-SMOD 1980 블록 구간 A (urban 30 / peri_urban 21-23 / rural 11-13, 물 10 제외) — 셀은 자기 블록의 구간.
- 카운티 구분: DEGURBA 매뉴얼 Level 1 공식 규칙 (2021 manual): GHS-POP 1980 인구 기준, 카운티 인구의 >= 50 %가 urban centre (30) 셀이면
  city; >= 50 %가 rural (11-13) 셀이면 rural; 나머지 town_suburb. (상자 고를 때 쓴 "cluster 하나도 없음" 규칙 아님.) 규칙을 로그에 출력.

[3. 카운티 표 (county_missed_1980.csv, 카운티 한 행)]
- GISJOIN, 주, census 1980 인구, 카운티 구분, 셀 수 (built / undated / no_record).
- 각 지도 (GHS-POP, v5.7, pq5, v5.4)의 카운티 인구 합 + unbuilt / undated / no_record 셀 인구 비율 (지도 자기 카운티 합 대비).
  -> 핵심 열: ghs_unbuilt_share, v57_unbuilt_share, gap = ghs - v57.
- GHS-POP 카운티 합 / census (GHS 자체가 카운티 총량을 얼마나 맞추는지; 1980 GHS-POP은 back-cast 값이라 참고).
- GHS-BUILT: 카운티 built surface 합 중 HISDAC unbuilt 셀 위 비율 (위성은 건물이라는데 HISDAC은 빈 셀) + undated / no_record 나눠서.
- 같은 셀 겹침: unbuilt 셀에서 v57 vs GHS-POP overlap = sum min(a_i, b_i) (degurba_boxes.overlap_metrics 그대로), even-spread 기준선.

[4. 요약 (by_class_1980.csv + 로그 표)]
- 카운티 구분 x 셀 구분 (urban / peri_urban / rural 셀) 별로 셀을 모아 (카운티 평균 아님): 인구 합, unbuilt 비율 (GHS / v57 / pq5 / v5.4),
  GHS-BUILT unbuilt 비율, overlap. 그리고 카운티 gap 분포 (중앙값, 10 / 90 분위) 카운티 구분별.
- "대도시 외곽" 확인: city 카운티 안의 rural 셀 / peri_urban 셀 행이 따로 보이게.

[5. PLURAL / remoteness가 놓친 셀을 고르나 (plural_capture_1980.csv + 그림)]
- 대상: unbuilt 셀 (전체, 그리고 카운티 구분별). 목표 = GHS-POP 인구 (질량).
- unbuilt 셀을 점수로 줄세워서 상위 k % 셀 (k = 1, 2, 5, 10, 20, 50 %; 셀 수 기준)이 GHS-POP unbuilt 인구의 몇 %를 담는지 (capture curve).
  점수: (a) GHS-POP 자체 = 상한, (b) 1 - PLURAL (덜 외진 곳 먼저), (c) v5.7 셀 인구 (모델이 고른 순서), (d) pq5 셀 인구, (e) NOBUILT,
  (f) d_* 있으면 -거리, (g) 무작위 = k % (기준선). 줄세우기는 카운티 안에서 (카운티마다 상위 k %, 그 다음 합) — 배분이 카운티 안 문제라서;
  CONUS 전체 한 줄세우기도 참고로 한 줄.
- 추가: unbuilt 셀에서 Spearman (점수 vs GHS-POP), 카운티 안 순위 기준 (카운티별 Spearman의 중앙값).
- 그림: capture curve 하나 (x = 상위 k %, y = 담은 GHS 인구 %, 점수별 선, 무작위 대각선), 카운티 구분별 패널 3개.

[6. 확인 (다르면 멈춤)]
- DEGURBA 11개 상자 안 셀만 모으면, 1980 unbuilt / undated / no_record 인구 합 (GHS-POP, v57, pq5)이
  results/validation/conus/external/degurba_boxes_v57/cell_type_shares.csv (1980, scheme A)의 같은 값과 같아야 함 (상자마다; 옮기는 방식이 같으니
  같아야 함). 다르면 멈춤.
- v57 카운티 합 = census 1980 (질량 보존; 예측이 있는 카운티). 다르면 멈춤.
- 지도와 자기 자신 overlap = 1, capture curve의 GHS 자체 점수가 모든 k에서 다른 점수 이상 (테스트).

[출력]
- results/validation/conus/missed_cells_1980/: county_missed_1980.csv, by_class_1980.csv, plural_capture_1980.csv, capture_1980.png,
  county_gap_1980.png (CONUS 카운티 지도: gap = ghs_unbuilt_share - v57_unbuilt_share, 발산 색, 0 = 흰색).
- 로그 요약표: 카운티 구분별 unbuilt 비율 (GHS / v57 / pq5 / v5.4), gap 분포, capture (k = 5 / 10 / 20 %) 점수별.

[공통]
- 새 스크립트 src/validation/missed_cells.py (명령 run; --check = 입력만), sbatch/missed_cells.sh, submit_conus.sh 모드 missed1980 (사전 확인:
  입력 파일 / 컷아웃 레이어 / GHS-BUILT; 잡 하나). 메모리 / 시간은 degurba_boxes와 aggregation_diag 사이 규모 (CONUS strip).
- 로컬 테스트 tests/test_missed_cells.py: 합성 격자에서 to_grid 합 보존 + strip = 창 전체; 셀 그룹 / 카운티 구분 (50 % 규칙, 경계값) 손계산;
  unbuilt 비율 / overlap / capture curve 손계산 (상한 >= 다른 점수, 무작위 = k); 상자 합 대조가 다르면 멈춤.
- docs/conus_plan.md 절 "1980 missed cells", 러너북 28절, CLAUDE.md, open_items 갱신.
- Alpine 명령: (0) GHS-BUILT 다운로드 (로그인 노드), (1) 사전 확인 + 제출, (2) 로그 + 결과 커밋. 블록 끝마다 성공 표시 한 줄.
- 해석은 하지 말고 숫자만 (해석은 Claude가 pull 후).
