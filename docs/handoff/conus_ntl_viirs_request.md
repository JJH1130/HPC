git pull 받고 아래를 해줘. 배경: docs/conus_plan.md "NTL test result" (gap / no-gap로 나누면 반대 결과), docs/open_items.md 2026-10-28.

[목적]
DMSP NTL(Li et al. 2020)은 BUI 공백 카운티에서 tract 오차를 절반으로 줄이지만(2010: 72.0 -> 35.1 %), 기록이 충실한 카운티에서는
빛 번짐 때문에 나빠짐(25.6 -> 30.8 %). 번짐이 적은 VIIRS-like NTL(Chen et al. 2021, 15 arc-sec, 2000-2018)로 같은 테스트를 해서
공백 카운티 이득은 유지되고 나머지 손해는 줄어드는지 확인.

[1. 데이터 등록 + 다운로드]
- docs/data_sources.md에 먼저 등록 (요약 표 행 + Details):
  Chen, Z., Yu, B., Yang, C., Zhou, Y., Yao, S., Qian, X., Wang, C., Wu, B., Wu, J. (2021). An extended time series (2000-2018) of global
  NPP-VIIRS-like nighttime light data from a cross-sensor calibration. Earth System Science Data 13, 889-906, doi:10.5194/essd-13-889-2021.
  Data: Harvard Dataverse doi:10.7910/DVN/YGIVCD (연도별 zip 약 50 MB). 라이선스는 Dataverse 페이지에서 확인해 기록.
  2000-2012는 DMSP를 오토인코더로 변환한 값, 2013-2018은 VIIRS 연간 합성이라는 점도 기록.
- 2000, 2010 두 해만 $DATA_ROOT/raw/ntl/viirs_like/ 로. Dataverse API로 파일 id를 찾아 받는 스크립트(또는 Alpine 로그인 노드에서
  붙여넣을 명령)를 만들어 줘. 인터넷이 안 되면 내가 노트북에서 받아 올리는 방법(scp 명령)도 같이.
- 받은 뒤 확인: CRS, 해상도, 값 범위, nodata, 바다 마스크, CONUS 범위 커버 여부를 로그로.

[2. 컷아웃 + QA]
- configs/conus_study_area.yaml에 레이어 NTLV 추가 (years [2000, 2010], float32, resampling nearest - DMSP NTL과 같게; 
  다른 방법이 낫다고 보면 이유와 함께 제안). grid_cutout.sh --layers NTLV.
- ntl_qa.py를 NTLV에도 (DN >= 60 박스 규칙은 이 자료에 맞지 않으니 VIIRS-like에는 적용하지 않거나 값 범위에 맞는 규칙으로;
  어떻게 했는지 로그). 경계 glow 지표(BUI = 0 셀 중 빛 있는 셀 비율, 경계 5 km vs 내륙)를 NTL과 NTLV 나란히.

[3. 모델]
- configs/conus_rf_v3_ntlv.yaml, 버전 Dasy_CONUS_RF_v3_ntlv: conus_rf_v3_ntl.yaml과 같고 피처 ntl 대신 ntlv(레이어 NTLV)만 다름.
  years [2000, 2010], compare_with Dasy_CONUS_RF_v3_all, 같은 split / fold / 탐색 공간 / n_iter 60.
- features / train / predict / validate (gap-share 0.05, 밀도 4묶음, train/test 부분).

[4. 비교]
- compare_models: v3_all, v3_ntl, v3_ntlv x 2000 / 2010 -> results/validation/conus/ntl_viirs_comparison.csv.
  특히 tract MdAPE를 gap / no_gap으로 나란히, 밀도 4묶음, 피처 순위(--rank-features ntl ntlv).
- county_maps 2010: 같은 4개 카운티 + BUI 공백 카운티 2곳(Macoupin IL 포함, DuPage IL 추가)으로 v3_all / v3_ntl / v3_ntlv,
  결과는 county_maps_ntlv/에 (기존 폴더 덮어쓰지 않게). BUI = 0 셀 인구 비율 포함.

[공통]
- 로컬 테스트, 커밋, push. docs/conus_plan.md, docs/runbooks/Running_CONUS.md, CLAUDE.md 갱신. submit_conus.sh에 ntlv 모드.
- Alpine 명령(다운로드 + 확인 블록, 사전 확인 + 체인, 진행 확인, 로그 커밋 + seff)을 블록마다 완전하게, 블록 끝에 성공 표시 한 줄씩.
