# GEM Suite — strain design UI, verification & analysis addendum

Extends `SPEC.md`. **Milestones 1–6 are already complete.** Everything here is an
**in-place enhancement** of the existing analysis and strain-design code —
modify the current files, do not rebuild or scaffold anew. Assumes the
`ModelService` and job-layer contracts are implemented.

> **Terminology note:** "dfba" in the request is read as **pFBA** (parsimonious
> FBA). The EFM test runs on the pFBA flux vector. If dynamic FBA is intended,
> stop and re-scope — it has no single flux vector to test for elementarity.

---

## 1. Dynamic suppress / protect constraint UI

Each module is a **card**; each card holds one or more **constraint rows**; each
row is a single free-text linear inequality over reaction IDs.

- Two "+ add module" buttons: **+ suppress**, **+ protect**. Each appends a card.
- Inside a card, "+ add constraint" appends a row; each row has a "×" to remove.
- Build with Dash **pattern-matching callbacks** (`ALL` / `MATCH`) over a
  `dcc.Store` that holds the module list. The stored JSON IS the job input:
  it serializes directly into `StrainDesignParams` from `jobs.py`. No separate
  translation layer.
- Constraint input is plain text, because that is what the solver consumes —
  linear inequalities with coefficients and multiple terms, e.g.
  `BIOMASS_Ecoli_core_w_GAM >= 0.2` or `EX_14bdo_e + 0.3 EX_glc__D_e <= 0`.

### Store shape (feeds StrainDesignParams)

```json
{
  "modules": [
    {"type": "suppress", "constraints": ["EX_14bdo_e + 0.3 EX_glc__D_e <= 0",
                                          "EX_glc__D_e <= -0.1"]},
    {"type": "protect",  "constraints": ["BIOMASS_Ecoli_core_w_GAM >= 0.2"]}
  ],
  "ko_candidates": null,
  "ki_reactions": [...],          // see §3
  "approach": "MCS",
  "gene_level": true,
  "max_solutions": 1,
  "max_size": 30,
  "time_limit_s": 300
}
```

### Live validation (this matters more than help text)

Validate on edit, show inline errors/warnings per row:

1. **Term resolution** — parse each term; flag any reaction ID not in the loaded
   model. This is the most common silent failure.
2. **Exchange sign reminder** — when a term references an exchange reaction, show
   a hint that secretion is positive, uptake negative. Yield constraints get the
   sign wrong constantly.
3. **The v = 0 trap (suppress only)** — a suppress region that does not exclude
   the zero-flux vector is satisfied trivially and the design is meaningless. If
   a suppress module has no constraint that bounds flux away from zero (e.g. a
   minimum uptake or minimum substrate flux), **auto-insert a suggested
   auxiliary row** (commented/removable) and warn. The StrainDesign manual adds
   exactly such an auxiliary uptake constraint for this reason.
4. **Operator/parse** — reject rows that aren't a valid `lhs (<=|>=|=) rhs`.

### "?" popover (terse, example-led — not a manual dump)

One popover each next to the suppress and protect headers:

- **Suppress** — "Make these flux states impossible." Example: forbid product
  yield below a minimum at growth → `EX_prod_e + Ymin*EX_sub_e <= 0`. Remember to
  also exclude zero flux.
- **Protect** — "Keep these flux states reachable." Example: guarantee growth →
  `BIOMASS >= 0.2`.
- Footer link to the StrainDesign MCS manual section. Keep total text under ~6
  lines per popover.

---

## 2. Goal preset library (the real fix for confusion)

A dropdown "design goal" that, on selection, **populates the module cards** with
editable inequalities. Users tweak numbers instead of authoring the
double-negative from scratch. Presets are a **data structure**, not hardcoded
UI, so they are testable (see §8).

