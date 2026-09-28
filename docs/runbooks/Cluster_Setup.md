# Cluster setup: from a new account to a cloned repo on Alpine

One-time onboarding for CU Boulder's Alpine HPC cluster. Run each step in order;
each ends with a check so we both know it worked (Claude can't see the cluster).

**Profile:** IdentiKey `jaju1407`, allocation: none — runs on `ucb-general`,
PetaLibrary: `/pl/active/Leyk_Lab` (not in use until PI approves), GitHub owner `JJH1130`, repo `HPC`, terminal: PuTTY.

## 1. Log in (PuTTY)

1. Open PuTTY → Host Name `login.rc.colorado.edu`, Port `22`, type SSH.
2. (Optional) name it `alpine` under Saved Sessions and Save, for a one-click login next time.
3. Open. At `login as:` enter `jaju1407`, then the IdentiKey password, then approve the Duo push
   (enroll first at https://duo.colorado.edu if not already). No Duo app: `yourpassword,sms` for a
   one-time code by text, then log in with `yourpassword,<code>`.
4. **Paste with right-click** in PuTTY (Ctrl-V does not work); selecting text copies automatically.

You land on a login node — fine for editing, git, and `sbatch`; never for computation or conda
installs (CURC kills heavy processes there; see `Creating_Cluster_Envs.md` once it exists).

**Status: done (terminal chosen).**

## 2. GitHub over SSH from the cluster

*Login node.* Create a dedicated key for GitHub (revocable on its own):

```bash
ssh-keygen -t ed25519 -C "jaju1407@alpine" -f ~/.ssh/id_ed25519_github
cat ~/.ssh/id_ed25519_github.pub
```

Copy the printed line into GitHub → Settings → SSH and GPG keys → New SSH key
(title e.g. "CURC Alpine"). A passphrase is recommended; if set,
`eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519_github` once per login.

*Login node.* Tell SSH to use that key for github.com:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_github
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

Check: `ssh -T git@github.com` → should say "Hi JJH1130! You've successfully authenticated".

*Login node.* Set git identity so cluster commits are attributable:

```bash
git config --global user.name  "Jaeheon Jung"
git config --global user.email "Jaeheon.Jung@colorado.edu"
git config --global pull.rebase false
```

**Status: done — 2026-09-26 (verified `ssh -T git@github.com` → "Hi JJH1130!...").**

## 3. Clone into /projects (not home, not scratch)

`/home` is 2 GB — too small. `/scratch` is purged 90 days after file creation — code there silently
disappears. `/projects/jaju1407` (250 GB, backed up) is the right place.

```bash
cd /projects/jaju1407
git clone git@github.com:JJH1130/HPC.git
cd HPC
git log --oneline -1
mkdir -p logs
git status
```

Confirms: the commit hash matches what was last pushed from the laptop.

**Status: done — reported by user 2026-09-29 (repo cloned at `/projects/jaju1407/HPC`).**

## 4. Allocation (optional — already recorded)

This project has no compute allocation; jobs run on the free default `ucb-general`. No
`--account` line needed in sbatch scripts. If that ever changes, run and report back:

```bash
sacctmgr -nP show assoc user=$USER format=account,partition,qos
```

PetaLibrary: `/pl/active/Leyk_Lab`. **Do not write there until the PI approves** — until then
`sbatch/cluster_env.sh` keeps `PL_ROOT` empty and all outputs stay on `/scratch/alpine/jaju1407`.

## 5. The local ↔ cluster loop (ongoing habit)

- Edit code locally (with Claude) → `git commit` + `git push`.
- On the cluster: `cd /projects/jaju1407/HPC && git pull`, then run the relevant runbook.
- Never edit the same file on both sides between pulls; a cluster-side hotfix gets committed and
  pushed from there before Claude's next local change.
- After a job: commit `logs/` + small results on the cluster, push, then tell Claude to pull.

## 6. CPU smoke test (first sbatch job)

Confirms submission, the `acpu` + `cpu-normal` pair, and the `logs/` round trip before any real job.

*Login node.*

```bash
cd /projects/jaju1407/HPC
git pull
mkdir -p logs
sbatch sbatch/test_hello_cpu.sh
```

*Login node.* Watch it (usually minutes; `PD` = pending, `R` = running, gone = finished):

```bash
squeue -u jaju1407
```

*Login node.* When it's gone from `squeue`, check it and send the log back:

```bash
cd /projects/jaju1407/HPC
cat logs/test_hello_cpu.*.out
git add logs/test_hello_cpu.*.out
git commit -m "run: test_hello_cpu smoke test log"
git push
```

Check: the log ends with `hello from Alpine, jaju1407` and `== done`. Then Claude pulls and reads it.

**Status: current step.**

## Notes

- 2026-09-26: onboarding started. Repo folder structure (`sbatch/`, `logs/`, `src/`) created and
  pushed from the laptop before cluster access was set up.
- 2026-09-29: moved to a new laptop; clone on Alpine confirmed. PetaLibrary name recorded
  (Leyk_Lab), pending PI approval. Next: CPU smoke test (`sbatch/test_hello_cpu.sh`).
