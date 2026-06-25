# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**All milestones (1–6) are done.** The package is scaffolded (`pyproject.toml`, `gem_suite/` package, `tests/`) and `ModelService` is implemented and tested on `e_coli_core`:
- M1 core: `load_model`, `summary`, `list_reactions`, `get_reaction`, `set_bounds`, `fba`, `pfba`, plus the session store and `close_session`/`list_sessions`/`change_log`.
- M2 exchanges: `classify_exchanges`, `toggle_exchange`, `set_medium` (sign-convention aware; positive flux = secretion, negative = uptake; toggle preserves existing open magnitudes and falls back to `DEFAULT_BOUND=1000`).
- M3 editing: `add_reaction`, `remove_reaction`, `set_objective`, `reset`, `export_model`. Each edit appends a `ChangeRecord`. `reset()` restores from an as-loaded `model.copy()` snapshot taken at load (decoupled from disk; the snapshot stays pristine across repeated resets). `export_model` writes SBML/JSON/MAT — this is the bridge to the job layer.
- M4 jobs: `jobs.py` split into the `gem_suite/jobs/` package — `spec.py` (contract types), `runners.py` (pure `run_fva`; `execute_job`/`read_result` dispatch; FVA↔parquet serde), `local.py` (`LocalProcessBackend`, ProcessPool with a **spawn** context + in-memory status store), `slurm.py` (conforming stub, all methods raise). `ModelService.fva()` is implemented for blocking use and shares the `compute_fva` helper in `model_service.py` with `run_fva` (no circular import: runners→model_service only). FVA results persist as parquet (scalars in schema metadata).

