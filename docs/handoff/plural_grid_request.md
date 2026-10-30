git pull 받고 아래를 해줘. 배경: docs/open_items.md "Meeting with Stefan, 2026-10-28" 3번 (PLURAL 900 m 격자를 250 m로 리샘플해서
피처로 시험; 연속형 / 범주형, 클래스 수와 경계는 민감도), docs/conus_plan.md "Version summary" (v5.6 = Dasy_CONUS_RF_v3_u070 채택).
PLURAL이 유의하면 1900-2020 값을 만들어 전체 연도를 돌릴 예정이고, 아니면 v5.6 전체 연도로 감. 이번엔 세 해만.

[1. 데이터]
- 입력: /projects/jaju1407/data/raw/plural/siqiao_2026/PLURAL_grid_data/index3_{1940,1980,2010}_900_US.tif
  (docs/data_sources.md "PLURAL": 900 m, float32 0-1, nodata 없음, LAEA 45N 100W, 1 = 외진 곳, 0 = 도시이면서 미국 밖 채움값도 0).
- docs/data_sources.md의 이 행 Use를 "feature test (v5.6 + plural, 1940 / 1980 / 2010)"로 갱신하고, index3가 무엇인지(PLURAL-1 / -2,
  인구 가중 여부) 아직 모른다는 점, 그리고 인구를 써서 만든 지수라면 같은 해 인구 정보가 피처로 들어가는 셈이라는 주의를 적어 둘 것.
- 컷아웃 레이어 PLURAL (years [1940, 1980, 2010]) 추가: HISDAC 250 m 격자에 맞춰 리샘플.
  - 두 가지: bilinear(주), cubic(민감도). cubic은 0-1 밖으로 나갈 수 있으니 [0, 1]로 자르고 잘린 셀 수 기록.
  - 미국 밖 0(채움값)이 해안 / 국경 셀에 섞여 들어가는지 확인: 경계 5 km 안 셀의 값 분포를 내륙과 비교해 로그.
    많이 섞이면 해안 / 국경 셀은 nearest로 처리하는 등 방법을 제안(내가 정함).
  - QA: 몇 개 도시 / 외진 곳 점(뉴욕, 보스턴, 덴버, Ely NV 등)에서 900 m 원본과 250 m 값 비교.

[2. 기준 모델]
- v5.6 = Dasy_CONUS_RF_v3_u070 (0.7 필터 + 고정 규칙, 같은 제외 카운티)을 1940, 1980에도 돌림 (2010은 이미 있음).
  y2020 때처럼 같은 버전에 연도만 추가 (--years 1940 1980), 기존 연도 결과는 바뀌면 안 됨.

[3. PLURAL 변형 (각각 v5.6 피처 + plural 하나, 같은 split / fold / 제외 카운티 / 탐색 공간 / n_iter 60)]
- 연속형: Dasy_CONUS_RF_v3_u070_plc (bilinear), _plcc (cubic)
- 범주형 (bilinear 값 기준, 클래스 번호를 정수 피처로): 클래스 수 3 / 5, 경계는 분위수(그해 CONUS 연구 셀 기준) / 등간격(0-1) ->
  _pq3, _pq5, _pe3, _pe5. 셀 피처 = 클래스 번호, 카운티 피처 = 셀 평균(지금 다른 피처와 같은 방식).
- 연도: 1940, 1980, 2010.

[4. 평가 - 모두 v5.6과 같은 tract / 카운티에서]
- tract MdAPE, MAPE(10명 이상): 전체, 0.7 기준 남은 / 빠진 카운티, gap / no-gap, 밀도 4묶음, 면적 비례 기준선.
- 카운티: TEST MdAPE (배분 전), CV / TEST R2.
- 피처 순위: plural의 permutation / SHAP 순위와 값 (--rank-features plural).
- 지도: 2010, 같은 4개 카운티(Chelan WA, Reno KS, Fremont CO, Macoupin IL)로 v5.6 vs 연속형 / 가장 나은 범주형, BUI = 0 셀에 놓인 인구 비율
  (PLURAL 거리 / 야간광 때처럼 빈 땅으로 퍼뜨리는지 확인).
- 출력: results/validation/conus/plural_grid/plural_comparison.csv + 그림 하나(연도 x 변형 tract MdAPE, v5.6 기준선).

[공통]
- 로컬 테스트(리샘플 = 정렬 확인, cubic 자르기, 클래스 경계, 연도 추가 시 기존 행 보존), 커밋, push.
- docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신. submit_conus.sh에 plural 모드.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 커밋 + seff. 블록 끝마다 성공 표시 한 줄.
