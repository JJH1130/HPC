git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "External comparison result" (v5.4 기준이었음). 지금 가장 나은 버전 = v5.6
(Dasy_CONUS_RF_v3_u070, 1900-2020; 최종 확정은 아님). 교수님(Stefan)이 GHS 비교를 원함. GHS-POP / WorldPop은 미국에서 블록 단위
센서스를 입력으로 써서 tract 비교가 공정하지 않음 (2010 MdAPE 약 1 %) -> (1) 수치는 "입력이 더 세밀한 참고선"으로 명시해서 보여주고,
(2) Noi et al. 초안처럼 도시 지도를 나란히 비교. 새 데이터 다운로드 없음 (이미 받은 GHS-POP / WorldPop / F&J 사용).

[1. 외부 비교 수치를 v5.6으로]
- configs/external_grids.yaml: reference를 Dasy_CONUS_RF_v3_u070 (label "v5.6 (Dasy_CONUS_RF_v3_u070)")으로. v5.4도 같은 표에 한 열로
  남김 (두 버전 다 tract_errors_{YEAR}.csv가 git에 있음). extract(외부 격자 tract 합계)는 다시 하지 않고 scratch의 합계 재사용;
  없으면 사전 확인에서 멈추고 알려줄 것.
- 지표: tract MdAPE + MAPE (10명 이상) 둘 다 (Noi et al.은 MAPE를 씀). 각 제품이 덮는 tract에서 제품 / v5.6 / v5.4 / 면적 비례 기준선.
- 표에 열 하나 추가: input_unit_class = block (GHS-POP, WorldPop, GPW) / county (F&J) / county (v5.6, v5.4). 그림에서도 block 입력
  제품은 점선 + 범례에 "finer input (blocks): reference, not a competitor".
- 출력: results/validation/conus/external/external_comparison_v56.csv + external_mdape_by_year_v56.png (기존 v5.4 파일은 그대로 둠).

[2. 도시 지도 비교 (정성적, Noi et al. Figure 10 방식)]
- 도시: Denver CO, Salt Lake City UT (Noi와 같음) + Chicago IL, Boston MA. 각 도시 중심에서 40 km x 40 km 상자 (LAEA / 우리 격자).
- 연도: 1980, 2010 (GHS-POP 있는 해). 패널: v5.6 | GHS-POP | Fang & Jawitz M5 (2010엔 + WorldPop).
- 모두 우리 250 m 격자로: 100 m GHS / WorldPop은 면적 가중 합(인구 보존), 1 km F&J는 면적 비례로 나눔. 단위 = 명 / km2, 같은
  log 색 범위 (도시 x 연도마다 공통), 우리 마스크 밖(물, 카운티 없음)은 회색 (0으로 두지 않음).
- 지도마다 수치 몇 개 (그림 제목 아래 + CSV): 상자 안 총인구 (각 제품), 1 km로 모은 셀 log 밀도의 Spearman (v5.6 vs 각 제품),
  BUI = 0 셀 인구 비율 (v5.6). "일치도이지 정확도가 아님"을 CSV / 문서에 명시.
- 출력: results/validation/conus/external/city_maps/{city}_{year}.png + city_maps_summary.csv.

[공통]
- 로컬 테스트 (재집계 인구 보존, 1 km 합 = 손계산, 마스크 회색 처리, MAPE 손계산), 커밋, push.
- submit_conus.sh 모드 externalv56 (evaluate 잡 + 지도 잡), 러너북 17절, docs/conus_plan.md 절 "External comparison with v5.6",
  CLAUDE.md, open_items 갱신.
- Alpine 명령: (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