```python
# presets.py
@dataclass
class DesignPreset:
    key: str
    label: str
    description: str                 # one line, shown under the dropdown
    approach: str                    # "MCS" | "OptKnock" | ...
    objective: str | None            # for bilevel approaches
    modules: list[dict]              # same shape as the Store, with {sub}/{prod}/{Ymin} placeholders
    notes: str                       # the "why", shown in an info strip

PRESETS = [
  DesignPreset("wgcp",  "Growth-coupled production (weak, wGCP)", ...,
               "MCS", None, [ suppress: low yield at max growth ... ]),
  DesignPreset("pgcp",  "Growth-coupled production (strong, pGCP)", ..., "MCS", ...),
  DesignPreset("sucp",  "Minimum-yield substrate-uptake coupling (SUCP)", ..., "MCS", ...),
  DesignPreset("lethal","Synthetic lethals (prohibit growth)", ..., "MCS", ...),
  DesignPreset("condaux","Conditional auxotrophy (substrate-dependent)", ..., "MCS", ...),
]
```

Placeholders (`{sub}`, `{prod}`, `{Ymin}`) are resolved from small inputs
(product reaction, substrate reaction, minimum yield) shown when a preset is
chosen. These map onto the StrainDesign manual examples (wGCP/pGCP/SUCP/synthetic
lethals), so the presets are documentation-backed, not invented.

---

## 3. Knock-in paste box

A `dcc.Textarea`, one reaction per line:

```
RXN_ID: 1.0 a_c + 2.0 b_c --> c_c          # irreversible
RXN_ID2: x_c <=> y_c                        # reversible
```

- Parse each line into a cobra `Reaction` (BiGG-style metabolite IDs; arrows
  `-->`, `<=>`, optional coefficients defaulting to 1).
- Register parsed reactions as **addable candidates** with a `ki_cost`.
  Mechanically StrainDesign treats reaction/gene additions as inverse knockouts,
  so a knock-in is just an addable carrying a cost.
- **Validation:**
  - **Orphan-metabolite warning** — if a KI introduces a metabolite the model
    does not already contain, warn. A KI adding a metabolite with no other
    producer/consumer is almost always a paste error and silently makes the
    addition useless.
  - **Duplicate ID** against existing reactions → error.
  - **Mass/charge balance** check (recommended) → warn if unbalanced.
- Parsed KIs serialize into the Store under `ki_reactions` and into the job spec.

---

## 4. Post-run verification (FBA / feasibility tests per constraint)

After each computed design, verify it actually does what it claims. For every
returned intervention, build the intervened model (apply KOs as `lb=ub=0` on the
chosen level; add the selected KIs), then test **each module constraint**:

- **PROTECT** → the LP with the protect constraints applied must be **feasible**.
  PASS if feasible, FAIL otherwise. Also run an FBA and report the achieved
  objective/flux for context.
- **SUPPRESS** → the LP with the suppress constraints applied (including the
  v ≠ 0 auxiliary) must be **infeasible**. PASS if infeasible, FAIL if a feasible
  flux exists.

Render a per-constraint **pass/fail table** under each design. The pass/fail is
feasibility-based; the reported flux/objective is informational.

- Run the verification FBA **loopless** (or expose a toggle), so thermodynamically
  infeasible internal loops don't produce a misleading "feasible" flux.
- This step catches solver and network-compression edge cases and gives the user
  confidence the design is real — cheap insurance on an NP-hard search.

---

## 5. EFM test on the pFBA solution

Exact criterion as specified: a flux vector is an elementary flux mode iff the
stoichiometric submatrix on its support, after dropping all-zero metabolite rows,
has **one more column than its row rank** (i.e. nullity 1).

```python
import numpy as np

def is_elementary_flux_mode(N, v, tol=1e-9):
    """N: stoichiometric matrix (rows=metabolites, cols=reactions).
       v: flux vector aligned to N's columns."""
    support = np.where(np.abs(v) > tol)[0]          # remove unused reactions
    if support.size == 0:
        return False, {"n_active": 0, "rank": 0, "nullity": 0, "reason": "zero flux"}
    Nsub = N[:, support]
    nz_rows = np.any(np.abs(Nsub) > tol, axis=1)     # remove all-zero rows
    Nred = Nsub[nz_rows, :]
    rank = int(np.linalg.matrix_rank(Nred, tol=tol))
    ncols = Nred.shape[1]
    nullity = ncols - rank
    return (nullity == 1), {"n_active": ncols, "rank": rank, "nullity": nullity}
```

- Report in the UI: **"Solution is an EFM"** / **"Solution is not an EFM"**, with
  the triple `(active reactions, rank, nullity)` shown for transparency.
