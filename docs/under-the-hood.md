# Under the hood — feature → COBRApy / StrainDesign mapping

This page maps every GEM Suite capability to the exact **COBRApy** and
**StrainDesign** functions it calls, so you can reproduce or extend any analysis
in plain Python. Two layers sit between the UI and those libraries:

```
Dash callbacks  ─▶  gem_suite.app.controllers  ─▶  ModelService / strain_design  ─▶  COBRApy / StrainDesign
(app/pages/*.py)     (UI-free, JSON-able)          (the real work)                   (solvers via optlang)
```

- **`ModelService`** (`gem_suite/model_service.py`) wraps a live `cobra.Model` per
  session. It is UI-free; notebooks and scripts call it directly.
- **The job layer** (`gem_suite/jobs/`) runs slow work (FVA, strain design) as
  pure `spec → result` *runners* in a process pool, referencing the model by file
  path. The runners call the same functions below.
- **Solvers**: COBRApy/StrainDesign talk to GLPK or Gurobi through **optlang**;
  the suite just passes a solver string (`ModelService(solver=…)`, `JobSpec.solver`).

> Legend: `Suite feature` → `ModelService method` → **cobra/straindesign call(s)**.

---

## Model I/O & sessions

| Feature | Method | COBRApy |
|---|---|---|
| Load SBML / JSON / MAT (Load tab, `load_model`) | `ModelService.load_model` → `read_model_file` | `cobra.io.read_sbml_model`, `cobra.io.load_json_model`, `cobra.io.load_matlab_model` |
| Export current model (Reactions ▸ Export SBML; job bridge) | `export_model` / `controllers.export_sbml` | `cobra.io.write_sbml_model`, `save_json_model`, `save_matlab_model` |
| As-loaded snapshot for `reset` | `load_model` / `reset` | `cobra.Model.copy()` |
| Structural hash (manifests) | `model_hash` | hash of `model.reactions` bounds + `model.metabolites` + `str(model.objective.expression)` |

Sessions are an in-memory dict of `cobra.Model`s keyed by `session_id`; the model
never crosses to the browser. (`clone_session` is the one declared method left
unimplemented.)

## Structure queries

| Feature | Method | COBRApy |
|---|---|---|
| Summary (counts, objective, solver) | `summary` | `len(model.reactions/metabolites/genes)`, `model.objective.expression`, `model.objective.direction` |
| Reaction table / details | `list_reactions`, `get_reaction` | `reaction.build_reaction_string()`, `.bounds`, `.gene_reaction_rule`, `.subsystem`, `.objective_coefficient` |
| Reaction ids / objective reactions | `reaction_ids`, `objective_reactions` | iterate `model.reactions`, `reaction.objective_coefficient` |

## Editing

| Feature | Method | COBRApy |
|---|---|---|
| Edit bounds (grid cell) | `set_bounds` | `reaction.bounds = (lb, ub)` |
| Add reaction (Reactions ▸ Add) | `add_reaction` (parsed by `ki_parser.parse_ki_line`) | `cobra.Reaction`, `model.add_reactions([…])`, `reaction.add_metabolites`, `cobra.Metabolite`, `reaction.gene_reaction_rule = …` |
| Remove reaction | `remove_reaction` | `model.remove_reactions([…], remove_orphans=…)` |
| Set objective (single or linear combo, max/min) | `set_objective` / `controllers.set_objective_combination` | `model.objective = "<rxn>"` or `{reaction: coeff}`; `model.objective.direction = "max"/"min"` |
| Change log / reset | `change_log`, `reset` | restores from the `model.copy()` snapshot |

Every edit returns a `ChangeRecord` and is appended to a per-session log.

## Exchanges

| Feature | Method | COBRApy |
|---|---|---|
| Classify boundary reactions | `classify_exchanges` | `model.boundary`, `model.exchanges`, `model.demands`, `model.sinks`; sign of bounds → direction |
| Open/close uptake/secretion | `toggle_exchange` | `reaction.bounds` (sign convention: negative = uptake) |
| Set the whole medium | `set_medium` | `model.medium = {exchange_id: max_uptake}` |

## FBA / pFBA

| Feature | Method | COBRApy |
|---|---|---|
| FBA | `fba` | `model.optimize()`; objective from `solution.objective_value`; duals via `solution.reduced_costs`, `solution.shadow_prices` |
| pFBA | `pfba` | `cobra.flux_analysis.pfba(model)` (objective reported as the biological objective, not the flux sum) |
| Loopless variant (both) | `fba(loopless=True)`, `pfba(loopless=True)` | `cobra.flux_analysis.loopless_solution(model[, fluxes])` (CycleFreeFlux) |
| Exchange flux diagram | `controllers.exchange_flux_diagram` | reuses `classify_exchanges` + the FBA/pFBA `fluxes` |

## Binding constraints (which inequalities are tight)

| Feature | Method | COBRApy |
|---|---|---|
| Bounds met with equality at the optimum | `binding_constraints` | compares `fluxes[r]` to `reaction.lower_bound/upper_bound`; FBA `reduced_costs` flag *limiting* bounds |

## FVA

| Feature | Method | COBRApy |
|---|---|---|
| Flux variability (blocking) | `fva` → `compute_fva` | `cobra.flux_analysis.flux_variability_analysis(model, reaction_list, fraction_of_optimum, loopless, processes)` |
| FVA as a job | `jobs.runners.run_fva` → `compute_fva` | same; result persisted as **parquet** (`pyarrow`) |
| Span plot | `controllers.fva_spans` | filters `max − min > tol` from the FVA ranges |

`loopless=True` is translated to cobra's `"cycleFreeFlux"` method.

## Scan (phenotypic phase plane / robustness)

