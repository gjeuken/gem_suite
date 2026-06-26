"""Thin wrapper over the StrainDesign package (Schneider/Klamt, on COBRApy).

Translates a JSON-friendly StrainDesignParams into StrainDesign's SDModule(s)
and `compute_strain_designs` call, then packs the SDSolutions into plain,
JSON-serializable dataclasses so the result crosses the job/UI boundary.

Supports MCS (growth-coupled production / yield enforcement), OptKnock,
RobustKnock and OptCouple; reaction- and gene-level knock-OUTs; and knock-INs
via a candidate database of addable reactions. Network compression runs before
the MILP (StrainDesign's `compress=True`) — essential at genome scale.

`straindesign` is imported lazily inside the functions so the rest of the
package (and `gem_suite.jobs`) imports without it installed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cobra

from gem_suite.efm import is_elementary_flux_mode
from gem_suite.jobs.spec import StrainDesignParams
from gem_suite.ki_parser import add_ki_reactions
from gem_suite.model_service import read_model_file

# StrainDesign is chatty; keep its logging quiet for library use.
import logging as _logging
_logging.getLogger("straindesign").setLevel(_logging.ERROR)


# --------------------------------------------------------------------------- #
# Result value types — plain dataclasses, JSON round-trippable.
# --------------------------------------------------------------------------- #

@dataclass
class StrainDesignSolution:
    knockouts: list[str]           # ids removed (genes if gene_level, else reactions)
    knockins: list[str]            # ids added (knock-in reactions)
    cost: float                    # total intervention cost (≈ number of changes)
    level: str                     # "gene" | "reaction"
    # per-module post-run verification (filled by verify_design); plain dicts so
    # the result JSON round-trips unchanged.
    verification: list[dict] = field(default_factory=list)
    efm: dict | None = None        # EFM verdict on the intervened pFBA flux


@dataclass
class StrainDesignResult:
    status: str                    # "optimal" | "infeasible" | "time_limit" | ...
    approach: str                  # echoes the requested approach
    gene_level: bool
    solutions: list[StrainDesignSolution] = field(default_factory=list)
    message: str = ""              # diagnosis (e.g. why no solution) — never silent


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _objective_reaction(model: cobra.Model) -> str:
    for r in model.reactions:
        if r.objective_coefficient:
            return r.id
    raise ValueError("model has no objective reaction to use as growth")


def _prepare_knockins(model: cobra.Model, params: StrainDesignParams) -> dict | None:
    """Merge knock-in candidate reactions into `model` and return their ki_cost.

    Candidates absent from the model are copied in from `ki_database` (a universal
    / KEGG-derived SBML). Returns {reaction_id: 1.0} marking them addable, or None
    when there are no knock-ins.
    """
    cost: dict[str, float] = {}

    # Pasted knock-in reactions (added to the model as addable candidates).
    if params.ki_reactions:
        for rid in add_ki_reactions(model, params.ki_reactions):
            cost[rid] = 1.0

    # Existing-reaction / database knock-in candidates.
    if params.ki_candidates:
        if params.ki_database:
            db = read_model_file(params.ki_database)
            for rid in params.ki_candidates:
                if not model.reactions.has_id(rid):
                    model.add_reactions([db.reactions.get_by_id(rid).copy()])
        missing = [r for r in params.ki_candidates if not model.reactions.has_id(r)]
        if missing:
            raise ValueError(
                f"knock-in candidates not in model and no ki_database to source: {missing}"
            )
        for rid in params.ki_candidates:
            cost[rid] = 1.0

    return cost or None


_MODULE_TYPES = {"suppress": "SUPPRESS", "protect": "PROTECT"}


def _build_modules(model: cobra.Model, params: StrainDesignParams):
    import straindesign as sd

    # Primary path: explicit suppress/protect modules with free-text constraints.
    if params.modules:
        out = []
        for mod in params.modules:
            key = mod["type"].lower()
            if key not in _MODULE_TYPES:
                raise ValueError(f"unknown module type {mod['type']!r}")
            module_type = getattr(sd.names, _MODULE_TYPES[key])
            out.append(sd.SDModule(model, module_type,
                                   constraints=list(mod["constraints"])))
        return out

    # Legacy convenience path: build modules from target_reaction + thresholds.
    biomass = _objective_reaction(model)
    target = params.target_reaction
    approach = params.approach.lower()
    min_growth = params.min_growth if params.min_growth is not None else 0.01

    if approach == "mcs":
        # Growth-coupled production: eliminate flux states that grow but do not
        # produce the target at least at the yield threshold. After the cut,
        # every growing state must produce the target.
        yield_thr = params.min_yield if params.min_yield is not None else 0.0
        return [sd.SDModule(
            model, sd.names.SUPPRESS,
            constraints=[f"{biomass} >= {min_growth}", f"{target} <= {yield_thr}"],
        )]
    if approach in ("optknock", "robustknock"):
        module_type = sd.names.OPTKNOCK if approach == "optknock" else sd.names.ROBUSTKNOCK
        constraints = ([f"{biomass} >= {params.min_growth}"]
                       if params.min_growth is not None else None)
        return [sd.SDModule(model, module_type, inner_objective=biomass,
                            outer_objective=target, constraints=constraints)]
    if approach == "optcouple":
        kwargs = {"inner_objective": biomass, "prod_id": target}
        if params.min_yield is not None:
            kwargs["min_gcp"] = params.min_yield
        return [sd.SDModule(model, sd.names.OPTCOUPLE, **kwargs)]
    raise ValueError(f"unknown strain-design approach: {params.approach!r}")


def _to_result(sols, params: StrainDesignParams) -> StrainDesignResult:
    gene_level = bool(sols.is_gene_sd)
    designs = sols.get_gene_sd() if gene_level else sols.reaction_sd
    level = "gene" if gene_level else "reaction"

    solutions: list[StrainDesignSolution] = []
    for design in designs or []:
        knockouts = sorted(k for k, v in design.items() if v < 0)
        knockins = sorted(k for k, v in design.items() if v > 0)
        solutions.append(StrainDesignSolution(
            knockouts=knockouts,
            knockins=knockins,
            cost=float(len(knockouts) + len(knockins)),
            level=level,
        ))
    return StrainDesignResult(
        status=str(sols.status),
        approach=params.approach,
        gene_level=gene_level,
        solutions=solutions,
    )


# --------------------------------------------------------------------------- #
# Post-run verification + EFM
# --------------------------------------------------------------------------- #

def _intervened_model(model: cobra.Model, params: StrainDesignParams,
                      solution: StrainDesignSolution, solver: str) -> cobra.Model:
    """Base model with the solution's KIs added and its KOs applied."""
    m = model.copy()
    m.solver = solver
    chosen = set(solution.knockins)
    add_ki_reactions(m, [d for d in (params.ki_reactions or []) if d["id"] in chosen])
    if solution.level == "gene":
        for gid in solution.knockouts:
            if m.genes.has_id(gid):
                m.genes.get_by_id(gid).knock_out()
    else:
        for rid in solution.knockouts:
            if m.reactions.has_id(rid):
                m.reactions.get_by_id(rid).bounds = (0.0, 0.0)
    return m


