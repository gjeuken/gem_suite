# User guide

This is the main manual. It starts with a plain-language **concepts primer**, then
walks through every tab of the app with worked examples on the *E. coli* core
model (`e_coli_core`, 95 reactions). Everything here is also available as a Python
API — see [Under the hood](under-the-hood.md).

---

## Concepts primer (read this first)

**A metabolic model** is a list of biochemical reactions. Each reaction converts
*metabolites* into other metabolites with fixed proportions (stoichiometry), and
each carries a *flux* `v` — the rate it runs — bounded by a lower and upper bound:

```
lower_bound  ≤  v  ≤  upper_bound
```

**Steady state.** Constraint-based modelling assumes the cell is balanced: every
internal metabolite is produced and consumed at the same rate (`S·v = 0`, where
`S` is the stoichiometric matrix). This plus the bounds defines a *space* of all
feasible flux distributions.

**FBA (Flux Balance Analysis)** picks, out of that space, the flux distribution
that **maximizes an objective** — usually the *biomass* reaction, a pseudo-reaction
that drains precursors in the proportions needed to grow. The objective value is
then the predicted growth rate. FBA is a linear program (LP).

**pFBA (parsimonious FBA)** first finds the maximum objective, then, among all
flux distributions achieving it, picks the one with the **smallest total flux** —
the "laziest" way to reach the optimum. It gives a cleaner, more unique flux map.
(In this project's notes, "dfba" always means pFBA, never dynamic FBA.)

**FVA (Flux Variability Analysis)** asks, for each reaction, *what is the minimum
and maximum flux it can carry* while staying at (or near) the optimum. The width
of that range — the **span** — tells you how flexible each reaction is.

**Exchange reactions** are the cell's doors to the environment. By convention a
boundary reaction is written `metabolite ⇌`, so:

- **negative flux = uptake** (metabolite enters the cell),
- **positive flux = secretion** (metabolite leaves).

Opening or closing these (the *medium*) decides what the cell can eat and excrete.

**Loopless.** Plain FBA can contain thermodynamically impossible internal loops
(flux going round a cycle for free). A *loopless* solution removes them. It costs
more to compute but gives physically meaningful fluxes — important for the EFM
test below.

**Strain design** asks the engineering question: *which genes/reactions should I
knock out (remove) or knock in (add) so the cell is forced to make my product?*
The suite uses the StrainDesign package, which frames this with **modules**:

- a **suppress** module describes flux states you want to make **impossible**
  (e.g. "grow without making product"),
- a **protect** module describes states you want to keep **possible**
  (e.g. "still able to grow").

It then finds the smallest set of interventions (a *minimal cut set*, MCS) — or,
with OptKnock/OptCouple, an intervention that maximizes production at the
growth optimum.

**EFM (Elementary Flux Mode).** A flux distribution is "elementary" if it cannot
be decomposed into smaller independent pathways — the simplest possible route
through the network. The suite reports whether a pFBA solution is an EFM.

---

## The app at a glance

A model lives in a server-side **session**; the browser holds only its id. Tabs:

| Tab | What it does |
|---|---|
| **Load** | Upload or pick a model file; see its summary. |
| **Reactions** | Browse/edit reaction bounds, add reactions, export SBML. |
| **Exchanges** | Classify boundary reactions and open/close uptake/secretion. |
| **Analysis** | Run FBA/pFBA (inline) and FVA (as a job); see binding constraints, an EFM verdict, a schematic flux diagram; export CSV. |
| **Scan** | Plot a response (objective or any flux) vs one or two scanned fluxes. |
| **Strain design** | Build suppress/protect modules (or pick a preset), add knock-in candidates, run a design job, and verify the results. |

Edits accumulate in the session and are reverted by **reset**. Every analysis can
write a **run manifest** (a JSON record of model + parameters + versions) so a
result is never separated from the conditions that produced it.

---

## Load

1. **Drag & drop** a model file (SBML `.xml`/`.xml.gz`, JSON, or MATLAB `.mat`) or
   click to browse. Alternatively expand *"load a server-side file by path"* and
   type a path (handy for large genome-scale files already on disk).
2. The summary shows counts, the active objective, its direction (max/min), and the
   solver in use.

> Try it: load `tests/data/e_coli_core.xml.gz` → 95 reactions, 72 metabolites,
> 137 genes, objective `Biomass_Ecoli_core (max)`.

The uploaded file is written to a temp path and loaded **by path**, so the rest of
the suite treats local uploads and server files identically.

---

## Reactions

An editable table of every reaction: id, name, equation, lower/upper bounds,
subsystem, GPR (gene–protein–reaction rule).

- **Filter** by id or name (regex) with the search box.
- **Edit a bound** by double-clicking the LB or UB cell. The change is applied to
  the live model immediately and logged (use **reset** to undo all edits).
- **Add a reaction** (expand *"➕ Add a reaction"*): give it an id, optional name,
  and an **equation** using BiGG-style metabolite ids and an arrow:
  - `-->` irreversible, `<=>` reversible (coefficients optional, default 1):
    `atp_c + h2o_c --> adp_c + pi_c + h_c`
  - Leave LB/UB blank to default from reversibility (`0..1000` or `-1000..1000`).
  - Tick **create missing metabolites** to introduce species the model doesn't
    have yet (otherwise an unknown metabolite is rejected — a useful guard against
    typos).
- **Export SBML** downloads the *current edited* model (added reactions and bound
  changes included) as an `.xml` file.

> Try it: add `ATPSINK: atp_c --> adp_c + pi_c + h_c`, then Export SBML and
> reload the file — your reaction is there.

---

## Exchanges

Boundary reactions are classified as **exchange**, **demand**, or **sink**, with
their current capability read from the bounds (`uptake`, `secretion`, `both`, or
`blocked`).

- Select a row, choose a direction, and **Apply toggle** to open/close it. The
  sign convention is handled for you: choosing *uptake* sets a negative lower
  bound, *secretion* a positive upper bound, *blocked* closes both. Existing
  magnitudes are preserved where possible.

> Try it: block `EX_glc__D_e` (glucose) → re-run FBA on the Analysis tab and the
> model is infeasible (no carbon source to meet ATP maintenance). Reset to undo.

---

## Analysis

### FBA / pFBA (instant)

Pick the **objective** first (see below), then click **Run FBA** or **Run pFBA**.
Optionally tick **loopless**. You get:

- the objective value and solver status,
- the **flux table** (active fluxes, sortable),
- a **schematic cell diagram**: uptake arrows enter from the left, secretion exits
  on the right, each labelled with its flux. If the objective is the biomass
  reaction, growth is drawn as an extra outgoing (purple) arrow,
- a **binding-constraints** table — the reactions whose flux sits exactly on a
  bound at the optimum (the inequality is "met" / tight). For FBA these come with
  *reduced costs*, which flag bounds that are genuinely **limiting** the objective
  (e.g. glucose pinned at −10, ATP maintenance at 8.39),
- an **EFM verdict** on the pFBA solution (with active/rank/nullity).

#### Choosing the objective (single flux or a linear combination)

The **Objective** box is a multi-select dropdown:

- pick **one** reaction → maximize/minimize that flux,
- pick **several** → a coefficient field appears for each, letting you build a
  **weighted linear combination**, e.g. `1·EX_succ_e + 0.5·EX_ac_e`,
- choose **max** or **min**, then **Set objective**.

The objective is a property of the model, so it also drives pFBA, FVA, and the
scan. The current objective is always shown beneath the box.

### FVA (as a job)

Enter an optional reaction list (blank = all), a *fraction of optimum*
(e.g. `0.9` allows 90%-optimal states), and **loopless** if wanted, then
**Submit FVA**. It runs as a background job and polls until done, showing:

- a **range table** (`min`, `max` per reaction),
- a **span plot**: a horizontal bar per reaction with a **non-zero span**, drawn
  from its min to its max (widest first).

### CSV export (+ manifest)

Each panel has an **Export CSV** button. The download is a **ZIP** containing the
CSV *and* a companion `*_manifest.json` (model label + structural hash, parameters,
solver, status, package versions) so the numbers are always traceable.

---

## Scan (phenotypic phase planes / robustness)

Pin one or two reactions across a range and watch a **response** change.

1. Pick **flux 1** (and tick *"scan a second flux"* for a 3-D surface), with a
   **min**, **max**, and number of **points**.
2. Choose what to **plot (response)**: the **objective** (default) or **any
   reaction's flux** — e.g. how CO₂ secretion varies as glucose uptake changes.
3. **Run scan** → a 2-D line (one flux) or a 3-D surface (two fluxes).

At each grid point the scanned reaction(s) are fixed and the model re-optimized;
infeasible points appear as gaps. Your session's bounds are **not** modified.

> Try it: scan `EX_glc__D_e` from −10 to −2 with response = objective → growth
> falls roughly linearly with carbon supply.

---

## Strain design

The most powerful tab. You describe a metabolic-engineering goal as **modules**,
the suite computes interventions, and then **verifies** them.

### The fast path: goal presets

Choose a **design goal** from the dropdown, set the **product** and **substrate**
exchange reactions and a **minimum yield**, and click **Apply preset**. The preset
fills in editable suppress/protect cards for you. Available presets map to the
StrainDesign manual's cases:

- **wGCP / pGCP** — growth-coupled production (weak/strong),
- **SUCP** — minimum-yield substrate-uptake coupling,
- **synthetic lethals** — interventions that prohibit growth,
- **conditional auxotrophy** — make growth depend on a substrate.

### Building modules by hand

- **+ suppress** / **+ protect** add cards. Inside a card, **+ add constraint**
  adds a free-text linear inequality over reaction ids, e.g.
  `EX_etoh_e + 0.2 EX_glc__D_e <= 0` or `Biomass_Ecoli_core >= 0.1`.
- **Live validation** flags unknown reaction ids, reminds you of the exchange sign
  convention, and warns about the **v = 0 trap**: a suppress region that still
  allows the all-zero flux vector is meaningless (add a minimum-uptake term).
- **Suppress** = "make these states impossible." **Protect** = "keep these states
  possible." The "?" helper shows examples.

### Knock-in candidates

Paste reactions to offer as additions, one per line, in the same equation format
as the Reactions tab (`RXN: a_c + b_c --> c_c`). They're parsed and validated
(orphan metabolites, duplicate ids, mass/charge balance) and offered to the
solver as addable interventions.

### Settings and running

Choose the **approach** (MCS / OptKnock / RobustKnock / OptCouple), gene- vs
reaction-level knock-outs, **max size** (cut-set size cap) and **max solutions**
(both default conservatively — MCS enumeration explodes), an optional time limit
and KO candidate list. **Submit** runs a background job.

> ⚠️ Strain design is genuinely hard (NP-hard MILPs). Keep max size/solutions
> small, restrict KO candidates, and prefer Gurobi for genome-scale models.

### Results, verification, EFM, manifest

When the job finishes you get a **solutions table** (knock-outs, knock-ins, cost),
and for each solution:

- a **verification** result — the suite rebuilds the intervened model and checks
  each module: a **protect** region must stay **feasible**, a **suppress** region
  must become **infeasible**. The per-constraint pass/fail is shown for solution 1.
  This catches solver/compression edge cases — cheap insurance on an expensive
  search.
- an **EFM** verdict on the intervened solution.

**Download manifest** saves a JSON of the whole run (modules, KO/KI, every
intervention, verification, EFM, versions) for reproducibility.

If no design is found, the status says so explicitly (distinguishing "infeasible"
from "not found in the time limit") — never a silent empty result.

---

## Tips & gotchas

- **Reset** reverts *all* edits (bounds, added/removed reactions, objective,
  medium) to the as-loaded state.
- The **objective is global**: setting it on Analysis or Scan affects every
  analysis of that session.
- **Exchange signs** trip everyone up: uptake is **negative**. Yield constraints
  like `EX_prod_e + Ymin·EX_sub_e <= 0` rely on the substrate term being negative.
- **GLPK vs Gurobi**: GLPK is fine for `e_coli_core`; switch to Gurobi for
  genome-scale FVA and strain design.
- Want to script an analysis you built in the UI? Every action is a `ModelService`
  call — see [Under the hood](under-the-hood.md).
