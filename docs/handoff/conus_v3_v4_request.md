git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "Pilot result" (v1 vs v2), docs/open_items.md.

[A. BUI 이상치 점검 - 먼저, 결과만 보고 처리는 아직 하지 않음]
- pilot 컷아웃에서 BUI 최댓값이 셀 하나에 306,635,538 (1920), 709,978,539 (1960), 5,447,140,510 (2010).
  250 m 셀 = 62,500 m2. 극단적 고층(바닥면적 / 땅면적 약 20배)도 셀당 약 1.25e6 m2 (약 1.35e7 sq ft)가 상한이라,
  단위가 sq ft든 m2든 불가능한 값으로 보임.
- 할 일: (1) HISDAC-US README / 메타데이터에서 BUI 단위와 정의 확인해서 docs/data_sources.md에 기록.
  (2) 연도별(1920/1960/2010)로 BUI 분포: 분위수(p50, p99, p99.9, p99.99, max), 상한 후보(예: 1e7, 3e7, 1e8)를 넘는 셀 수,
  상위 50개 셀의 좌표(lon/lat), 카운티, 주, BUI, BUPL, BUPR 값을 CSV로 results/cutout/conus/에 남김.
  같은 셀의 bldg_size(BUI/BUPL)도 같이.
  (3) 상위 셀이 대도시 도심에 몰려 있는지, 아무 곳에나 흩어져 있는지 로그로 요약.
- 가벼운 잡 하나로 (컷아웃 래스터를 스트립으로 읽기). 처리 방법(상한 자르기, 주변 값 대체 등)은 결과를 보고 Claude와 정함.

[B. v3, v4 추가 (1960, 2010만)]
- Dasy_CONUS_RF_v3 = v1 + elev, slope (고도는 절대값; 카운티 평균 대비 상대값은 카운티 평균이 항상 0이라 학습 불가라서 안 씀).
- Dasy_CONUS_RF_v4 = v1 + d_10k, d_20k, d_50k, d_100k, d_250k + elev, slope (전부).
- v1, v2와 같은 split/fold, 같은 연도(1960, 2010), compare_with Dasy_CONUS_RF_v1.
- CONUS DEM 컷아웃 필요: MA와 같은 GMTED2010 mn75_grd (/projects/jaju1407/data/raw/dem/gmted2010/mn75_grd),
  HISDAC 격자로 average 리샘플링, float32. 바다 nodata 처리와 slope 계산은 MA common.py 방식 그대로 (스트립 처리에 맞게).
  slope는 창 전체 gradient라 스트립 경계에서 결과가 같도록(겹치는 행 1줄) 주의.
- 설정 파일 configs/conus_rf_v3.yaml, conus_rf_v4.yaml. submit_conus.sh에 v3/v4 체인 모드 추가
  (DEM cutout -> v3, v4 features/train/predict/validate; distances, water는 pilot 것 재사용).

[C. tract 검증 출력 추가 (모든 버전 공통)]
- 2010(및 1960) tract를 인구밀도 4묶음으로 나눈 결과도 metrics에 추가:
  pop_obs / (n_cells x 0.0625 km2) 기준 <50, 50-500, 500-2000, 2000+ 명/km2. 묶음별 tract 수, 인구 비율, 면적 비율, MdAPE, MAE.
  (Claude가 v1/v2 2010로 미리 계산해 본 결과: 모든 묶음에서 v1이 나음, v2는 시골(<50)에서 35.2 -> 49.8 %로 가장 나빠짐.)
- 이미 돈 v1, v2도 validate만 다시 돌려서 같은 표를 얻게 해줘.

[D. 지도 비교]
- 2010 v1 vs v2 (그리고 v4) 셀 인구 지도를, 대도시에서 60-150 km 떨어진 시골 카운티 3-4곳에 대해 확대해서 PNG로
  (카운티 경계 + 건물 BUI 위에 인구 표시). 거리 피처가 카운티 안에서 인구를 대도시 쪽 빈 땅으로 옮기는지 눈으로 확인하려는 것.
  카운티 선택: v2 시골 tract 오차가 v1보다 가장 크게 늘어난 카운티 중에서 골라도 됨.

[공통]
- MA 설정과 기존 v1/v2 결과는 그대로. 로컬 합성 테스트, 커밋, push 후 Alpine 명령(사전 확인 + 체인 + 로그 커밋 + seff) 줘.
- A는 B, C, D와 독립이라 같은 제출에 넣되 실패해도 나머지가 돌게.
