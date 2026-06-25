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

from dataclasses import dataclass, field

import cobra

from gem_suite.jobs.spec import StrainDesignParams
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


@dataclass
class StrainDesignResult:
    status: str                    # straindesign status, e.g. "optimal"
    approach: str                  # echoes the requested approach
    gene_level: bool
    solutions: list[StrainDesignSolution] = field(default_factory=list)


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
    if not params.ki_candidates:
        return None
    if params.ki_database:
        db = read_model_file(params.ki_database)
        for rid in params.ki_candidates:
            if not model.reactions.has_id(rid):
                model.add_reactions([db.reactions.get_by_id(rid).copy()])
    missing = [r for r in params.ki_candidates if not model.reactions.has_id(r)]
    if missing:
        raise ValueError(
            f"knock-in candidates not in model and no ki_database to source them: {missing}"
        )
    return {rid: 1.0 for rid in params.ki_candidates}


def _build_modules(model: cobra.Model, params: StrainDesignParams):
    import straindesign as sd

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
# Entry point
# --------------------------------------------------------------------------- #

def design_strains(
    model: cobra.Model,
    params: StrainDesignParams,
    solver: str = "glpk",
) -> StrainDesignResult:
    """Compute strain designs for `params` against a COPY of `model`."""
    import straindesign as sd

    work = model.copy()
    work.solver = solver

    ki_cost = _prepare_knockins(work, params)
    modules = _build_modules(work, params)

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

    sols = sd.compute_strain_designs(work, **kwargs)
    return _to_result(sols, params)
