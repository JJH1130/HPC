git pull 받고 아래를 해줘. 배경: BUPR_contemp.tif가 Dataverse BUPR.tar(v2)에 없음
(results/hisdac_uncertainty/BUPR.tar_members.txt; logs/hisdac_extra_download.txt). 위치는 Stefan에게 묻는 중.

[contemp 없이 진단을 돌릴 수 있게]
- record_uncertainty.py / submit_conus.sh uncertainty: BUPR_contemp.tif가 없으면 멈추지 말고, NobuiltYear.tif로 같은 비율을 계산:
  A' = NobuiltYear / (BUPR_2015 + NobuiltYear)  (contemp = 연도 있는 기록 + 연도 없는 기록 이라는 정의에서 나온 같은 비율;
  2015는 ZTRAX 수집 시점 ~2016에 가장 가까운 시계열). 2020도 같이 계산해서 2015와 차이를 로그로.
  B_year는 그대로. NobuiltYear가 0/1(개수가 아님)이면 A'와 B_year 둘 다 계산할 수 없으므로 그 사실과 값 분포만 기록하고
  끝내기 (실패 아님, exit 0).
- contemp가 나중에 생기면 원래 A도 같이 계산해서 A와 A' 비교 (셀 / 카운티 수준).
- 출력 열 이름에 어떤 정의인지 드러나게 (ratio_A_contemp / ratio_A_nby). threshold 표는 쓸 수 있는 정의마다.
- 로컬 테스트(contemp 없음 + NobuiltYear 개수 / 0/1 두 경우), docs/data_sources.md, Running_CONUS.md 11절, CLAUDE.md 갱신,
  커밋, push. Alpine 명령: 다운로드 다시 할 필요 없음 - 제출 블록 + 로그 커밋 블록만, 블록 끝마다 성공 표시 한 줄.
