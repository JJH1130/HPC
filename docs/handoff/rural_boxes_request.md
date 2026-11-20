git pull 받고 아래를 해줘. (이 파일은 2026-11-21에 다시 썼음: 임의 밀도 경계 대신 Degree of Urbanisation. 예전 판으로 시작한 작업이
있으면 이 판에 맞춰 고칠 것.)

배경: docs/conus_plan.md "City boxes by density class: result". 지금 비교 상자 (Boston / Denver / Chicago 40 x 40 km)의 "rural"은
대도시 외곽뿐이고, 구간 경계 (블록 밀도 100 / 1,000)는 근거 없는 값이었음. 사용자 결정 (2026-11-21): 구간은 EU / UN Degree of
Urbanisation (DEGURBA) 정의로, 상자도 같은 기준으로 골라 진짜 시골 / 근교 상자를 추가.

[0. 데이터: GHS-SMOD R2023A]
- JRC GHS-SMOD R2023A (DEGURBA stage I을 GHS-POP R2023A + GHS-BUILT-S R2023A에 적용한 격자, 1 km Mollweide, 1975-2030 5년 간격).
  1980 / 2010 (+ 상자 고르기에는 2010). docs/data_sources.md에 먼저 행 + Details (인용, 다운로드 URL, 버전, 클래스 코드: 30 urban centre,
  23 / 22 / 21 urban cluster 계열, 13 / 12 / 11 rural 계열, 10 water). sbatch/external_download.sh에 추가 (로그인 노드, 기존 GHS-POP과
  같은 방식, 체크섬 기록). 클래스 코드는 받은 파일의 문서로 확인하고 로그에 출력.
- 우리 250 m 격자로: 각 250 m 셀 중심이 들어가는 SMOD 1 km 셀의 클래스 (nearest). 1 km 블록 클래스 = 블록 안 16개 셀의 다수결
  (동수면 더 도시 쪽).

[1. 블록 구간 (두 가지, 둘 다 출력)]
- A (주): GHS-SMOD 클래스 -> urban (30), peri_urban (21-23 = urban cluster, urban centre 제외), rural (11-13). 물 (10)은 제외.
- B (확인): 같은 규칙을 우리 v5.7 밀도의 1 km 블록에 직접: urban centre = 밀도 >= 1,500 / km2 블록의 4-연결 (대각선 제외) 덩어리, 덩어리
  인구 >= 50,000, 덩어리 안 구멍 메우기; urban cluster = 밀도 >= 300 블록의 8-연결 (대각선 포함) 덩어리, 덩어리 인구 >= 5,000 (urban centre
  제외 나머지); 나머지 rural. 상자 경계에서 덩어리가 잘리지 않게 상자보다 사방 20 km 넓게 계산 후 잘라냄. 구멍 메우기는 매뉴얼 규칙을
  확인해서 구현하고 (확인 못 하면: 사방이 urban centre인 블록만 메움) 로그에 적은 규칙 출력. 가장자리 다듬기는 생략하고 로그에 명시.
- 기존 도시 상자 (Boston / Denver / Chicago)도 A / B 구간으로 다시 계산 (예전 100 / 1,000 결과 파일은 그대로 두고, 새 폴더).

[2. 상자 고르기 (결과 보기 전에 규칙 고정; 골라진 상자를 config에 기록하고 커밋)]
- 2010 카운티 (우리 2010 경계, 학습 status)마다 GHS-SMOD 2010의 카운티 안 셀 클래스 집계.
- rural 후보: 카운티 안에 urban cluster / urban centre 셀이 하나도 없는 카운티. peri_urban 후보: urban cluster 셀은 있고 urban centre 셀은
  없는 카운티.
- Census region 4개 (주 FIPS)마다, 종류별로 후보 중 2010 밀도가 중앙값인 카운티 하나 (짝수면 낮은 쪽, 동률이면 GISJOIN 작은 쪽) ->
  rural 4 + peri_urban 4 = 8개. 상자 = 그 카운티 중심점 (polygon centroid, ESRI:102039)에서 40 x 40 km, 우리 250 m 격자에 맞춤.
