git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "DEGURBA boxes: result". 시골 상자에서 v5.7이 HISDAC상 건물 없는 셀
(BUI = 0)에 주는 인구 비율이 GHS-POP과 같음 (2010 20 % vs 20 %). 하지만 같은 비율이 같은 셀이라는 뜻은 아님 (사용자). -> 같은 셀에
줬는지 250 m 셀 단위로 확인. 새 데이터 / 새 상자 없음: degurba_boxes.py의 같은 11개 상자 (rural 4, peri_urban 4, city 3), 같은 셀 값
(제품은 이미 우리 250 m 셀로 옮긴 값, 마스크 / BUI / NobuiltYear 읽기 그대로).

[1. 계산 (degurba_boxes.py에 overlap 단계 추가 또는 같은 모듈의 새 명령)]
- 셀 그룹: unbuilt = BUI_year = 0 (전체), 그 안을 undated (NobuiltYear > 0) / no_record (= 0)로 나눈 것, 그리고 비교 기준으로 built
  (BUI_year > 0). 마스크 밖 / 물 제외, 구간 A / B 계산에서 쓴 블록 규칙 (마스크에 걸친 블록 제외 등)과 같게.
- 쌍: (v5.7, GHS-POP), (pq5, GHS-POP), (v5.7, WorldPop), (pq5, WorldPop), 그리고 참고선 (GHS-POP, WorldPop) = 두 제품끼리의 일치
  (2010만). 연도 1980 (GHS-POP만) / 2010.
- 상자마다, 그리고 box_type별 합 (rural / peri_urban / city)으로, 셀 그룹마다:
  - 겹침 (분포): 그 그룹 셀들에서 각 지도의 인구를 그 그룹 합으로 나눈 비율 a_i, b_i -> overlap = sum_i min(a_i, b_i) (0 - 1; 1 = 같은 셀에
    같은 비율). box_type 합은 셀을 다 모아서 다시 계산 (상자 평균 아님).
  - 겹침 (양): sum_i min(x_i, y_i) / sum_i y_i (y = 제품 인구): 제품이 그 그룹에 둔 사람 중 우리도 같은 셀에 둔 비율.
  - 무작위 기준선: 그 그룹 인구를 그룹 셀에 고르게 펼친 지도와 제품의 overlap (분포) -> 우리 값이 이것보다 얼마나 높은지.
  - Spearman: 그 그룹의 250 m 셀 (둘 다 0인 셀 포함 / 제외 두 가지).
  - 셀 수, 양쪽 0이 아닌 셀 수, 그룹 인구 (양쪽).
- 같은 계산을 구간 A의 rural 블록만으로도 (city 상자 안의 시골 블록 = 대도시 외곽 확인용).

[2. 출력 / 확인]
- results/validation/conus/external/degurba_boxes_v57/unbuilt_overlap.csv + 로그 요약표 (box_type x 연도 x 셀 그룹 x 쌍: overlap 분포 /
  양 / 무작위 기준선 / Spearman).
- 확인: 각 그룹 인구 합이 cell_type_shares.csv의 같은 값과 같아야 함 (다르면 멈춤). overlap(분포)는 0 - 1, 지도와 자기 자신 = 1 (테스트).
- 그림 하나 (선택): box_type별 막대, 쌍마다 overlap (분포), 무작위 기준선 점선.

[공통]
- 로컬 테스트 (합성 상자: overlap 분포 / 양 / 무작위 기준선 / Spearman 손계산, 자기 자신 = 1, 겹치지 않는 두 지도 = 0, 그룹 합 =
  cell_type_shares), 커밋, push.
- submit_conus.sh 모드 unbuiltoverlap (잡 하나; 상자는 config 고정 값 그대로, 다시 고르지 않음). 러너북 27절, docs/conus_plan.md 절
  "Unbuilt-cell overlap", CLAUDE.md, open_items 갱신.
- Alpine 명령: (1) 제출, (2) 로그 + 결과 커밋. 블록 끝마다 성공 표시 한 줄.
