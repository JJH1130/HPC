git pull 받고 아래를 해줘. 배경: docs/open_items.md "Meeting with Stefan, 2026-11-17" 2번 / 4번 (1번 nby_age는 끝남: v5.7 유지).
기준 버전 = v5.7 (Dasy_CONUS_RF_v3_all_nby, nby, 필터 없음). 보고 규칙 (open_items): 카운티 지표는 항상 모든 TEST 카운티; kept /
excluded t070은 옆에 라벨. 이번에 돌리는 건 A만. B는 코드 + 테스트만 하고 제출하지 않음 (A 결과로 버전을 정한 뒤 그 버전으로 돌림).
SHAP 그림 (3번)은 이미 git에 있는 shap_values.csv로 Claude가 로컬에서 그림 -> 이번 요청에 없음.

[A. PLURAL을 v5.7 위에서 다시 (제출)]
- Stefan 의견: PLURAL은 기록이 없는 곳에 인구를 뿌리는 효과를 완화하고 과다 배분도 줄이는 보상 효과가 있을 수 있고, NobuiltYear가
  들어간 모델에서는 더 잘 작동할 수 있음. v5.6 위에서 한 테스트 (docs/conus_plan.md "PLURAL grid test")와 같은 6개 변형, v5.7 위에서.
- configs/conus_rf_v3_all_nby_{plc,plcc,pq3,pq5,pe3,pe5}.yaml (version Dasy_CONUS_RF_v3_all_nby_<variant>): v5.7과 같은 split / fold /
  statuses / water mask / strips / 탐색 공간 / n_iter 60, exclude_counties 없음; 각 era = v5.7의 그 해 era + plural; plural 블록 =
  conus_rf_v3_u070_<variant>.yaml과 같음 (layer PLURAL / PLURALC, classes, breaks). 연도 1940 / 1980 / 2010 (PLURAL 격자가 있는 해).
  compare_with Dasy_CONUS_RF_v3_all_nby. cutout 레이어 PLURAL / PLURALC는 이미 있음 (다시 만들지 않음; 사전 확인에서 존재만 확인).
- 사전 확인: 같은 연도의 plural_breaks.csv가 v5.6 테스트의 것과 같아야 함 (같은 cutout, 같은 연구 셀이면 같음; 다르면 멈춤).
- features / train / predict / tract validate (gap 카운티 = v5.6의 것, --gap-version, 이전과 같게), 6개 변형 병렬.
- 비교 (plural_compare.py 재사용 또는 같은 정의, 기준을 v5.7로): v5.7 + 6개 변형 (+ 참고 열: v5.6과 v5.6 + 6개 변형, 기존 결과에서;
  재계산하면 같아야 함).
  - 카운티: TEST R2 / MdAPE / MAPE (모든 TEST 카운티 주 열, kept / excluded t070 라벨), county CV RMSE (v5.7과 같은 CV 집합 -> 직접
    비교 가능).
  - tract MdAPE: all, kept / excluded t070, gap / no-gap, 밀도 4묶음.
  - BUI = 0 셀 인구 비율 / 그중 NobuiltYear > 0 셀 비율 (Stefan의 보상 효과 질문: 빈 셀 배분이 늘어나는지 줄어드는지), plural / nby
    permutation + SHAP 순위.
  - 선택 규칙 (결과 보기 전에 고정): 변형마다 county CV RMSE가 v5.7보다 낮은 연도 수 + 평균 변화. tract로 고르지 않음 (v5.6 테스트의
    "best classed variant" tract 규칙은 지도 표시용이었고 이번에는 쓰지 않음). 결정은 사용자.
  - 출력: results/validation/conus/plural_grid_v57/ (comparison CSV + cells / ranks / cv_rule CSV), 로그에 요약표. 그림 없음.
- submit_conus.sh 모드 v57plural (사전 확인 -> 6개 변형 features / train / predict / validate 병렬 -> 비교, 한 번 제출). 러너북 23절.

[B. 도시 상자를 밀도 구간으로 나눠 GHS-POP / WorldPop과 비교 (코드 + 테스트만, 제출 안 함)]
- Stefan: 지금은 Boston / Denver / Chicago 40 x 40 km 상자 전체로만 비교함 -> rural / peri-urban / urban으로 나눠서, 특히 rural에서
  얼마나 비슷하거나 다른지 보고 싶음.
- external_city_meeting.py와 같은 상자 / 재격자 / 마스크 / 1 km 블록 (= Spearman 블록), 1980 (GHS-POP) / 2010 (GHS-POP, WorldPop).
- 구간 (결과 보기 전에 고정): 1 km 블록의 GHS-POP 밀도 (그해) 기준 rural < 100, peri-urban 100 - 1,000, urban >= 1,000 명 / km2
  (주 분류). 확인용: 같은 경계를 우리 버전의 밀도로 나눈 분류도 같이 (제품 기준으로만 나누면 그 제품 쪽으로 치우칠 수 있어서).
  WorldPop 비교도 GHS-POP 기준 구간을 씀 (같은 블록 집합; 1980은 GHS-POP만).
- 구간마다 (도시 x 연도 x 제품): 블록 수, Spearman, 총인구 (우리 / 제품, 비율), 블록별 우리 / 제품 비율의 중앙값 + 10 / 90 분위,
  우리 0인 블록 수 / 제품 0인 블록 수, |log10 비율| > log10(4)인 블록 비율 (위 / 아래 따로).
- 그림: 도시 x 연도마다 한 장, 구간별 산점도 3개 (기존 미팅 산점도와 같은 고정 축 0.01 - 30,000, 1:1 선 + x4 / ÷4 보조선) + 구간 지도
  (블록을 구간 색으로) 한 개. 기존 미팅 그림 폴더는 건드리지 않음.
- --version / --version-label (기본 v5.7), 출력 results/validation/conus/external/city_density_classes_<label>/
  (density_class_summary.csv + PNG). 전체 상자 값 (구간 합친 Spearman / 총인구)은 기존 meeting_summary_v56_v57.csv와 같아야 함 (다르면 멈춤).
- 테스트: 합성 도시로 구간 나누기 / 지표 손계산 / 경계값 블록 처리 (100, 1,000은 위 구간) / 전체 = 기존 값. sbatch/external_city_density.sh +
  submit_conus.sh 모드 citydensity (버전 인자) 준비, 러너북 24절에 블록만 써 둠 (실행은 나중).

[공통]
- 로컬 테스트, 커밋, push. docs/conus_plan.md 절 "PLURAL on v5.7" / "City boxes by density class", CLAUDE.md, open_items 갱신.
- Alpine 명령 (A만): (1) 사전 확인 + 제출, (2) 진행 확인, (3) 로그 + 결과 커밋 + sacct / seff. 블록 끝마다 성공 표시 한 줄.
