# Getting started

## 1. What you need

- **Python 3.11+**
- A **solver**. Two are supported:
  - **GLPK** — free, ships with COBRApy, no setup. Fine for small models
    (`e_coli_core`) and all the tests. It can be slow on genome-scale models.
  - **Gurobi** — much faster, recommended for genome-scale models and strain
    design. Needs a license (academic licenses are free).

## 2. Create a virtual environment

Work in an isolated environment so the project's dependencies don't clash with
other Python tools on your machine. From the cloned repository root:

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
py -m venv .venv
.venv\Scripts\Activate.ps1
```

Your shell prompt should now show `(.venv)`. (Conda users can instead run
`conda create -n gem_suite python=3.11 && conda activate gem_suite`.) To leave the
environment later, run `deactivate`.

## 3. Install

With the environment **active**, install the package in editable mode with the
extras you need:

```bash
pip install --upgrade pip
pip install -e .                 # core: cobra, optlang, pandas, scipy, pyarrow
pip install -e ".[app]"          # + Dash front-end (dash, dash-ag-grid)
pip install -e ".[strain]"       # + StrainDesign (strain-design tab)
pip install -e ".[gurobi]"       # + gurobipy (Gurobi solver)
pip install -e ".[dev]"          # + pytest (run the test suite)

# everything at once:
pip install -e ".[app,strain,gurobi,dev]"
```

## 4. The Gurobi license (optional)

If you have a `gurobi.lic`, drop it in the **repository root**. On import,
`gem_suite` points `GRB_LICENSE_FILE` at it automatically (it uses `setdefault`,
so an environment variable you set yourself still wins). The bundled license is
**git-ignored** because it contains a secret key.

- The file must be **valid for your machine** (academic licenses are usually
  node-locked) and **compatible with the installed `gurobipy` major version**.
- No license / wrong machine? Use GLPK: `export GEM_SUITE_SOLVER=glpk`.

## 5. Run the app

```bash
python -m gem_suite.app.main        # or the console script:  gem-suite-app
```

This serves the Dash app at **http://127.0.0.1:8050**.

- The default solver is **Gurobi**; override with `GEM_SUITE_SOLVER=glpk`.
- The app keeps the live model **server-side**; your browser only holds a short
  `session_id` (and a `job_id` for long jobs). Loading a model, editing it, and
  running analyses all happen in one in-memory session.

## 6. Or use it as a library

`ModelService` is completely UI-free — drive it from a script or notebook:

```python
from gem_suite import ModelService

svc = ModelService(solver="glpk")
sid = svc.load_model("tests/data/e_coli_core.xml.gz")

print(svc.summary(sid))                 # counts, objective, solver
print(svc.fba(sid).objective_value)     # 0.8739…  max growth rate

svc.set_bounds(sid, "EX_o2_e", lower=0) # anaerobic
print(svc.fba(sid).objective_value)     # lower growth
svc.reset(sid)                          # back to as-loaded
```

## 7. Run the tests

```bash
pytest            # ~165 tests on e_coli_core with GLPK (no Gurobi needed)
```

Tests always use the small `e_coli_core` model — never a genome-scale model.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Could not set solver 'gurobi'` on load | No/invalid Gurobi license → `GEM_SUITE_SOLVER=glpk`. |
| App starts but a tab errors on first click | No model loaded yet — use the **Load** tab first. |
| `BrokenProcessPool` when launching | A custom launch script must guard its entry with `if __name__ == "__main__":` (job workers re-import it). The provided entry point already does. |
| Strain-design tab missing features | Install the extra: `pip install -e ".[strain]"`. |
