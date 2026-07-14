# GEM Suite

A single-user, local tool for exploring **genome-scale metabolic models (GEMs)**
— load a model, edit it, run constraint-based analyses (FBA / pFBA / FVA), and
scan phenotypes — all from a browser, with a clean Python API underneath.

It is a friendly front-end over **[COBRApy](https://opencobra.github.io/cobrapy/)**
(model handling and constraint-based analysis).

> **Strain design** (MCS / OptKnock / RobustKnock / OptCouple via
> **[StrainDesign](https://straindesign.readthedocs.io/)**) is implemented and
> tested, but **not exposed in the local UI**: those MILPs are far too slow to run
> interactively without a cluster. It remains available from Python and through
> the job layer, which is built to move to SLURM/HPC. See
> [under the hood](docs/under-the-hood.md#strain-design-gem_suitestrain_designpy).

```
┌─────────────┐    session_id / job_id     ┌──────────────────────────┐
│  Dash app   │ ───────────────────────▶   │ ModelService (UI-free)   │  COBRApy
│ (browser)   │ ◀───────── results ─────    │  sessions, edits, FBA…   │
└─────────────┘                             │ Job layer  ──▶ runners   │  StrainDesign
                                            └──────────────────────────┘
```

## Documentation

- **[Getting started](docs/getting-started.md)** — install, solver/license, run the app.
- **[User guide](docs/user-guide.md)** — a didactic, tab-by-tab walkthrough with
  the concepts explained from scratch.
- **[Under the hood](docs/under-the-hood.md)** — every feature mapped to the exact
  COBRApy and StrainDesign functions it calls.

## Quick start

Install it as a standalone command with [pipx](https://pipx.pypa.io/) — no clone,
no license, runs on the bundled **GLPK** solver:

```bash
pipx install "gem_suite[app] @ git+https://github.com/gjeuken/gem_suite.git"
gem-suite-app        # serves at http://127.0.0.1:8050
```

Or from a clone, in a virtual environment:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[app,dev]"
python -m gem_suite.app.main
```

(Add the `strain` extra only if you want the StrainDesign API — it is not part of
the local UI.)

The app opens with a bundled *E. coli* core model preselected — click **Load** and
explore. Want the faster Gurobi solver? See
[getting started §4](docs/getting-started.md) (`GEM_SUITE_SOLVER=gurobi` + a license).
Prefer scripting? `ModelService` is a plain Python API:

```python
from gem_suite import ModelService
from gem_suite.data import example_model_path
svc = ModelService(solver="glpk")            # or "gurobi"
sid = svc.load_model(example_model_path())   # bundled e_coli_core (or any path)
print(svc.fba(sid).objective_value)          # 0.8739…  (max growth)
```

See [SPEC.md](SPEC.md) and [SPEC_strain_design_addendum.md](SPEC_strain_design_addendum.md)
for the original design briefs.
