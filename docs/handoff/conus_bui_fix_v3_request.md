git pull 받고 아래를 해줘. 결정과 배경: docs/conus_plan.md "Version comparison v1-v4", "BUI outliers"의 Treatment, docs/open_items.md 2026-10-27.

[1. BUI 이상치 처리 (결정됨)]
- 규칙: BUI > 3e7 sq ft인 셀은 기록 오류로 보고, 그 셀의 BUI를 주변 3 x 3 이웃(자기 자신 제외 8셀)의 BUI 중앙값으로 대체.
  BUPL, BUPR, Land_Use는 그대로. 원본 HISDAC 파일은 건드리지 않고 CONUS 컷아웃의 BUI 레이어에만 적용.
- 모든 연도에 적용. 연도별로 대체한 셀 수, 대체 전/후 값, 상위 셀 목록을 로그와 QA CSV(results/cutout/conus/bui_fixed_{YEAR}.csv 같은 이름)로 남김.
  이웃이 창 밖이면 있는 이웃만 사용. 이웃도 3e7 초과면 그 이웃은 중앙값 계산에서 제외(남은 게 없으면 0).
- 설정으로 켜고 끔 (예: conus_study_area.yaml에 bui_cap: {max: 3.0e7, replace: neighbour_median}). MA 설정은 끈 상태 그대로 두되,
  MA 컷아웃에 3e7 초과 셀이 있는지만 QA로 한 번 세어서 기록 (있으면 알려줘).
- 컷아웃 단계에서 하든, 컷아웃 직후 별도 단계로 하든 단순한 쪽으로. 스트립 처리 시 이웃 계산이 스트립 경계에서 같게(위아래 1행 halo).
- 테스트: 합성 데이터로 (a) 고립된 큰 값 대체, (b) 이웃도 큰 값인 경우, (c) 창 가장자리, (d) 스트립 = 창 전체 결과.

[2. county_maps 버그]
- logs/county_maps.34921594.out: place_points()에서 rasterio CRS에 crs.name을 호출해 AttributeError.
  CRS 이름 출력 부분을 rasterio/pyproj 둘 다 되게 고쳐줘. 테스트 추가.

[3. v3를 CONUS 기본으로 다시 실행]
- Dasy_CONUS_RF_v3 (v1 + elev, slope)를 1920, 1960, 2010 세 해로 (지금은 1960, 2010만 있음). 같은 split/fold.
  BUI 처리 후의 컷아웃으로 features/train/predict/validate 전부 다시. 이전 v3 결과와 비교할 수 있게 버전 이름은
  Dasy_CONUS_RF_v3_bui (또는 v3를 덮어쓰지 않는 다른 이름)로, compare_with: Dasy_CONUS_RF_v3.
- v1도 같은 BUI 처리 컷아웃으로 1920/1960/2010 다시 (Dasy_CONUS_RF_v1_bui) 돌려서, BUI 처리 자체의 효과를 v1 기준으로도 볼 수 있게.
- county_maps는 2010에서 v1_bui, v2, v3_bui, v4를 같은 4개 카운티(Chelan WA, Reno KS, Fremont CO, Macoupin IL)로.
- 1920 tract 검증, 밀도 4묶음 포함.

[공통]
- docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신. 로컬 테스트, 커밋, push 후
  Alpine 명령(사전 확인 + 체인 + 로그 커밋 + seff)을 하나의 완전한 블록으로 줘 (지난번 붙여넣기에서 제출 줄이 잘린 적이 있으니,
  블록마다 끝에 무엇이 출력되면 성공인지 한 줄씩).
