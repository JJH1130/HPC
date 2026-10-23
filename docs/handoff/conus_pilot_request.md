git pull 받고 아래를 한 뒤, 시범 실행(pilot: 1920/1960/2010, v1+v2) 명령까지 줘.

[시험 실행 결과 요약 - Claude가 로그 확인 (jobs 34814376-34814382, 1960 v1)]
- 7개 잡 모두 DONE. 대기 제외 약 25분.
- 시간/메모리 (seff): census 1:14 / 1.7 GB, cutout 1:59 / 7.7 GB (15 GB 할당), water 14:32 / 15.2 GB (60), place_dist 2:54 / 3.0 GB (30),
  features 1:03 / 9.5 GB (15, 64%), train 3:35 / 3.9 GB (60), predict measure 0:45 / 9.3 GB (120).
  예측 추정: 연도당 약 3.6분 (1.24억 셀, 570k cells/s) - conus_plan.md 추정(1-1.5시간)보다 훨씬 빠름.
- 1960 v1: train 2,475 / test 618 counties, CV R2 0.719 +/- 0.037, TEST R2 0.738. SHAP: bui > bldg_size > mu_ratio > rent_share > dist_built > res_share.
- water: uncovered 0, QA points ok, JRC no-data 0.0204 of covered pixels (MA에서만 바다로 확인됨).
- 이 결과(시간, 메모리, 점수)를 conus_plan.md 규모 표 옆에 "measured (trial)" 열로 기록하고, 러너북 Status 갱신.

[pilot 전에 고칠 것]
1. CSV에 행이 없는 2010 카운티 4개 보정: Miami-Dade (G1200860, 2010년 250만), Shannon SD (G4601130), Broomfield CO (G0800140), Bedford city VA (G5105150).
   CSV에는 12025/12086, 46113/46102 등 어떤 코드로도 행이 없음(Claude가 확인). FIPS 재매핑으로는 안 고쳐짐.
   -> conus_counties.py에서 이 카운티들의 인구를 그해 NHGIS 원래 카운티 인구(counties_{YEAR}.gpkg, prepare_census 출력)에서 GISJOIN으로 가져와 채움.
   Miami-Dade는 NHGIS에서 옛 Dade County 코드(G1200250)로 나오는 연도가 있으니 그 경우 그 코드를 씀.
   Broomfield는 2001년 생성이라 2010만, Bedford city는 NHGIS에 있는 연도만. 없는 연도는 그대로 no_value.
   새 status 이름 예: filled_nhgis, use_status에 추가. 채운 카운티/연도/인구를 로그와 results/census_conus 요약에 남기고,
   경계가 2010 폴리곤과 같은지(면적 비) 같이 로그로. docs/conus_plan.md "Known input errors"와 open_items.md 갱신.
2. JRC no-data 점검: CONUS에서 no-data(255)를 물로 세는 규칙이 내륙 육지를 물로 만들지 않는지 확인.
   src/grid/jrc_nodata_check.py(MA에서 쓴 것)를 CONUS 창에 돌리거나 water_frac 로그에 추가해서,
   study county 셀 안의 no-data 비율, no-data가 가장 많은 카운티 상위 20개를 qa 파일로 남겨줘. pilot 체인에 넣어도 됨(가벼우면).
3. 자원: features는 v2에서 거리 레이어 5개가 더해지니 ntasks 4 -> 6. 나머지는 시험 결과로 충분하니 그대로,
   wall time은 측정치의 3-4배 정도로 줄여도 됨(대기 시간 줄이기). submit_conus.sh에 반영.
4. pilot에서 v2 train이 v1과 같은 split/fold를 쓰고 compare_with v1로 비교 결과를 남기는지 확인.
5. 로컬 테스트, 커밋, push 후 내가 Alpine에 붙여넣을 pilot 명령(사전 확인 + 체인 + 모니터링 + 로그 커밋, seff 출력까지)을 줘.