def _feasible_with(model: cobra.Model, constraints: list[str]):
    """Is the model feasible with these extra linear constraints? -> (feasible, obj)."""
    import straindesign as sd

    m = model.copy()
    extra = []
    for coeff, sense, rhs in sd.parse_constraints(constraints, [r.id for r in m.reactions]):
        expr = sum(c * m.reactions.get_by_id(rid).flux_expression
                   for rid, c in coeff.items())
        lb = rhs if sense in (">=", "=") else None
        ub = rhs if sense in ("<=", "=") else None
        extra.append(m.problem.Constraint(expr, lb=lb, ub=ub))
    if extra:
        m.add_cons_vars(extra)
        m.solver.update()
    val = m.slim_optimize(error_value=float("nan"))
    feasible = not math.isnan(val)
    return feasible, (None if not feasible else float(val))


def verify_design(model: cobra.Model, params: StrainDesignParams,
                  solution: StrainDesignSolution, solver: str) -> list[dict]:
    """Per-module feasibility check on the intervened model.

    PROTECT region must be feasible; SUPPRESS region must be infeasible.
    """
    if not params.modules:
        return []
    intervened = _intervened_model(model, params, solution, solver)
    rows: list[dict] = []
    for mod in params.modules:
        kind = mod["type"].lower()
        feasible, obj = _feasible_with(intervened, list(mod["constraints"]))
        passed = feasible if kind == "protect" else (not feasible)
        rows.append({
            "module_type": kind,
            "constraints": list(mod["constraints"]),
            "feasible": feasible,
            "passed": bool(passed),
            "objective": obj,
        })
    return rows


