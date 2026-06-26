# CLAUDE.md — GEM Suite

Single-user, local GEM analysis suite. COBRApy backend, Dash frontend. Full spec
in `SPEC.md`; strain-design detail in `SPEC_strain_design_addendum.md`. Those
docs are the source of truth — read them before non-trivial work.

**Status: milestones 1–6 are complete.** Current work is the additions in
`SPEC_strain_design_addendum.md` — modify existing files in place, do not rebuild.

## Fixed decisions (do not relitigate)

- **`ModelService` is UI-free.** Frontend, notebooks, and scripts all drive it.
  No Dash/HTTP knowledge in `ModelService` or `jobs`.
- **Sessions live server-side**; callers hold a `session_id` string only. Live
  `cobra.Model` never crosses to the UI. Memory-only, no session persistence.
- **Jobs reference the model by file path, never by handle.**
  `ModelService.export_model()` is the bridge. This is the local→SLURM seam.
- **FBA/pFBA synchronous on `ModelService`; FVA and strain design go through the
  job layer.** `JobType` covers only FVA and strain design.
- **`JobBackend` is a Protocol**, implemented `LocalProcessBackend` now,
  `SlurmBackend` (stub) later. Runners are pure `spec -> result`.
- **Parallelism is across designs/targets, not within one MILP.**
- **Solver: Gurobi** (academic), configurable; GLPK must not crash on small models.
- **Frontend: Dash** + `dash-ag-grid`; `dcc.Store` holds session/job ids and the
  strain-design module list (that JSON IS the job input).

## Naming

- "dfba" always means **pFBA** (parsimonious FBA), not dynamic FBA. The EFM test
  runs on the pFBA flux vector (prefer the loopless solution).

## Cross-cutting requirements

- **Run manifest** (JSON) for every analysis/design run: model label + hash,
  params, solver, versions, and for designs the modules/KO/KI/costs,
  interventions, verification, EFM verdict. CSV exports get a companion manifest.
- **Always surface solver status**; distinguish "infeasible" from "not found in
  time limit"; offer relaxation. Never return a silent empty result.
- **Loopless toggle** on FBA/pFBA/FVA and the verification LP.

## UI specifics

- App background **light gray**, content **cards white**, emerald header.
- **Active tab bold (700), inactive normal (400).**
- Strain design: dynamic suppress/protect cards (Dash pattern-matching `ALL`/
  `MATCH`), free-text inequality rows, **live validation** (unknown reaction IDs;
  exchange sign; suppress must exclude the v=0 vector — auto-insert/warn).
- **Goal presets** populate modules from documented StrainDesign cases
  (wGCP/pGCP/SUCP/synthetic-lethal/conditional-auxotrophy). Presets are data, not
  hardcoded UI.
- **KI paste box**: `RXN_ID: stoich` with `-->`/`<=>`; warn on orphan
  metabolites, duplicate IDs, unbalanced reactions.
- **Post-run verification**: protect region must be feasible, suppress region
  must be infeasible, on the intervened model. Render a per-constraint pass/fail
  table. Verdict is feasibility-based; reported flux is informational.
- **EFM test**: on the pFBA support submatrix (drop unused reactions, then
  all-zero rows), EFM iff columns == rank + 1 (nullity 1). Report (active, rank,
  nullity).

## Testing (hard rules)

- All tests run on `e_coli_core` (or a small extended model a preset needs).
  Never load iML1515 in tests.
- **Every goal preset is tested**: build it, run a short single-solution solve,
  run verification, assert protect/suppress pass. No preset ships untested.
- EFM test has unit tests: a known EFM (True), a two-mode superposition (False),
  plus zero-flux and degenerate edge cases.
- KI parser, CSV export, and validation rules each have tests.
- `JobSpec`/`JobStatus` stay JSON round-trippable.

## Workflow

- Use plan mode for non-trivial changes; show diffs.
- When I correct you, add the rule here so it doesn't recur.
- Keep this file short.