- 기존 도시 상자나 다른 새 상자와 중심 간 50 km 미만이면, 상자가 CONUS 밖으로 나가면 -> 그 region / 종류의 다음 후보 (중앙값에서 가까운 순).
- 확인용 출력 (로그 + boxes_selected.csv): 카운티, 주, 밀도, 후보 수, 상자 안 SMOD 클래스별 셀 비율, 상자 안 v5.7 인구 (1980 / 2010),
  마스크 밖 셀 비율.
- configs/external_grids.yaml에 rural_boxes: 블록 (규칙 + 골라진 8개 상자, box_type rural / peri_urban). 이후 실행은 이 값을 읽음 (다시
  고르지 않음).

[3. 계산 (external_city_density.py 재사용)]
- 상자: 새 8개 + 기존 도시 3개. 버전: v5.7 (주) + v5.7 + PLURAL pq5 (extra). 1980 (GHS-POP) / 2010 (GHS-POP, WorldPop).
- 구간 A와 B 각각: density_class_summary (상자 / 구간별 블록 수, Spearman, 총인구 비율, x4 비율 등), cell_type_shares (셀 종류별 인구 비율:
  BUI > 0 / BUI = 0 이고 NobuiltYear > 0 / 기록 없음; GHS-POP / WorldPop / v5.7 / pq5). 상자별 + box_type별 합 (city / peri_urban / rural).
- 총인구 비율은 구간 A, 구간 B, 상자 전체 (구간 없이) 세 가지를 로그 요약표에 나란히 (구간 기준 착시 확인용).
- 그림: 새 상자마다 미팅 지도 형식 한 장 (v5.7 | GHS-POP | WorldPop(2010), 같은 색 범위 / 축척막대 / 회색 마스크 / 고정 축 산점도) + 셀
  종류 막대 그림 (구간 A).
- 출력: results/validation/conus/external/degurba_boxes_v57/. 기존 city_density_classes_v57/는 건드리지 않음.

[공통]
- 로컬 테스트 (SMOD 클래스 -> 우리 셀 / 블록 다수결 손계산; B의 덩어리 규칙: 4- / 8-연결, 인구 문턱, 구멍 메우기, 넓힌 창 = 잘리지
  않음 손계산; 상자 고르기: 합성 카운티에서 후보 / 중앙값 / 짝수 / 동률 / 50 km / CONUS 밖 손계산; 기존 도시 상자 예전 결과 그대로),
  커밋, push.
- submit_conus.sh 모드 degurbaboxes (사전 확인: SMOD 파일 / 상자 config; 상자 고르기는 config가 없을 때만 첫 잡으로, 있으면 그대로 ->
  계산 잡; 한 번 제출). SMOD 다운로드는 러너북 26절 블록 0 (로그인 노드). 러너북 26절, docs/conus_plan.md 절 "DEGURBA boxes",
  CLAUDE.md, open_items 갱신.
- Alpine 명령: (0) SMOD 다운로드 (로그인 노드), (1) 사전 확인 + 제출, (2) 로그 + 결과 커밋. 블록 끝마다 성공 표시 한 줄.

[추가 2026-11-21, f5a1889 이후: 구간 B 구멍 메우기 / 가장자리 규칙 확인됨 -> 고쳐줘]
- 출처: R 패키지 flexurba (DEGURBA 매뉴얼 구현) DoU_classify_grid_urban_centres 기본값
  (https://www.rdocumentation.org/packages/flexurba/versions/0.2.3/topics/DoU_classify_grid_urban_centres).
- 구멍 메우기: urban centre 안에 완전히 둘러싸인 비-centre 블록 덩어리 중 면적 < 15 km2 (블록 15개 미만)를 그 centre에 넣음
  (max_gap = 15).
- 가장자리 다듬기: 주변 8개 블록 중 5개 이상이 같은 urban centre인 블록을 그 centre에 넣고, 더 이상 추가되지 않을 때까지 반복
  (majority rule).
- built-up 조건 (built share >= 20 / 50 %)은 쓰지 않음 (GHS-BUILT 없음) -> RULE B 로그에 생략했다고 명시.
- 순서: 덩어리 판정 (1,500 / 4-연결 / 50,000) -> 구멍 메우기 -> 다듬기. 테스트: 14개 블록 구멍은 메워지고 15개는 안 메워짐, 5/8 규칙 반복.
