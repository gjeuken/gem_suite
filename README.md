# GEM Suite

A single-user, local tool for exploring **genome-scale metabolic models (GEMs)**
— load a model, edit it, run constraint-based analyses (FBA / pFBA / FVA), scan
phenotypes, and compute strain designs (knock-outs **and** knock-ins) — all from
a browser, with a clean Python API underneath.

It is a friendly front-end over two well-established libraries:

- **[COBRApy](https://opencobra.github.io/cobrapy/)** — model handling and
  constraint-based analysis.
- **[StrainDesign](https://straindesign.readthedocs.io/)** — MCS / OptKnock /
  RobustKnock / OptCouple strain design.

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
pipx install "gem_suite[app,strain] @ git+https://github.com/gjeuken/gem_suite.git"
gem-suite-app        # serves at http://127.0.0.1:8050
```

Or from a clone, in a virtual environment:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[app,strain,dev]"
python -m gem_suite.app.main
```

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
