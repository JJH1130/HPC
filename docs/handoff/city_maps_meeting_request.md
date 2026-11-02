git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "External comparison with v5.6: result". Stefan 미팅용 그림. 이번 미팅에서는 F&J를 빼고
GHS-POP / WorldPop만 보여줌 (메시지: 블록 단위 입력이라 tract 검증은 공정하지 않음 -> 대신 공간 패턴 일치도). 새 데이터 없음, 기존
external_city_maps.py 재사용 (같은 상자, 같은 재격자, 같은 마스크, 같은 1 km Spearman 정의). 기존 city_maps/ 결과는 그대로 둠.

[그림: 도시당 한 장, 2010, 3개 도시]
- 도시: Boston MA, Denver CO, Chicago IL (기존 40 x 40 km 상자 그대로).
- 위 줄 지도 3개: v5.6 | GHS-POP | WorldPop (같은 log 색 범위, 마스크 밖 회색, 10 km 축척막대). F&J 패널 없음.
- 아래 줄 산점도 2개: 1 km 블록 (4 x 4 셀, 마스크 안 블록만 = Spearman과 같은 블록) 인구 밀도, x = v5.6, y = GHS-POP / WorldPop,
  둘 다 log 축 (명 / km2; 0인 블록은 축 아래 띠에 따로 표시 + 개수), 1:1 선, 제목에 Spearman rho와 블록 수.
- Chicago만 추가: 지도 위에 "v5.6이 GHS보다 크게 낮은 1 km 블록" 테두리 표시 (기준 고정: v5.6 / GHS < 0.25, GHS >= 1,000명 / km2).
  그 블록들의 HISDAC 상태를 CSV로: 블록 수, GHS 인구 합, 그 블록 안 BUI > 0 셀 비율, NobuiltYear > 0 셀 비율 (cutout에 NobuiltYear
  레이어가 없으면 HISDAC 원본 NobuiltYear.tif를 같은 격자로 읽어 셈; 원본도 없으면 그 열만 NA + 로그).
  -> "v5.6이 비운 곳 = HISDAC 기록이 없는 곳인가 / 연도 없는 기록은 있는가"를 숫자로.
- 그림 위쪽 한 줄 설명: "Spearman of 1 km block densities (rank agreement, not accuracy); GHS-POP / WorldPop use block-level census
  input in the US".
- 출력: results/validation/conus/external/city_maps_meeting/{boston,denver,chicago}_2010.png + meeting_summary.csv (도시 x 제품:
  rho, 블록 수, 상자 안 총인구) + chicago_gap_blocks.csv.

[공통]
- 로컬 테스트 (산점도 블록 = Spearman 블록, gap 블록 기준 손계산, NobuiltYear 비율 손계산), 커밋, push.
- submit_conus.sh 모드 citymeeting (잡 하나), 러너북 18절, docs/conus_plan.md 한 줄, CLAUDE.md 갱신.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋. 블록 끝마다 성공 표시 한 줄.