| Feature | Method | COBRApy |
|---|---|---|
| Scan 1–2 fixed fluxes vs a response | `scan_objective` | for each grid point: `with model:` (context manager, auto-reverts), `reaction.bounds = (v, v)`, `model.slim_optimize()`; response = objective value or `reaction.flux` (the optimised primal) |

Using `slim_optimize` + `reaction.flux` avoids building a full `Solution` per point
and emits no infeasibility warnings; `with model:` guarantees the session bounds
are untouched.

## EFM test (elementary flux mode)

| Feature | Method | COBRApy / NumPy |
|---|---|---|
| EFM verdict on a flux vector | `efm_test` → `gem_suite.efm.is_elementary_flux_mode` | `cobra.util.array.create_stoichiometric_matrix(model)`; NumPy `linalg.matrix_rank` on the support submatrix; **EFM iff nullity == 1** |

The Analysis tab runs it on the (loopless) pFBA solution.

## Strain design (`gem_suite/strain_design.py`)

| Feature | Function | StrainDesign / COBRApy |
|---|---|---|
| Build suppress/protect modules | `_build_modules` | `straindesign.SDModule(model, sd.names.SUPPRESS \| PROTECT, constraints=[…])` |
| Bilevel approaches | `_build_modules` (legacy/target path) | `sd.names.OPTKNOCK`, `ROBUSTKNOCK`, `OPTCOUPLE` |
| Knock-out candidates (gene/reaction) | `design_strains` | `compute_strain_designs(gko_cost=…)` / `ko_cost=…` |
| Knock-in candidates | `_prepare_knockins`, `ki_parser.add_ki_reactions` | `cobra.Reaction`/`Metabolite`, `model.add_reactions`; `compute_strain_designs(ki_cost=…)` |
| Solve | `design_strains` | `straindesign.compute_strain_designs(model, sd_modules=…, solver=…, compress=True, max_cost=…, max_solutions=…, solution_approach=sd.names.BEST)` |
| Read solutions | `_to_result` | `SDSolutions.status`, `.is_gene_sd`, `.get_gene_sd()`, `.reaction_sd` |
| KI equation parsing | `ki_parser.parse_ki_line/parse_ki_block` | builds cobra-style stoichiometry dicts |

`compress=True` runs StrainDesign's network compression before the MILP — essential
at genome scale. GLPK has no indicator constraints, so StrainDesign automatically
falls back to a big-M formulation (you'll see a log note).

### Post-run verification & design EFM

| Feature | Function | StrainDesign / COBRApy |
|---|---|---|
| Build the intervened model | `_intervened_model` | `model.copy()`; reaction KOs via `reaction.bounds = (0, 0)`; gene KOs via `gene.knock_out()`; KIs via `add_ki_reactions` |
| Test a module's region | `verify_design` → `_feasible_with` | `straindesign.parse_constraints(constraints, reaction_ids)` → optlang `model.problem.Constraint` on `reaction.flux_expression`; feasibility via `model.slim_optimize()` (protect ⇒ feasible, suppress ⇒ infeasible) |
| EFM of a design | `_design_efm` | `cobra.flux_analysis.pfba` + `loopless_solution`, then `is_elementary_flux_mode` |

## Job layer (detachable heavy compute)

| Piece | File | Notes |
|---|---|---|
| Spec / status / params | `jobs/spec.py` | `JobSpec`, `JobStatus`, `JobType`, `StrainDesignParams` — all JSON round-trippable; model referenced by **path** |
| Local backend | `jobs/local.py` | `concurrent.futures.ProcessPoolExecutor` (**spawn** context — solver libs aren't fork-safe) |
| Runners | `jobs/runners.py` | pure `run_fva`, `run_strain_design`; artifacts: FVA → parquet, strain design → JSON + companion manifest |
| SLURM backend | `jobs/slurm.py` | conforming stub for a future cluster backend (same `JobBackend` protocol) |

## Run manifests (`gem_suite/manifest.py`)

`build_manifest` records model label + `model_hash`, operation, parameters, solver,
status, and **package versions** (`importlib.metadata.version` for cobra, optlang,
straindesign, gurobipy, gem_suite). CSV exports ship a companion `*_manifest.json`;
strain-design jobs write one beside the result.

---

## Minimal end-to-end in pure Python

Everything the UI does is reproducible without it:

```python
from gem_suite import ModelService
from gem_suite.jobs.spec import StrainDesignParams
from gem_suite.strain_design import design_strains
import cobra

svc = ModelService(solver="glpk")
sid = svc.load_model("tests/data/e_coli_core.xml.gz")

# analysis
svc.set_objective(sid, {"EX_succ_e": 1.0}, direction="max")   # cobra: model.objective
print(svc.pfba(sid, loopless=True).objective_value)           # cobra: pfba + loopless_solution
res = svc.fba(sid)                                            # cobra: optimize (reduced costs available)
print(svc.binding_constraints(sid, res.fluxes, res.reduced_costs))

# strain design (StrainDesign under the hood)
model = cobra.io.read_sbml_model("tests/data/e_coli_core.xml.gz")
params = StrainDesignParams(
    approach="MCS", gene_level=False, ko_candidates=["PFK", "PYK", "NADH16",
        "CYTBD", "ATPS4r", "FRD7", "SUCDi"], max_size=3, max_solutions=2,
    modules=[
        {"type": "suppress", "constraints": ["Biomass_Ecoli_core >= 0.05",
            "EX_etoh_e <= 0", "EX_glc__D_e <= -0.1"]},
        {"type": "protect", "constraints": ["Biomass_Ecoli_core >= 0.05"]},
    ])
result = design_strains(model, params, solver="glpk")          # straindesign.compute_strain_designs
for sol in result.solutions:
    print(sol.knockouts, "verified:", [v["passed"] for v in sol.verification])
```
