git pull 받고 v4.1(PLURAL-1 거리 지표 5개)을 구현한 뒤, 내가 Alpine에 붙여넣을 실행 명령까지 줘.
20분 안에 잡을 제출하고 자리를 비울 거라, 체인 하나로 끝까지 돌게 해줘.

[결정 사항 - docs/open_items.md 결정 기록에도 남겨줘]
- 2026-10-23 Stefan 미팅: (1) PLURAL-1의 거리 지표 5개만 셀 단위로 새로 계산해 피처로 쓰는 방식 승인.
  place 인구 규모, focal population density 두 지표는 누출 때문에 제외. (2) 인구 자료는 일단 Stefan CSV
  (2010 경계, 1900-)로 가고 나중에 필요하면 고친다. MA 실험은 지금처럼 NHGIS 그해 경계로 계속하고,
  CSV 전환은 마지막 단계(2026-10-20 결정 유지).

[v4.1 설계 - docs/dasymetric_v4_1.md로 문서화]
- v4.1 = v3.4 피처 + 연도별 GDW 물 마스크(water_mask: yearly, v4와 같음) + 거리 피처 5개.
  지형(elev, slope)은 넣지 않음(v4에서 MA 과적합, CONUS에서 재시험). compare_with: v3_4, folds_from: v2.
- 거리 피처는 E23(1940-2020)에만 추가. E1(1810-1930)은 v3.4 그대로(PLURAL이 1930부터라 E1 대부분 없음).
- 피처 이름: d_10k, d_20k, d_50k, d_100k, d_250k (km). 등급: [1만,2만), [2만,5만), [5만,10만),
  [10만,25만), 25만 이상. 각 셀 중심에서 그해 그 등급 place 중 가장 가까운 것까지의 직선거리.
  카운티 값은 다른 피처처럼 셀 평균. SHAP 그룹은 "Place distance" 하나로 묶어도 됨(summary plot은 피처별).
- 입력 (Alpine):
  /projects/jaju1407/data/raw/plural/plural_2023/PLURAL_CSV/PLURAL_CSV/place_level_remoteness_all_scaled_across_years.csv
    -> placeid, place_name, state_name, placepop_{1930..2010, 2018} (0 = 그해 기록 없음). 좌표 없음.
  /projects/jaju1407/data/raw/plural/plural_2023/PLURAL_SHP/PLURAL_SHP/plural_indices_scaled_across_years_{YEAR}.shp
    -> 포인트, 필드 placeid, placepop 등, CRS ESRI:102003. 연도별 파일을 합쳐 placeid당 위치 하나로.
  미국 전체 place를 써야 함(가장 가까운 큰 도시가 창 밖에 있을 수 있음). cutout CRS로 재투영.
- 연도 매칭: 1940-2010은 같은 해, 2020은 2018 사용.
- 뉴잉글랜드 town 누락 보정: place 인구가 Y년에 0인데 Y-10, Y+10년에 둘 다 >0이면 두 값의 평균으로 채움
  (1930과 2018은 안 채움). MA에서 1950, 1970년에 Brookline, Arlington, Framingham 등이 빠지는 문제
  (MA 1만 이상 place: 1930 39, 1940 78, 1950 47, 1960 75, 1970 48, 1980 78). 채운 건수를 주, 연도별로
  로그에 남기고, 보정 후 MA 1만 이상 place 수가 연도별로 매끄러워졌는지 로그로 보여줘.
  Millbury 1940 = Milford와 같은 15,388(매칭 오류 의심)은 그대로 두고 문서에 한계로 적기.
- 구현 위치 제안: src/grid/place_dist.py (water_frac.py처럼 window.json 읽고
  layers/PLACEDIST/<name>/{YEAR}_<name>.tif float32로 씀, qa/place_dist_qa.csv),
  configs/study_area.yaml에 place_dist: 블록(csv, shp 경로, fill_gaps, first_year),
  common.py에 d_* 피처 추가(LAYER_FEATURES에 "PLACEDIST/d_10k" 식으로 매핑하면 layer_path 그대로 씀),
  sbatch/place_dist.sh, configs/model.yaml을 v4_1로. 거리는 scipy cKDTree로 행 블록 단위 계산
  (창 1711x2842 셀, 9개 연도 x 5등급).
- 로컬에서 합성 데이터로 거리 계산과 gap fill을 시험하고, 로그에서 확인할 기대값도 러너북에 적어줘
  (예: Boston 셀 d_250k 약 0 km, Berkshire 셀 d_250k 큼).

[실행 - docs/runbooks/Running_Dasymetric.md에 "v4.1" 섹션]
사전 확인 + 체인: place_dist -> features -> train -> predict -> validate_tract --version v4_1
(cutout, DEM, water_frac은 v4에서 이미 만들어져 있음. scratch 90일 퍼지 전이라 그대로 씀).
로그 커밋 명령까지 포함. 실패하면 뒤 잡은 DependencyNeverSatisfied로 남으니 scancel 안내도.
다 끝나면 나중에 결과를 v3_4와 비교(카운티 CV, tract MdAPE, R2, d_* SHAP)해서 문서에 기록.