- Edge cases: zero flux → not an EFM; nullity 0 → degenerate/numerical (flag);
  nullity > 1 → decomposable, not elementary.
- One-line caveat in the help text: this is the rank/nullity-1 criterion; loops
  in a non-loopless pFBA solution can inflate the support, so prefer the loopless
  pFBA flux as the EFM-test input.

---

## 6. CSV export for FBA, pFBA, FVA

Each analysis panel gets an **Export CSV** button via `dcc.Download` +
`pandas.to_csv`.

- **FBA / pFBA columns:** `reaction_id, reaction_name, subsystem, flux,
  lower_bound, upper_bound`.
- **FVA columns:** `reaction_id, reaction_name, min_flux, max_flux, span,
  fraction_of_optimum`.
- Filenames: `{model_label}_{analysis}_{YYYYMMDD-HHMM}.csv`.
- Write a companion `{...}_manifest.json` (see §9) so a CSV is never orphaned
  from the conditions that produced it.

---

## 7. Styling

- **App background → light gray.** Set the app container background to a neutral
  light gray (e.g. `#EFEFF1`); keep content **cards white** so tables and the
  emerald header stay legible. Verify text contrast (the `#0F2A24` ink on gray is
  fine).
- **Active tab bold, others normal.** With `dcc.Tabs`, give the selected tab
  `font-weight: 700` via `selected_style`/`selected_className` and inactive tabs
  `font-weight: 400`. No other weight changes.

---

## 8. Testing requirements (Claude Code must do during the build)

Hard requirements, all on `e_coli_core` (or the small extended model a preset
needs, e.g. an e_coli_core + 1,4-BDO pathway for SUCP):

1. **Every preset template is tested.** For each `DesignPreset`: resolve
   placeholders, build modules, run a single-solution short-timelimit design,
   and assert either a solution is found or a defined "no solution" is handled
   cleanly. Then run §4 verification and assert all protect/suppress checks pass.
   No preset ships untested.
2. **EFM test** — unit tests on a hand-built tiny network: one case with a known
   elementary mode (assert True) and one with a superposition of two modes
   (assert False); plus zero-flux and degenerate edge cases.
3. **KI parser** — round-trip parse tests, orphan-metabolite warning, duplicate
   ID error, unbalanced-reaction warning.
4. **Verification logic** — a design known to be growth-coupled passes; a
   deliberately wrong intervention fails the suppress check.
5. **CSV export** — assert headers and row count match the result object.
6. **Validation** — unknown reaction ID flagged; suppress module missing the
   v ≠ 0 auxiliary is detected.

---

## 9. Recommended additions (answering "anything else?")

Worth doing now, low cost, high value given how you work:

- **Run manifest (do this now).** Per design run, persist a JSON: model label +
  structural hash, full module definitions, KO/KI candidates and costs, approach,
  solver, time limit, max size/solutions, package versions, every returned
  intervention, the §4 verification table, and the §5 EFM result. This is the
  reproducibility backbone and pairs with the CSV exports.
- **Solver status + infeasibility diagnosis.** Surface MILP status (optimal /
  time-limit / infeasible) prominently. On "no solution," the usual cause is an
  over-constrained protect+suppress combination or essential reactions excluded
  by protection — offer a one-click relaxation (raise max size, drop a module) to
  distinguish "infeasible" from "not found in time."
- **Loopless toggle** on FBA/pFBA/FVA and the verification step — you'll want it
  for the EFM test specifically.
- **"Copy run as Python."** Emit the equivalent `straindesign` script for the
  current modules/KIs/settings, so a design can be reproduced or batched in a
  notebook. Fits your script-driven workflow and the `ModelService`-is-also-an-API
  design.

Defer unless needed:

- **FVA-under-design** — after a design, show the product/growth flux ranges of
  the intervened model (confirms the coupling visually). Nice, not essential.
- **Charge/mass-balance report** across pasted KIs as a batch check.

---

## Definition of done (this addendum)

Suppress/protect cards with dynamic +/− rows and live validation; preset library
populating modules; KI paste box with parser and warnings; post-run per-constraint
verification table; EFM verdict on the pFBA solution; CSV export for FBA/pFBA/FVA
with manifest; light-gray background with white cards; bold active tab. All
presets and the EFM test covered by passing `pytest` on `e_coli_core`.
