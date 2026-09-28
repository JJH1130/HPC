#!/bin/bash
# Env check: confirms the "analysis" conda env (environment.yml) works inside a
# batch job — python comes from the env, numpy/pandas/matplotlib/Jupyter import,
# and a small compute + headless plot succeed. Ends with "ENV OK".
# The test figure goes to $SCRATCH (not git); its path is printed in the log.
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/test_env_analysis.sh
#SBATCH --job-name=test_env_analysis
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# --account is OPTIONAL: add "#SBATCH --account=<allocation>" only if you have
# a project allocation. This repo currently has none, so jobs run on the free
# default account (ucb-general).
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=00:10:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env analysis
cd "$REPO"

py=$(command -v python)
echo "== python: $py"
if [[ "$py" != "$ENVS/analysis/bin/python" ]]; then
    echo "ERROR: python is not from $ENVS/analysis — env missing or half-built"
    exit 1
fi
echo "== jupyter lab $(jupyter lab --version)"

export MPLBACKEND=Agg   # compute nodes have no display
export FIG_PATH=$SCRATCH/test_env_analysis_${SLURM_JOB_ID:-local}.png
python -u - <<'EOF'
import os, sys
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import ipykernel

print(f"python {sys.version.split()[0]} | numpy {np.__version__} | pandas {pd.__version__} "
      f"| matplotlib {matplotlib.__version__} | ipykernel {ipykernel.__version__}")

rng = np.random.default_rng(0)
a = rng.standard_normal((500, 500))
print(f"numpy matmul trace: {np.trace(a @ a.T):.1f}")

df = pd.DataFrame({"group": rng.integers(0, 3, 1000), "value": rng.standard_normal(1000)})
print("pandas groupby mean:")
print(df.groupby("group")["value"].mean().round(3).to_string())

fig, ax = plt.subplots()
df["value"].plot.hist(ax=ax, bins=30)
fig.savefig(os.environ["FIG_PATH"])
size = os.path.getsize(os.environ["FIG_PATH"])
assert size > 0, "empty figure"
print(f"matplotlib figure: {os.environ['FIG_PATH']} ({size} bytes)")
print("ENV OK")
EOF

echo "== done $(date -Is)"