- M5 frontend: `gem_suite/app/` Dash app driving a **live in-process `ModelService` + `LocalProcessBackend`**. Logic lives in `app/controllers.py` (plain functions taking an explicit `service`/`backend`, JSON-able returns — this is the unit-tested surface); `app/pages/{load,reactions,exchanges,analysis}.py` provide pure `layout()` + thin `register_callbacks(app, service, backend)`; `app/main.py:create_app(service=None, backend=None)` wires shared `dcc.Store`s (`session-store` = the browser's only model handle; `job-store`) and tabs. Reactions use an editable `dash-ag-grid`; FBA/pFBA run inline; FVA submits a job and polls via `dcc.Interval`. Solver via `GEM_SUITE_SOLVER` env (default `gurobi` — see the Solver section). No browser/E2E tests (selenium is heavy); callbacks are thin over tested controllers, and a build test asserts the app constructs.

- M6 strain design: `gem_suite/strain_design.py` is a thin wrapper over the **StrainDesign** package (`design_strains(model, params, solver)`, lazy `import straindesign` so core/jobs import without it). Supports MCS (growth-coupled production via a SUPPRESS module `biomass>=min_growth ∧ target<=min_yield`), OptKnock/RobustKnock/OptCouple, reaction- and gene-level KOs, and KIs (merging candidate reactions from `ki_database`); `compress=True` runs network compression before the MILP. `runners.run_strain_design` + JSON artifact serde (`result_suffix` makes the local backend pick `.json` for strain design vs `.parquet` for FVA). Results are `StrainDesignResult`/`StrainDesignSolution` dataclasses (JSON round-trippable). App page `app/pages/strain_design.py` + controllers submit a job and render the solution sets; `max_size`/`max_solutions` are exposed and defaulted conservatively.

The contract `model_service.py` was relocated from the repo root into `gem_suite/gem_suite/model_service.py` and implemented in place; `jobs.py` was likewise relocated into `gem_suite/jobs/`. The only `ModelService` method still `NotImplementedError` is `clone_session` (no milestone requires it). `SlurmBackend` remains a conforming stub by design (the seam, implemented later).

**Job workers use a `spawn` context**, so any script that starts the app/backend MUST guard its entry with `if __name__ == "__main__":` (as `app/main.py` does) — otherwise spawned workers re-import and re-run it, crashing with `BrokenProcessPool`.

`SPEC.md` is the authoritative brief. Read it before starting any milestone. The "Build order" and "Definition of done per milestone" sections there are the work plan.

## What "GEM Suite" is

A single-user, local-only tool for analysing genome-scale metabolic models (GEMs) via COBRApy: load a model, edit reaction bounds / add / remove reactions, change the objective, classify and toggle exchange reactions, and run FBA / pFBA / FVA, with strain design (knock-outs **and** knock-ins) as the final milestone.

## Architecture and the invariants that must not be violated

The whole design exists to keep heavy compute detachable to a SLURM cluster later **without changing calling code**. The seams below are the point of the project — preserve them.

- **`ModelService` is UI-free.** No Dash/Panel/notebook knowledge leaks into `model_service.py` or `jobs.py`. The same service is driven by the frontend, notebooks, and scripts. Keeping this clean is part of every milestone's definition of done.

- **Sessions live server-side; callers hold only a `session_id` string.** The live `cobra.Model` never crosses to the UI (it would break Dash's rerun model and isn't serializable). Sessions are memory-only — no persistence to disk.

- **Jobs reference the model by file PATH, never by in-memory handle.** This is the local→SLURM seam: a path is portable across processes/nodes on a shared filesystem, a `cobra.Model` is not. `ModelService.export_model()` serializes the *current edited* model to disk; the `JobSpec` points at that file. Never try to pass a model object into the job layer.

- **`JobSpec` and `JobStatus` must stay JSON round-trippable.** All value types (`FluxResult`, `FVAResult`, `ChangeRecord`, `ExchangeInfo`, etc.) are deliberately plain dataclasses/enums so they cross the UI and job boundaries. Don't add non-serializable fields.

- **Fast vs slow split is fixed.** FBA and pFBA are **synchronous** methods on `ModelService`. FVA and strain design go through the job layer (`JobType` covers only those two). `ModelService.fva()` is still exposed directly for blocking notebook use, but the UI drives FVA as a job.

- **`JobBackend` is a `Protocol` implemented twice** — `LocalProcessBackend` (now) and `SlurmBackend` (later, a conforming stub for now) — with identical semantics. **Runners are pure `spec -> result` functions** (`run_fva`, `run_strain_design`) so they are backend-agnostic. Do not build cluster orchestration now; build the seam.

- **Parallelism is across designs/targets, not within a single MILP.** A sweep over targets is N independent jobs; one hard MILP gets no cluster benefit. Parallelise the former in the job layer.

- **Every edit returns a `ChangeRecord`** and is appended to a per-session change log; `reset()` reverts to the as-loaded state.

- **Exchange handling is sign-convention aware:** negative flux = uptake. `classify_exchanges()` reports current capability from the bounds and distinguishes true exchanges from demands and sinks; `toggle_exchange(direction)` edits the correct bound.

## Solver

Gurobi (academic license) is the default, but the solver string is **configurable** (`ModelService(solver=...)`, `JobSpec.solver`). GLPK must at least not crash on small models — don't hard-code Gurobi-only assumptions.

**Gurobi license:** an academic, host-locked `gurobi.lic` lives in the repo root (gitignored — it holds a secret KEY). `gem_suite/__init__.py:_bootstrap_gurobi_license()` sets `GRB_LICENSE_FILE` to it on import (via `setdefault`, so an explicit env var wins), so the app/notebooks/scripts pick it up with no setup. `gurobipy` (v13, matching the license) is the `.[gurobi]` extra; install it to use Gurobi. The dev venv `/home/gus/envs/gem_suite` has it installed. **The license is node-locked to this machine and expires 2027-06-25** — it won't validate elsewhere; set `GEM_SUITE_SOLVER=glpk` there. The **test suite still pins GLPK** (the testing constraint below is unchanged).

## Testing constraint (important)

**Tests use `e_coli_core`, never iML1515.** Genome-scale models are for manual/interactive use only, never the automated test loop (they are too slow and need Gurobi). Test data lives under `tests/data/` and must stay small.

## Intended layout (from SPEC.md — build toward this)

The single starter file `jobs.py` is to be split into a `jobs/` package when implementing:

```
gem_suite/
  pyproject.toml
  gem_suite/
    model_service.py        # the provided contract
    jobs/
      spec.py               # JobSpec, JobStatus, JobType, StrainDesignParams, JobBackend
      local.py              # LocalProcessBackend (ProcessPool + status store)
      slurm.py              # SlurmBackend (stub, later)
      runners.py            # run_fva(spec)->result, run_strain_design(spec)->result
    strain_design.py        # thin wrapper over the StrainDesign package
    app/                    # Dash entry + pages (reactions, exchanges, analysis, strain design)
  tests/
    data/                   # e_coli_core only
```

## Frontend

Dash, with `dash-ag-grid` (AG Grid) for the heavy editable tables, `dcc.Store` for session/job ids, and a callback-based submit-and-poll model. The frontend holds only `session_id` + `job_id`.

## Strain design (milestone 6)

Use the **StrainDesign** package (Schneider/Klamt, on COBRApy) — unifies MCS, OptKnock, RobustKnock, OptCouple; gene- and reaction-level KOs; knock-ins via a candidate database of addable reactions. Network compression runs before the MILP (essential at genome scale). MCS enumeration up to size *k* is NP-hard and explodes, so `max_size` and `max_solutions` must be exposed and defaulted conservatively. The knock-in candidate database (BiGG universal vs KEGG-derived) is deferred to this milestone.

## Dependencies and commands

Python 3.11+. Planned deps (pin in `pyproject.toml` when created): `cobra`, `optlang`, `gurobipy`, `straindesign`, `dash`, `dash-ag-grid`, `pandas`, `pyarrow` (parquet job results), `pytest`.

Python 3.11+. Development uses the venv at `/home/gus/envs/gem_suite` (activate with `source /home/gus/envs/gem_suite/bin/activate`).

- **Install (editable):** `pip install -e .` — core deps (`cobra`, `optlang`, `pandas`, `scipy` for MAT IO, `pyarrow` for job-result parquet). Feature deps are extras: `.[dev]` (pytest), `.[app]` (dash, dash-ag-grid), `.[strain]` (straindesign — lazy-imported, pulls matplotlib), `.[gurobi]` (gurobipy). To run the full test suite + app + strain design here: `pip install -e ".[dev,app,strain]"`.
- **Test:** `pytest` (config in `pyproject.toml`; `testpaths=tests`). Single test: `pytest tests/test_model_service.py::test_fba`.
- **Run the app:** `python -m gem_suite.app.main` or the `gem-suite-app` console script (needs `.[app]`). Defaults to `http://127.0.0.1:8050`; override the solver with `GEM_SUITE_SOLVER=...`.
- **Solver:** the dev venv has **GLPK only** (no Gurobi license here), so tests instantiate `ModelService(solver="glpk")`. The library default stays `gurobi` per SPEC.
