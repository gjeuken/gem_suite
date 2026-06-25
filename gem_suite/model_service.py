"""ModelService: UI-agnostic wrapper over COBRApy.

Design contract for the GEM analysis suite. Implement against this interface;
do not add UI knowledge here. The same service is driven by the Dash/Panel
frontend, by notebooks, and by scripts.

Key decisions (see SPEC.md):
- Sessions live server-side; callers hold only a serializable `session_id`.
- Edits are logged as ChangeRecords; `reset()` reverts to as-loaded state.
- Fast analyses (FBA/pFBA) are synchronous here. Slow ones (FVA, strain
  design) are normally driven through the job layer (jobs.py); `export_model`
  is the bridge — it writes the current edited model to disk for a worker.

Implementation status: milestone 1 (core: load/summary/list/get/set_bounds/
fba/pfba) plus the session store. Methods for later milestones raise
NotImplementedError until their milestone lands.
"""
from __future__ import annotations

import math
import os
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import cobra
from cobra import Metabolite, Reaction
from cobra.flux_analysis import pfba as _cobra_pfba
from cobra.io import (
    load_json_model,
    load_matlab_model,
    read_sbml_model,
    save_json_model,
    save_matlab_model,
    write_sbml_model,
)


# --------------------------------------------------------------------------- #
# Value types — all JSON-serializable so they cross the UI / job boundaries.
# --------------------------------------------------------------------------- #

class ExchangeDirection(str, Enum):
    UPTAKE = "uptake"        # negative-flux convention for boundary reactions
    SECRETION = "secretion"
    BOTH = "both"
    BLOCKED = "blocked"


@dataclass
class ExchangeInfo:
    reaction_id: str
    metabolite_id: str
    name: str
    lower_bound: float
    upper_bound: float
    direction: ExchangeDirection   # current capability implied by the bounds
    kind: str                      # "exchange" | "demand" | "sink"


@dataclass
class FluxResult:
    objective_value: float
    status: str                    # optlang status, e.g. "optimal"
    fluxes: dict[str, float]
    reduced_costs: Optional[dict[str, float]] = None
    shadow_prices: Optional[dict[str, float]] = None


@dataclass
class FVAResult:
    status: str
    ranges: dict[str, tuple[float, float]]   # reaction_id -> (min, max)
    fraction_of_optimum: float
    loopless: bool


@dataclass
class ChangeRecord:
    op: str                        # "set_bounds" | "add_reaction" | "remove_reaction" | ...
    target: str                    # reaction / metabolite / objective id
    before: dict
    after: dict


# --------------------------------------------------------------------------- #
# Internal session record (server-side only; never crosses to the caller).
# --------------------------------------------------------------------------- #

@dataclass
class _Session:
    session_id: str
    label: str
    model: cobra.Model
    original: cobra.Model          # as-loaded snapshot; reset() restores from this
    source: str                    # path the model was loaded from
    fmt: str                       # detected format: "sbml" | "json" | "mat"
    changes: list[ChangeRecord] = field(default_factory=list)
    last_fluxes: Optional[dict[str, float]] = None   # cache for get_reaction


DEFAULT_BOUND = 1000.0   # cobra's default flux magnitude for an open bound


def _direction_from_bounds(lower: float, upper: float) -> ExchangeDirection:
    """Current capability of a boundary reaction from its bounds.

    Boundary reactions carry their metabolite as the reactant (`met <=>`), so by
    the sign convention positive flux = secretion and negative flux = uptake.
    """
    can_uptake = lower < 0
    can_secrete = upper > 0
    if can_uptake and can_secrete:
        return ExchangeDirection.BOTH
    if can_uptake:
        return ExchangeDirection.UPTAKE
    if can_secrete:
        return ExchangeDirection.SECRETION
    return ExchangeDirection.BLOCKED


def _detect_format(source: str) -> str:
    """Map a path's extension onto a cobra loader key."""
    lower = source.lower()
    if lower.endswith((".xml", ".sbml", ".xml.gz", ".sbml.gz")):
        return "sbml"
    if lower.endswith((".json", ".json.gz")):
        return "json"
    if lower.endswith(".mat"):
        return "mat"
    raise ValueError(
        f"Cannot infer model format from {source!r}; "
        "expected an .xml/.sbml, .json, or .mat file."
    )


