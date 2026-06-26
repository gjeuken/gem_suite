# GEM Suite — build specification

A single-user computational suite for analysing genome-scale metabolic models
(GEMs), starting from iML1515-class models. This document is the bootstrap brief
for Claude Code. Two contract files accompany it and are the skeleton to build
against: `model_service.py` and `jobs.py`.

## Goal

A local tool to:

- load a GEM (SBML / JSON / MAT) and inspect structure
- edit reaction bounds; add and remove reactions; change the objective
- classify import/export (and demand/sink) reactions and toggle them on/off
- run FBA, parsimonious FBA (pFBA), and FVA; export each to CSV
- (later) strain design: compute the gene/reaction knock-outs **and knock-ins**
  required to reach a metabolic-engineering goal (target coupled to growth, or a
  yield enforced), with post-run verification and an EFM check

> **Naming:** any reference to "dfba" in correspondence means **pFBA**
> (parsimonious FBA), not dynamic FBA. The EFM test runs on the pFBA flux vector.

The strain-design UI, verification, EFM test, CSV export, and styling are
specified in detail in `SPEC_strain_design_addendum.md` (milestone 6). This file
is the high-level source of truth; the addendum is its expansion.

## Scope and constraints

- **Single user, local only.** No auth, no multi-tenancy, no cloud.
- Keep `ModelService` **UI-free**. The frontend, notebooks, and scripts all
  drive the same service.
- **Tests use `e_coli_core`, never iML1515.** Genome-scale models are for
  manual/interactive use, not the test loop.
- **Solver: Gurobi** (academic license), but the solver string is configurable
  and GLPK must at least not crash on small models.
- Heavy compute is **detachable**: built so it can move to a SLURM cluster later
  with no change to the calling code. Do not build cluster orchestration now —
  build the seam for it.

### Cross-cutting requirements (apply across analysis and strain design)

- **Run manifest.** Every analysis or design run persists a JSON manifest:
  model label + structural hash, the operation and its parameters, solver, time
  limit, package versions, and (for designs) modules, KO/KI candidates and costs,
  interventions, verification results, and EFM verdict. CSV exports are written
  with a companion manifest so a result is never orphaned from its conditions.
- **Solver status is always surfaced.** Report optimal / time-limit / infeasible
  explicitly. For strain design, distinguish "infeasible" from "not found within
  the time limit" and offer a one-click relaxation (raise max size, drop a
  module). Never present a silent empty result.
- **Loopless toggle** on FBA, pFBA, FVA, and the design-verification LP. Required
  input for a trustworthy EFM test (loops inflate the support).

## Architecture

```
ModelService  (cobra wrapper, sessions, edits, FBA/pFBA)  -- synchronous, UI-free
     |  export_model() writes current edited model to disk
     v
JobSpec (JSON, references model by PATH) --> JobBackend
                                              |-- LocalProcessBackend  (now)
                                              |-- SlurmBackend         (later, stub)
                                              `-- runners: run_fva, run_strain_design
