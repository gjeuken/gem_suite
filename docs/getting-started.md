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

### Install as a standalone command (pipx)

If you just want the app as a command (no cloning, no editable install), use
[pipx](https://pipx.pypa.io/) — it installs GEM Suite in its own isolated
environment and puts `gem-suite-app` on your PATH:

```bash
pipx install "gem_suite[app,strain] @ git+https://github.com/gjeuken/gem_suite.git"
gem-suite-app        # serves the app at http://127.0.0.1:8050
```

This runs on **GLPK** with no license or extra setup. To use Gurobi later:
`pipx inject gem_suite gurobipy`, add a license (see §4), and set
`GEM_SUITE_SOLVER=gurobi`.

## 4. Choosing a solver (and the optional Gurobi license)

The solver is set by the `GEM_SUITE_SOLVER` environment variable:

- **`glpk` (default)** — bundled with COBRApy, no license, nothing to configure.
  This is what runs out of the box. Fine for small/medium models; slower on
  genome-scale FVA and strain design.
- **`gurobi`** — much faster; opt in with `export GEM_SUITE_SOLVER=gurobi` once
  you have a license.

**Adding a Gurobi license** (only if you want Gurobi):

1. Get a free academic (or commercial) license from the Gurobi portal.
2. Run `grbgetkey <your-key>` — it writes `~/gurobi.lic`. gurobipy finds it
   automatically. (Or point `GRB_LICENSE_FILE=/path/to/gurobi.lic` at any file.)
3. `pip install -e ".[gurobi]"` (or `pipx inject gem_suite gurobipy`) and set
   `GEM_SUITE_SOLVER=gurobi`.

Notes:
- A normal **local install (pip/pipx) on your own machine** is the easy case — the
  usual node-locked academic license works fine here. (Inside Docker it would not;
  containers need a Gurobi WLS license instead.)
- The license version must be ≥ the installed `gurobipy` major version.
- When you run **from a source checkout**, a `gurobi.lic` placed in the repo root
  is auto-detected (it's git-ignored, as it holds a secret key). Installed copies
  just use the standard locations above.

## 5. Run the app

```bash
python -m gem_suite.app.main        # or the console script:  gem-suite-app
```

This serves the Dash app at **http://127.0.0.1:8050** and opens with a bundled
*E. coli* core model preselected, so you can click **Load** and start immediately.

- The default solver is **GLPK**; set `GEM_SUITE_SOLVER=gurobi` for Gurobi.
- The app keeps the live model **server-side**; your browser only holds a short
  `session_id` (and a `job_id` for long jobs). Loading a model, editing it, and
  running analyses all happen in one in-memory session.
- **Security:** the app has no authentication and runs server-side compute and
  file uploads. Keep it local — don't expose it on a public network.

## 6. Or use it as a library

`ModelService` is completely UI-free — drive it from a script or notebook:

```python
from gem_suite import ModelService
from gem_suite.data import example_model_path     # the bundled e_coli_core

svc = ModelService(solver="glpk")
sid = svc.load_model(example_model_path())        # or any SBML/JSON/MAT path

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