def _linspace(lo: float, hi: float, n: int) -> list[float]:
    """`n` evenly spaced values from lo to hi inclusive (n>=1)."""
    if n < 1:
        raise ValueError("points must be >= 1")
    if n == 1:
        return [float(lo)]
    step = (hi - lo) / (n - 1)
    return [float(lo + step * i) for i in range(n)]


def read_model_file(source: str) -> cobra.Model:
    """Load a cobra model from an SBML / JSON / MAT path (format from extension).

    Module-level so the job layer can load a model from a path without a
    ModelService instance (the local->SLURM seam: jobs reference a file).
    """
    fmt = _detect_format(source)
    if fmt == "sbml":
        return read_sbml_model(source)
    if fmt == "json":
        return load_json_model(source)
    if fmt == "mat":
        return load_matlab_model(source)
    raise ValueError(f"Unsupported format: {fmt!r}")


def compute_fva(
    model: cobra.Model,
    reaction_list: list[str] | None = None,
    fraction_of_optimum: float = 1.0,
    loopless: bool = False,
    processes: int | None = None,
) -> FVAResult:
    """Run flux variability analysis on a model and pack it into an FVAResult.

    Shared by ModelService.fva() (blocking) and jobs.runners.run_fva() (worker)
    so both produce identical results.
    """
    from cobra.flux_analysis import flux_variability_analysis

    # cobra deprecated the boolean `loopless`: None = off, a method name = on.
    loopless_arg = "cycleFreeFlux" if loopless else None
    df = flux_variability_analysis(
        model,
        reaction_list=reaction_list,
        fraction_of_optimum=fraction_of_optimum,
        loopless=loopless_arg,
        processes=processes,
    )
    ranges = {
        str(rid): (float(row.minimum), float(row.maximum))
        for rid, row in df.iterrows()
    }
    return FVAResult(
        status="optimal",
        ranges=ranges,
        fraction_of_optimum=fraction_of_optimum,
        loopless=loopless,
    )


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #

class ModelService:
    """Holds model sessions and exposes all GEM operations with no UI coupling."""

    def __init__(self, solver: str = "gurobi") -> None:
        self.solver = solver
        self._sessions: dict[str, _Session] = {}

    # -- internal helpers --------------------------------------------------- #

    def _session(self, session_id: str) -> _Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise KeyError(f"Unknown session_id: {session_id!r}") from None

    # -- session lifecycle -------------------------------------------------- #

    def load_model(self, source: str, label: str | None = None) -> str:
        """Load SBML / JSON / MAT from `source` path. Returns a new session_id."""
        if not os.path.exists(source):
            raise FileNotFoundError(source)
        fmt = _detect_format(source)
        model = read_model_file(source)
        try:
            model.solver = self.solver
        except Exception as exc:   # solver not installed / unknown
            raise RuntimeError(
                f"Could not set solver {self.solver!r} on the model: {exc}"
            ) from exc

        session_id = uuid.uuid4().hex
        self._sessions[session_id] = _Session(
            session_id=session_id,
            label=label or model.id or os.path.basename(source),
            model=model,
            original=model.copy(),    # snapshot for reset(), decoupled from disk
            source=source,
            fmt=fmt,
        )
        return session_id

    def clone_session(self, session_id: str) -> str:
        """Deep-copy a session (for what-if branches). Returns new session_id."""
        raise NotImplementedError

    def close_session(self, session_id: str) -> None:
        self._session(session_id)            # validate it exists
        del self._sessions[session_id]

    def list_sessions(self) -> list[dict]:
        """[{session_id, label, n_reactions, n_metabolites, n_genes}, ...]"""
        return [
            {
                "session_id": s.session_id,
                "label": s.label,
                "n_reactions": len(s.model.reactions),
                "n_metabolites": len(s.model.metabolites),
                "n_genes": len(s.model.genes),
            }
            for s in self._sessions.values()
        ]

    def export_model(self, session_id: str, path: str, fmt: str = "sbml") -> str:
        """Serialize the CURRENT (edited) model to disk. Returns the path.

        This is the bridge to the job layer: heavy jobs reference this file,
        never the in-memory model, so the same job spec works locally and on
        a SLURM node sharing the filesystem.
        """
        s = self._session(session_id)
        fmt = fmt.lower()
        if fmt in ("sbml", "xml"):
            write_sbml_model(s.model, path)
        elif fmt == "json":
            save_json_model(s.model, path)
        elif fmt in ("mat", "matlab"):
            save_matlab_model(s.model, path)
        else:
            raise ValueError(
                f"Unsupported export format {fmt!r}; expected sbml, json, or mat."
            )
        return path

    # -- structure queries -------------------------------------------------- #

    def summary(self, session_id: str) -> dict:
        """counts + active objective + solver + loaded label."""
        s = self._session(session_id)
        model = s.model
        return {
            "session_id": s.session_id,
            "label": s.label,
            "model_id": model.id,
            "n_reactions": len(model.reactions),
            "n_metabolites": len(model.metabolites),
            "n_genes": len(model.genes),
            "objective": str(model.objective.expression),
            "objective_direction": model.objective.direction,
            "solver": self.solver,
        }

    def get_reaction(self, session_id: str, rxn_id: str) -> dict:
        """id, name, reaction string, bounds, GPR, subsystem, current flux if any."""
        s = self._session(session_id)
        rxn = s.model.reactions.get_by_id(rxn_id)
        flux = None
        if s.last_fluxes is not None:
            flux = s.last_fluxes.get(rxn_id)
        return {
            "id": rxn.id,
            "name": rxn.name,
            "reaction": rxn.build_reaction_string(),
            "lower_bound": rxn.lower_bound,
            "upper_bound": rxn.upper_bound,
            "gene_reaction_rule": rxn.gene_reaction_rule,
            "subsystem": rxn.subsystem,
            "objective_coefficient": rxn.objective_coefficient,
            "flux": flux,
        }

    def list_reactions(self, session_id: str, pattern: str | None = None) -> list[dict]:
        """All reactions (optionally regex/substring filtered) as table rows."""
        s = self._session(session_id)
        reactions = s.model.reactions
        if pattern:
            rx = re.compile(pattern, re.IGNORECASE)
            reactions = [
                r for r in reactions
                if rx.search(r.id) or (r.name and rx.search(r.name))
            ]
        return [
            {
                "id": r.id,
                "name": r.name,
                "reaction": r.build_reaction_string(),
                "lower_bound": r.lower_bound,
                "upper_bound": r.upper_bound,
                "subsystem": r.subsystem,
                "gene_reaction_rule": r.gene_reaction_rule,
            }
            for r in reactions
        ]

    def objective_reactions(self, session_id: str) -> list[str]:
        """Ids of the reactions with a non-zero objective coefficient."""
        s = self._session(session_id)
        return [r.id for r in s.model.reactions if r.objective_coefficient]

    # -- edits (each returns a ChangeRecord; service maintains a change log) - #

    def set_bounds(
        self, session_id: str, rxn_id: str,
        lower: float | None = None, upper: float | None = None,
    ) -> ChangeRecord:
        s = self._session(session_id)
        rxn = s.model.reactions.get_by_id(rxn_id)
        before = {"lower_bound": rxn.lower_bound, "upper_bound": rxn.upper_bound}

        new_lower = before["lower_bound"] if lower is None else float(lower)
        new_upper = before["upper_bound"] if upper is None else float(upper)
        if new_lower > new_upper:
            raise ValueError(
                f"lower_bound ({new_lower}) cannot exceed upper_bound ({new_upper})"
            )
        # Assign via .bounds to avoid transient lower>upper during attribute set.
        rxn.bounds = (new_lower, new_upper)

        after = {"lower_bound": rxn.lower_bound, "upper_bound": rxn.upper_bound}
        record = ChangeRecord(op="set_bounds", target=rxn_id, before=before, after=after)
        s.changes.append(record)
        return record

    def add_reaction(
        self, session_id: str, rxn_id: str, name: str,
        stoichiometry: dict[str, float],
        lower_bound: float = 0.0, upper_bound: float = 1000.0,
        gene_reaction_rule: str | None = None,
        create_missing_metabolites: bool = False,
    ) -> ChangeRecord:
        """`stoichiometry`: {metabolite_id: coeff}. If a referenced metabolite
        is absent, create it only when `create_missing_metabolites` is True,
        otherwise raise."""
        s = self._session(session_id)
        model = s.model
        if model.reactions.has_id(rxn_id):
            raise ValueError(f"Reaction {rxn_id!r} already exists")
        if lower_bound > upper_bound:
            raise ValueError(
                f"lower_bound ({lower_bound}) cannot exceed upper_bound ({upper_bound})"
            )

        # Resolve / create the referenced metabolites first.
        resolved: dict[Metabolite, float] = {}
        for met_id, coeff in stoichiometry.items():
            if model.metabolites.has_id(met_id):
                met = model.metabolites.get_by_id(met_id)
            elif create_missing_metabolites:
                met = Metabolite(met_id)
                # infer compartment from a trailing _<comp> suffix when known
                if "_" in met_id:
                    comp = met_id.rsplit("_", 1)[1]
                    if comp in model.compartments:
                        met.compartment = comp
            else:
                raise ValueError(
                    f"Unknown metabolite {met_id!r}; pass "
                    "create_missing_metabolites=True to create it"
                )
            resolved[met] = coeff

        rxn = Reaction(rxn_id, name=name, lower_bound=lower_bound, upper_bound=upper_bound)
        model.add_reactions([rxn])          # new metabolites are added when referenced
        rxn.add_metabolites(resolved)
        if gene_reaction_rule:
            rxn.gene_reaction_rule = gene_reaction_rule

        after = {
            "id": rxn.id,
            "name": rxn.name,
            "reaction": rxn.build_reaction_string(),
            "lower_bound": rxn.lower_bound,
            "upper_bound": rxn.upper_bound,
            "gene_reaction_rule": rxn.gene_reaction_rule,
        }
        record = ChangeRecord(op="add_reaction", target=rxn_id, before={}, after=after)
        s.changes.append(record)
        return record

    def remove_reaction(
        self, session_id: str, rxn_id: str, remove_orphans: bool = False,
    ) -> ChangeRecord:
        s = self._session(session_id)
        rxn = s.model.reactions.get_by_id(rxn_id)
        before = {
            "id": rxn.id,
            "name": rxn.name,
            "reaction": rxn.build_reaction_string(),
            "lower_bound": rxn.lower_bound,
            "upper_bound": rxn.upper_bound,
            "gene_reaction_rule": rxn.gene_reaction_rule,
        }
        s.model.remove_reactions([rxn], remove_orphans=remove_orphans)
        record = ChangeRecord(
            op="remove_reaction", target=rxn_id, before=before, after={}
        )
        s.changes.append(record)
        return record

    def set_objective(
        self, session_id: str, expr: str | dict[str, float],
        direction: str | None = None,
    ) -> ChangeRecord:
        """Reaction id, or a linear combination {rxn_id: coeff}.

        `direction` ("max" | "min") sets the optimization sense; None keeps the
        model's current sense.
        """
        s = self._session(session_id)
        model = s.model
        before = {
            "expression": str(model.objective.expression),
            "direction": model.objective.direction,
        }

        if direction is not None and direction not in ("max", "min"):
            raise ValueError(f"direction must be 'max' or 'min', got {direction!r}")

        if isinstance(expr, str):
            model.reactions.get_by_id(expr)        # validate it exists
            model.objective = expr
            target = expr
        else:
            coeffs = {
                model.reactions.get_by_id(rid): float(c) for rid, c in expr.items()
            }
            if not coeffs:
                raise ValueError("Objective dict must reference at least one reaction")
            model.objective = coeffs
            target = ",".join(expr.keys())

        if direction is not None:
            model.objective.direction = direction

        after = {
            "expression": str(model.objective.expression),
            "direction": model.objective.direction,
        }
        record = ChangeRecord(
            op="set_objective", target=target, before=before, after=after
        )
        s.changes.append(record)
        return record

    def change_log(self, session_id: str) -> list[ChangeRecord]:
        return list(self._session(session_id).changes)

    def reset(self, session_id: str) -> None:
        """Revert the session to its as-loaded state."""
        s = self._session(session_id)
        s.model = s.original.copy()       # fresh copy so the snapshot stays pristine
        try:
            s.model.solver = self.solver
        except Exception:
            pass
        s.changes.clear()
        s.last_fluxes = None

    # -- exchange / transport handling -------------------------------------- #

    def classify_exchanges(self, session_id: str) -> list[ExchangeInfo]:
        """Classify all boundary reactions (exchange/demand/sink) and report
        their current uptake/secretion capability from the bounds."""
        s = self._session(session_id)
        model = s.model
        # cobra partitions boundary reactions into these three sets.
        demands = {r.id for r in model.demands}
        sinks = {r.id for r in model.sinks}

        infos: list[ExchangeInfo] = []
        for rxn in model.boundary:
            if rxn.id in demands:
                kind = "demand"
            elif rxn.id in sinks:
                kind = "sink"
            else:
                kind = "exchange"
            # boundary reactions have exactly one metabolite
            metabolite_id = next(iter(rxn.metabolites)).id
            infos.append(
                ExchangeInfo(
                    reaction_id=rxn.id,
                    metabolite_id=metabolite_id,
                    name=rxn.name,
                    lower_bound=rxn.lower_bound,
                    upper_bound=rxn.upper_bound,
                    direction=_direction_from_bounds(rxn.lower_bound, rxn.upper_bound),
                    kind=kind,
                )
            )
        return infos

    def toggle_exchange(
        self, session_id: str, rxn_id: str, direction: ExchangeDirection,
    ) -> ChangeRecord:
        """Open/close uptake and/or secretion by editing bounds, respecting the
        boundary sign convention (negative flux = uptake)."""
        s = self._session(session_id)
        rxn = s.model.reactions.get_by_id(rxn_id)
        if not rxn.boundary:
            raise ValueError(f"{rxn_id!r} is not a boundary reaction")

        before = {"lower_bound": rxn.lower_bound, "upper_bound": rxn.upper_bound}
        # Preserve the existing open magnitude in each direction; fall back to the
        # default when that side is currently closed.
        uptake_mag = -rxn.lower_bound if rxn.lower_bound < 0 else DEFAULT_BOUND
        secretion_mag = rxn.upper_bound if rxn.upper_bound > 0 else DEFAULT_BOUND

        direction = ExchangeDirection(direction)   # accept raw strings too
        if direction is ExchangeDirection.UPTAKE:
            new_bounds = (-uptake_mag, 0.0)
        elif direction is ExchangeDirection.SECRETION:
            new_bounds = (0.0, secretion_mag)
        elif direction is ExchangeDirection.BOTH:
            new_bounds = (-uptake_mag, secretion_mag)
        else:  # BLOCKED
            new_bounds = (0.0, 0.0)
        rxn.bounds = new_bounds

        after = {
            "lower_bound": rxn.lower_bound,
            "upper_bound": rxn.upper_bound,
            "direction": direction.value,
        }
        record = ChangeRecord(
            op="toggle_exchange", target=rxn_id, before=before, after=after
        )
        s.changes.append(record)
        return record

    def set_medium(self, session_id: str, medium: dict[str, float]) -> ChangeRecord:
        """{exchange_rxn_id: max_uptake}. Wraps cobra's medium setter.

        cobra's setter defines the *whole* medium: listed exchanges get the given
        max uptake, and every other exchange has its uptake closed.
        """
        s = self._session(session_id)
        before = dict(s.model.medium)
        s.model.medium = medium       # cobra validates the keys are exchanges
        after = dict(s.model.medium)
        record = ChangeRecord(
            op="set_medium", target="medium", before=before, after=after
        )
        s.changes.append(record)
        return record

    # -- fast analyses: synchronous (sub-second to seconds) ----------------- #

    def fba(self, session_id: str) -> FluxResult:
        s = self._session(session_id)
        solution = s.model.optimize()
        s.last_fluxes = solution.fluxes.to_dict()
        return FluxResult(
            objective_value=float(solution.objective_value),
            status=solution.status,
            fluxes=dict(s.last_fluxes),
            reduced_costs=_series_to_dict(solution.reduced_costs),
            shadow_prices=_series_to_dict(solution.shadow_prices),
        )

    def pfba(self, session_id: str) -> FluxResult:
        s = self._session(session_id)
        solution = _cobra_pfba(s.model)
        s.last_fluxes = solution.fluxes.to_dict()
        # cobra's pFBA solution.objective_value is the minimized sum of absolute
        # fluxes; report the biological objective (e.g. growth) instead, computed
        # from the parsimonious fluxes — consistent with fba().
        objective_value = sum(
            r.objective_coefficient * s.last_fluxes[r.id]
            for r in s.model.reactions
            if r.objective_coefficient
        )
        return FluxResult(
            objective_value=float(objective_value),
            status=solution.status,
            fluxes=dict(s.last_fluxes),
        )

    def scan_objective(self, session_id: str, scan: list[dict]) -> dict:
        """Scan the objective value over a grid of fixed flux values.

        `scan` is a list of 1 or 2 dicts {reaction_id, min, max, points}. Each
        scanned reaction is pinned to each grid value (lower=upper) and the model
        re-optimised; the result is the objective value at every grid point
        (robustness analysis / phenotypic phase plane). Infeasible points are
        None. Edits are made inside cobra's context manager, so the session's
        bounds and objective are left untouched.

        Returns {objective, direction, axes:[{reaction_id, values}], values}
        where `values` is a 1-D list (one axis) or a 2-D grid (two axes,
        values[i][j] for axes[0].values[i] x axes[1].values[j]).
        """
        if not 1 <= len(scan) <= 2:
            raise ValueError("scan must specify 1 or 2 reactions")
        s = self._session(session_id)
        model = s.model

        axes: list[dict] = []
        rxns = []
        for a in scan:
            rxn = model.reactions.get_by_id(a["reaction_id"])
            axes.append({
                "reaction_id": rxn.id,
                "values": _linspace(float(a["min"]), float(a["max"]), int(a["points"])),
            })
            rxns.append(rxn)

        def _solve() -> Optional[float]:
            val = model.slim_optimize(error_value=float("nan"))  # no warnings on infeasible
            return None if math.isnan(val) else float(val)

        if len(axes) == 1:
            values: list = []
            for v in axes[0]["values"]:
                with model:                       # auto-reverts bounds after the block
                    rxns[0].bounds = (v, v)
                    values.append(_solve())
        else:
            values = []
            for v0 in axes[0]["values"]:
                row = []
                for v1 in axes[1]["values"]:
                    with model:
                        rxns[0].bounds = (v0, v0)
                        rxns[1].bounds = (v1, v1)
                        row.append(_solve())
                values.append(row)

        return {
            "objective": str(model.objective.expression),
            "direction": model.objective.direction,
            "axes": axes,
            "values": values,
        }

    # -- slow analysis: exposed for blocking use, but normally run via the
    #    job layer (see jobs.py JobType.FVA). ------------------------------- #

    def fva(
        self, session_id: str,
        reaction_list: list[str] | None = None,
        fraction_of_optimum: float = 1.0,
        loopless: bool = False,
        processes: int | None = None,
    ) -> FVAResult:
        s = self._session(session_id)
        return compute_fva(
            s.model,
            reaction_list=reaction_list,
            fraction_of_optimum=fraction_of_optimum,
            loopless=loopless,
            processes=processes,
        )


def _series_to_dict(series) -> Optional[dict[str, float]]:
    """Convert a pandas Series of duals to a plain dict, or None if absent."""
    if series is None:
        return None
    try:
        return {k: float(v) for k, v in series.to_dict().items()}
    except Exception:
        return None
