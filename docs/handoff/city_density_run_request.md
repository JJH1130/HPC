git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "PLURAL on v5.7: result" + "City boxes by density class" (part B 코드, 아직 안 돌림).
PLURAL을 넣으면 county CV는 좋아지는데 tract는 나빠지고, 늘어난 인구는 대부분 BUI = 0이면서 HISDAC 기록도 없는 셀로 감. 사용자:
기록이 전혀 없는 셀에도 실제 건물 / 사람이 있을 수 있음 (그것도 불확실성). -> 블록 단위 센서스 입력을 쓰는 GHS-POP / WorldPop을
참고선으로, 도시 상자에서 그런 셀에 사람이 실제로 얼마나 사는지 세기. Stefan 4번 (rural / peri-urban / urban)과 같은 잡.

[1. external_city_density.py 확장]
- 버전 두 개를 같은 실행에서: v5.7 (Dasy_CONUS_RF_v3_all_nby, label v5.7)과 v5.7 + PLURAL pq5 (Dasy_CONUS_RF_v3_all_nby_pq5, label
  v5.7_pq5; county CV가 가장 좋았던 변형). pq5는 1980 / 2010만 (PLURAL 연도 중 GHS가 있는 해). v5.7 상자 전체 값은 지금처럼
  meeting_summary_v56_v57.csv와 같아야 함 (다르면 멈춤); pq5는 대조할 이전 값이 없으니 그 확인 없이 (로그에 명시).
- 새 표: 셀 종류별 인구 비율. 상자의 250 m 셀을 세 종류로: (a) BUI_year > 0, (b) BUI = 0 이고 NobuiltYear > 0 (연도 없는 기록만),
  (c) BUI = 0 이고 NobuiltYear = 0 (기록 없음). 종류마다 셀 수와, 그 셀들에 간 인구가 상자 인구에서 차지하는 비율을 GHS-POP / WorldPop
  (2010) / v5.7 / v5.7_pq5 각각. 상자 전체 + 밀도 구간별 (GHS-POP 블록 기준 rural / peri_urban / urban; 셀은 속한 1 km 블록의 구간).
  NobuiltYear는 external_city_meeting.py와 같은 소스 (cutout NOBUILT 또는 $HISDAC_DIR/FBUY/NobuiltYear.tif, 같은 격자 읽기).
  -> cell_type_shares.csv (city, year, class, cell_type, n_cells, then share_<product> 열).
- 기존 구간 표 (density_class_summary.csv)는 두 버전 모두 (version 열). 그림: 기존 구간 그림은 v5.7만 (지금 그대로) + 도시 x 연도마다
  셀 종류 막대 그림 하나 (x = 제품, 막대 = 세 종류 비율, 패널 = 구간; 같은 축).
- 출력 results/validation/conus/external/city_density_classes_v57/ (pq5 행 포함).

[공통]
- 로컬 테스트 (합성 도시: 세 종류 분류 / 비율 손계산 / 합 = 1 / 구간별 합 = 전체; pq5 대조 생략 경로), 커밋, push. 러너북 24절 블록 갱신
  (citydensity 모드, 두 버전), docs/conus_plan.md, CLAUDE.md, open_items 갱신.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 로그 + 결과 커밋. 블록 끝마다 성공 표시 한 줄.
