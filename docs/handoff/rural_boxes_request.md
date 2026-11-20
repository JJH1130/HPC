git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "City boxes by density class: result". 지금 비교 상자 (Boston / Denver /
Chicago 40 x 40 km)의 "rural"은 대도시 외곽뿐임. 사용자: 진짜 시골에서도 봐야 함 (Stefan 11/17 4번: rural에서 GHS-POP / WorldPop과
얼마나 비슷하거나 다른지). -> 시골 상자 4개 + 근교 / 소도시 (peri-urban) 상자 4개를 고정 규칙으로 골라 같은 계산 (사용자 2026-11-21: peri-urban도).

[1. 상자 고르기 (결과 보기 전에 규칙 고정, 골라진 상자를 config에 기록하고 커밋)]
- 후보: 2010 카운티 (우리 2010 경계, 학습에 쓰는 status) 중 2010 인구 밀도 < 10 명 / km2.
- Census region 4개 (Northeast / Midwest / South / West; 주 FIPS로)마다, 후보 중 밀도가 중앙값인 카운티 하나 (짝수면 낮은 쪽; 같으면
  GISJOIN 작은 쪽). 상자 = 그 카운티 중심점 (polygon centroid, ESRI:102039)에서 40 x 40 km, 우리 250 m 격자에 맞춤 (기존 상자와 같은
  방식).
- peri-urban 상자 (같은 방식, 별도 4개): 후보 = 2010 밀도 20 - 100 명 / km2 카운티, 그리고 그 중심점에서 기존 도시 상자
  (Boston / Denver / Chicago)와 다른 상자까지 50 km 이상. region마다 밀도 중앙값 카운티 하나. 상자 종류 열 box_type = rural /
  peri_urban.
- 확인용 출력 (로그 + rural_boxes.csv): 고른 카운티, 주, 밀도, 후보 수, 상자 안 v5.7 인구 (1980 / 2010), 상자 안 마스크 밖 셀 비율,
  상자 안에 인구 1만 이상 place가 있는지 (PLURAL place 자료가 있으면; 없으면 생략하고 로그). 상자가 CONUS 밖으로 나가면 그 region의
  다음 순위 카운티 (중앙값에서 가까운 순).
- configs/external_grids.yaml에 rural_boxes: 블록 (선택 규칙 + 골라진 8개 상자, box_type). 이 블록은 선택 스크립트가 만들고, 이후 실행은 그
  고정 값을 읽음 (다시 고르지 않음).

[2. 같은 계산 (external_city_density.py 재사용)]
- 버전: v5.7 (주) + v5.7 + PLURAL pq5 (extra), 1980 (GHS-POP) / 2010 (GHS-POP, WorldPop). 기존 도시 상자 결과는 건드리지 않음.
- 구간: 같은 경계 (GHS-POP 블록 밀도 rural < 100, peri-urban 100 - 1,000, urban >= 1,000). 시골 상자는 대부분 rural이 될 것.
- 표: density_class_summary.csv (상자 / 구간별 Spearman, 총인구 비율, x4 비율 등), cell_type_shares.csv (셀 종류별 인구 비율: BUI > 0 /
  BUI = 0 이고 NobuiltYear > 0 / 기록 없음; GHS-POP / WorldPop / v5.7 / pq5), 상자 전체 + 구간별 + box_type별 4개 상자 합.
- 구간 기준 착시 주의 (도시 상자 결과의 교훈): 총인구 비율은 (a) GHS-POP 밀도로 구간, (b) 우리 밀도로 구간 둘 다 쓰고, 상자 전체
  총인구 비율 (우리 / GHS-POP, 구간 없이)도 같이. 로그 요약표에 세 가지 나란히.
- 그림: 상자마다 지도 한 장 (v5.7 | GHS-POP | WorldPop(2010), 기존 미팅 지도와 같은 색 범위 / 축척막대 / 회색 마스크) + 셀 종류 막대
  그림. 미팅 지도 코드 재사용 (city_maps_meeting 형식, 산점도 포함; 고정 축 0.01 - 30,000).
- 출력: results/validation/conus/external/rural_boxes_v57/.

[공통]
- 로컬 테스트 (선택 규칙: 합성 카운티 표에서 region별 중앙값 / 짝수 / 동률 / CONUS 밖 처리 손계산; 고정 상자 읽기; 기존 도시 상자 결과
  그대로), 커밋, push.
- submit_conus.sh 모드 ruralboxes (선택은 사전 확인에서 로그인 노드로 또는 첫 잡으로 -> 계산 잡; 한 번 제출). 러너북 26절,
  docs/conus_plan.md 절 "Rural boxes", CLAUDE.md, open_items 갱신. docs/data_sources.md는 새 데이터가 없으면 그대로.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 로그 + 결과 커밋. 블록 끝마다 성공 표시 한 줄.