def _design_efm(model: cobra.Model, params: StrainDesignParams,
                solution: StrainDesignSolution, solver: str) -> dict | None:
    """EFM verdict on the intervened model's loopless pFBA flux."""
    from cobra.flux_analysis import loopless_solution, pfba
    from cobra.util.array import create_stoichiometric_matrix

    intervened = _intervened_model(model, params, solution, solver)
    try:
        sol = loopless_solution(intervened, fluxes=pfba(intervened).fluxes)
    except Exception:
        return None
    n_matrix = create_stoichiometric_matrix(intervened)
    v = [sol.fluxes.get(r.id, 0.0) for r in intervened.reactions]
    is_efm, info = is_elementary_flux_mode(n_matrix, v)
    return {"is_efm": bool(is_efm), **info}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def design_strains(
    model: cobra.Model,
    params: StrainDesignParams,
    solver: str = "glpk",
    verify: bool = True,
) -> StrainDesignResult:
    """Compute strain designs for `params` against a COPY of `model`.

    When `verify` and modules are given, each solution is verified (protect
    feasible / suppress infeasible) and gets an EFM verdict on its intervened
    loopless pFBA flux.
    """
    import straindesign as sd

    work = model.copy()
    work.solver = solver

    ki_cost = _prepare_knockins(work, params)
    try:
        modules = _build_modules(work, params)
    except Exception as exc:
        # e.g. a suppress/protect region that is already infeasible in the model
        return StrainDesignResult(status="infeasible", approach=params.approach,
                                  gene_level=params.gene_level, solutions=[],
                                  message=str(exc))

    kwargs: dict = {
        "sd_modules": modules,
        "solver": solver,
        "compress": True,                  # network compression before the MILP
        "max_solutions": params.max_solutions,
    }
    if params.max_size is not None:
        kwargs["max_cost"] = params.max_size
    if params.time_limit_s is not None:
        kwargs["time_limit"] = params.time_limit_s

    # Knock-out candidates: gene- vs reaction-level. None = all (StrainDesign default).
    if params.gene_level:
        genes = params.ko_candidates or [g.id for g in work.genes]
        kwargs["gko_cost"] = {g: 1.0 for g in genes}
    elif params.ko_candidates:
        kwargs["ko_cost"] = {r: 1.0 for r in params.ko_candidates}

    if ki_cost:
        kwargs["ki_cost"] = ki_cost

    # Nested approaches need a "best" search; MCS minimises cost globally.
    if params.approach.lower() in ("optknock", "robustknock", "optcouple"):
        kwargs["solution_approach"] = sd.names.BEST

    try:
        sols = sd.compute_strain_designs(work, **kwargs)
    except Exception as exc:
        return StrainDesignResult(status="infeasible", approach=params.approach,
                                  gene_level=params.gene_level, solutions=[],
                                  message=str(exc))
    result = _to_result(sols, params)

    if verify and params.modules:
        for solution in result.solutions:
            solution.verification = verify_design(model, params, solution, solver)
            solution.efm = _design_efm(model, params, solution, solver)
    return result