Frontend (Dash)  -- holds only session_id + job_id, submits & polls
```

### Decisions already fixed (in the contract files)

1. **Sessions live server-side.** Callers hold a `session_id` string only; the
   live `cobra.Model` never crosses to the UI. (Fixes the rerun-vs-mutable-model
   problem and drops into a Dash `dcc.Store`.) Memory-only; no session
   persistence to disk.
2. **Jobs reference the model by file path, not handle.** `ModelService.export_model()`
   serializes the current *edited* model; the `JobSpec` points at that file. This
   is the local→SLURM seam: a path is portable, a `cobra.Model` is not.
3. **FBA/pFBA are synchronous on `ModelService`. FVA and strain design go
   through the job layer.** `fva()` is still exposed directly for blocking
   notebook use; `JobType` covers only FVA and strain design.
4. **Every edit returns a `ChangeRecord`; the service keeps a change log with
   `reset()`** back to the as-loaded state.
5. **Exchange handling is sign-convention aware** (negative flux = uptake).
   `classify_exchanges()` reports current capability; `toggle_exchange(direction)`
   edits the correct bound. Demands and sinks distinguished from true exchanges.
6. **`JobBackend` is a `Protocol` implemented twice** — local now, SLURM later —
   with identical semantics. Runners are pure `spec -> result` functions, so
   they are backend-agnostic.
7. **Parallelism is across designs/targets, not within a single MILP.** A
   sweep over targets is N independent jobs; one hard MILP gets no cluster
   benefit. The job layer parallelises the former.

### Decisions (fixed at kickoff)

- **Frontend: Dash.** AG Grid (`dash-ag-grid`) for the heavy editable tables;
  `dcc.Store` for session/job ids; callback model for submit-and-poll.
- **Knock-in candidate database: deferred to milestone 6.** Not needed before
  strain design. BiGG universal vs KEGG-derived to be decided then.

## Strain design

Use the **StrainDesign** package (Schneider/Klamt, built on COBRApy). It unifies
MCS, OptKnock, RobustKnock, OptCouple; supports gene- and reaction-level KOs; and
supports knock-ins via a candidate database of addable reactions. Network
compression runs before the MILP — essential at genome scale. See
`StrainDesignParams` in `jobs.py`.

Reality to encode in the UI/docs: MCS enumeration up to size *k* is NP-hard and
explodes; expose `max_size` and `max_solutions` and default them conservatively.

## Suggested layout

```
gem_suite/
  pyproject.toml
  gem_suite/
    __init__.py
    model_service.py        # from the provided contract
    jobs/
      __init__.py
      spec.py               # JobSpec, JobStatus, JobType, StrainDesignParams, JobBackend
      local.py              # LocalProcessBackend (ProcessPool + status store)
      slurm.py              # SlurmBackend (stub, later)
      runners.py            # run_fva(spec)->result, run_strain_design(spec)->result
    strain_design.py        # thin wrapper over the StrainDesign package
    app/
      main.py               # Dash entry
      pages/                # reactions table, exchanges, analysis, strain design
  tests/
    data/                   # e_coli_core only
    test_model_service.py
    test_jobs.py
```

(The provided `jobs.py` is a single starter file; split into `jobs/` as above
when implementing.)

## Dependencies

Python 3.11+. `cobra`, `optlang`, `gurobipy` (academic), `straindesign`,
`dash` + `dash-ag-grid`, `pandas`, `pyarrow` (parquet job results), `pytest`.
Pin in `pyproject.toml`.

## Build order

1. **`ModelService` core over `e_coli_core`:** `load_model`, `summary`,
   `list_reactions`, `get_reaction`, `set_bounds`, `fba`, `pfba`. Tests green.
2. **Exchanges:** `classify_exchanges`, `toggle_exchange`, `set_medium`.
3. **Editing:** `add_reaction`, `remove_reaction`, `set_objective`, change log,
   `reset`, `export_model`.
4. **Jobs:** `LocalProcessBackend` + `runners.run_fva`; submit/poll/cancel; FVA
   result as parquet. `SlurmBackend` left as a conforming stub.
5. **Frontend** over 1–4: model load, editable reactions table, exchanges panel
   with toggles, analysis panel (FBA/pFBA inline, FVA as a job with progress).
   Add: **CSV export** for FBA/pFBA/FVA (+ manifest), a **loopless toggle**, the
   **EFM verdict** on the pFBA solution, **light-gray app background with white
   cards**, and **bold active tab / normal inactive tabs**. Surface solver status.
6. **Strain design** (see `SPEC_strain_design_addendum.md` for the full spec):
   `strain_design.py` + `runners.run_strain_design`; MCS first (KO only), then
   knock-ins via the candidate DB, then OptKnock/OptCouple. Dynamic suppress/
   protect cards with live validation; goal-preset library; KI paste box; a job
   that submits and renders solutions; **post-run per-constraint verification**
   (protect feasible, suppress infeasible) and **EFM check**; per-run manifest.

## Definition of done per milestone

Each milestone: implemented against the contract, unit-tested on `e_coli_core`,
no UI knowledge leaked into `ModelService` or `jobs`, and `JobSpec`/`JobStatus`
remain JSON round-trippable. Every run writes a manifest. For milestone 6, every
goal preset and the EFM test ship with passing tests (see the addendum).
