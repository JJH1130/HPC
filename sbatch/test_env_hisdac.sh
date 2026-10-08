#!/bin/bash
# Env check: confirms the "hisdac" conda env (envs/hisdac/environment.yml) works
# inside a batch job — python comes from the env, and a tiny end-to-end pass
# through each package succeeds: rasterio raster write/read with a CRS (GDAL/PROJ
# data found), geopandas reproject + parquet (pyarrow) + GeoPackage (pyogrio),
# LightGBM fit, SHAP values, scikit-learn metric, YAML, headless plot.
# Ends with "ENV OK". Test files go to $SCRATCH/test_env_hisdac_<jobid>/ (not git).
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/test_env_hisdac.sh
#SBATCH --job-name=test_env_hisdac
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=00:10:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

py=$(command -v python)
echo "== python: $py"
if [[ "$py" != "$ENVS/hisdac/bin/python" ]]; then
    echo "ERROR: python is not from $ENVS/hisdac — env missing or half-built"
    exit 1
fi

export MPLBACKEND=Agg   # compute nodes have no display
export TEST_DIR=$SCRATCH/test_env_hisdac_${SLURM_JOB_ID:-local}
mkdir -p "$TEST_DIR"
python -u - <<'EOF'
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
import geopandas as gpd
import pyogrio
import pyarrow
import sklearn
from sklearn.metrics import r2_score
import lightgbm as lgb
import shap
import yaml
import matplotlib
import matplotlib.pyplot as plt
import ipykernel

out = Path(os.environ["TEST_DIR"])
print(f"python {sys.version.split()[0]} | numpy {np.__version__} | pandas {pd.__version__}")
print(f"rasterio {rasterio.__version__} (GDAL {rasterio.__gdal_version__}) | geopandas {gpd.__version__} "
      f"| pyogrio {pyogrio.__version__} | pyarrow {pyarrow.__version__}")
print(f"scikit-learn {sklearn.__version__} | lightgbm {lgb.__version__} | shap {shap.__version__} "
      f"| pyyaml {yaml.__version__} | matplotlib {matplotlib.__version__} | ipykernel {ipykernel.__version__}")

# rasterio: write + read a small GeoTIFF in CONUS Albers (EPSG:5070) — fails if PROJ/GDAL data is missing
rng = np.random.default_rng(0)
arr = rng.random((50, 50)).astype("float32")
tif = out / "test.tif"
with rasterio.open(tif, "w", driver="GTiff", height=50, width=50, count=1, dtype="float32",
                   crs="EPSG:5070", transform=from_origin(-2e6, 3e6, 250, 250)) as dst:
    dst.write(arr, 1)
with rasterio.open(tif) as src:
    assert np.allclose(src.read(1), arr)
    print(f"rasterio GeoTIFF ok: {src.crs.to_string()} {src.width}x{src.height}")

# geopandas: reproject, write GeoParquet (pyarrow) and GeoPackage (pyogrio), read back
gdf = gpd.GeoDataFrame({"v": [1, 2, 3]},
                       geometry=gpd.points_from_xy([-105.27, -104.99, -105.08], [40.01, 39.74, 40.59]),
                       crs="EPSG:4326").to_crs("EPSG:5070")
gdf.to_parquet(out / "test.parquet")
gdf.to_file(out / "test.gpkg", engine="pyogrio")
assert len(gpd.read_parquet(out / "test.parquet")) == 3
assert len(gpd.read_file(out / "test.gpkg", engine="pyogrio")) == 3
print(f"geopandas ok: reprojected to EPSG:5070, x[0]={gdf.geometry.x.iloc[0]:.0f} m")

# LightGBM + SHAP + scikit-learn
X = rng.standard_normal((500, 5))
y = 2 * X[:, 0] - X[:, 1] + 0.1 * rng.standard_normal(500)
model = lgb.LGBMRegressor(n_estimators=50, n_jobs=1, verbose=-1).fit(X, y)
print(f"lightgbm ok: train R2={r2_score(y, model.predict(X)):.3f}")
sv = shap.TreeExplainer(model).shap_values(X[:100])
top = np.abs(sv).mean(axis=0).argmax()
print(f"shap ok: values {sv.shape}, top feature = x{top} (expected x0)")

# pyyaml + matplotlib
assert yaml.safe_load("a: 1\nb: [2, 3]") == {"a": 1, "b": [2, 3]}
fig, ax = plt.subplots()
ax.imshow(arr)
fig.savefig(out / "test.png")
print(f"yaml + matplotlib ok: {out / 'test.png'} ({(out / 'test.png').stat().st_size} bytes)")
print("ENV OK")
EOF

echo "== done $(date -Is)"
