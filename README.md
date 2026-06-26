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

```bash
python -m venv .venv && source .venv/bin/activate   # create & activate a venv
pip install -e ".[app,strain,dev]"                  # install with extras
python -m gem_suite.app.main                        # serve at http://127.0.0.1:8050
```

(On Windows: `python -m venv .venv` then `.venv\Scripts\activate`.)

Open the app, **Load** the bundled `tests/data/e_coli_core.xml.gz`, and explore.
Prefer scripting? `ModelService` is a plain Python API:

```python
from gem_suite import ModelService
svc = ModelService(solver="glpk")            # or "gurobi"
sid = svc.load_model("tests/data/e_coli_core.xml.gz")
print(svc.fba(sid).objective_value)          # 0.8739…  (max growth)
```

See [SPEC.md](SPEC.md) and [SPEC_strain_design_addendum.md](SPEC_strain_design_addendum.md)
for the original design briefs.
