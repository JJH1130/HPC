git pull 받고 아래를 해줘. 배경: 미팅용 도시 지도 (docs/handoff/city_maps_meeting_request.md, results/validation/conus/external/city_maps_meeting/)를
사용자가 보고 지적한 표시 문제 수정. 숫자 / 블록 / 재격자는 바꾸지 않음 (rho, 총인구, gap 블록 표는 그대로 나와야 함; 실행 중 대조).
이번 미팅에는 F&J를 보여주지 않음.

[1. 미팅 그림 (external_city_meeting.py) 표시 수정]
- 축척막대: 지금은 검은 막대 + 글자가 진한 파란 지도 위에 묻혀 안 보임 -> 흰 반투명 상자 위에 검은 막대 + "10 km", 왼쪽 아래
  모서리, 세 지도 모두에. (또는 지도 밖 아래 여백에 그려도 됨; 보이기만 하면 됨.)
- 지도 3개 간격 맞추기: 지금 v5.6 패널과 GHS 패널 사이만 넓음 -> 세 패널 같은 간격, 같은 크기.
- 산점도 축 눈금: log 축 아래쪽 눈금이 전부 "0"으로 찍힘 (0.01, 0.1 등이 정수 포맷) -> 0.01 / 0.1 / 1 / 10 ... 으로. 0인 블록 띠의
  라벨은 "0 (n blocks)" 하나만 (x축의 "0 (0)" + 별도 "0" 눈금 중복 제거; 0 블록이 없으면 띠 자체를 그리지 않음).
- Chicago 숫자 패널: "cells NobuiltYear > 0 94.9 %"는 gap / 나머지 고밀도 블록 차이를 못 보여줌 (95 % vs 96 %) -> 두 그룹을
  나란히: "BUI > 0: 57 % vs 91 %", "BUI = 0 but NobuiltYear > 0 (undated records only): 39 % vs 6 %", "no record: 4 % vs 3 %"
  (gap vs dense non-gap; 값은 chicago_gap_blocks.csv에서).
- 범례 / 설명 한 줄 유지: "grey = outside our mask (water, no county); white = 0 people".

[2. 1980 미팅 그림 추가 (GHS-POP만, WorldPop은 1980 없음)]
- 같은 세 도시, 1980: 위 줄 지도 2개 (v5.6 | GHS-POP), 아래 산점도 1개 (GHS). 같은 수정 사항 적용. 파일 {city}_1980.png.
  meeting_summary.csv에 1980 행 추가.

[3. 예전 city_maps/ (F&J 포함, 0명 셀 회색 버그) 정리]
- 폴더 이름을 results/validation/conus/external/city_maps_internal_with_fj/ 로 바꾸고 (git mv), 그 안에 README.txt 한 줄:
  "internal check, not for the meeting; PNGs drawn before the display fix 6d9e3b0 (0-people cells grey)". 다시 그리지는 않음.
  config / 코드 / 러너북 / docs의 경로도 같이 고침.

[공통]
- 로컬 테스트 갱신 (눈금 라벨 문자열, 0 블록 없을 때 띠 없음, 1980 패널 수, Chicago 패널 문자열이 CSV 값과 같음), 커밋, push.
- 러너북 18절에 재실행 블록 (같은 citymeeting 모드), docs/conus_plan.md 한 줄, CLAUDE.md 경로 갱신.
- Alpine 명령: (1) 제출, (2) 로그 + 결과 커밋. 블록 끝마다 성공 표시 한 줄.
