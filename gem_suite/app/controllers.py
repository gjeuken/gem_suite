"""Controller functions: the app's logic, decoupled from Dash.

Every function takes an explicit `service` (and `backend` where needed) and
returns plain JSON-able data — so the same logic is unit-tested directly against
a live ModelService and merely *wired* to inputs/outputs by the Dash callbacks.
No Dash imports here; no UI knowledge leaks into ModelService.
"""
from __future__ import annotations

import base64
import os
import tempfile
from dataclasses import asdict
from typing import Any

from gem_suite import ExchangeDirection, ModelService
from gem_suite.jobs import JobBackend, JobSpec, JobState, JobType, StrainDesignParams

_ACTIVE = 1e-9   # flux magnitude considered non-zero for display


# -- model loading / structure --------------------------------------------- #

def load_model(service: ModelService, source: str, label: str | None = None) -> dict:
    session_id = service.load_model(source, label=label)
    return {"session_id": session_id, "summary": service.summary(session_id)}


def load_model_from_upload(
    service: ModelService,
    contents: str,
    filename: str,
    label: str | None = None,
    upload_dir: str | None = None,
) -> dict:
    """Load a model from a dcc.Upload payload.

    `contents` is a data URL ("data:<mime>;base64,<data>"). The bytes are written
    to a temp file under the ORIGINAL basename so cobra infers the format from the
    extension (.xml/.sbml/.xml.gz/.json/.mat) and ModelService still loads by path
    — the file-path seam is preserved.
    """
    if not contents or not filename:
        raise ValueError("no file uploaded")
    _, _, b64 = contents.partition(",")
    data = base64.b64decode(b64)

    upload_dir = upload_dir or tempfile.mkdtemp(prefix="gem_upload_")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, os.path.basename(filename))   # basename: no traversal
    with open(path, "wb") as fh:
        fh.write(data)

    return load_model(service, path, label=label or None)


def reaction_rows(service: ModelService, session_id: str,
                  pattern: str | None = None) -> list[dict]:
    return service.list_reactions(session_id, pattern=pattern or None)


def reaction_options(service: ModelService, session_id: str) -> list[dict]:
    """Dropdown options (label searchable by id + name, value = reaction id)."""
    return [
        {"label": f"{r['id']} — {r['name']}" if r["name"] else r["id"],
         "value": r["id"]}
        for r in service.list_reactions(session_id)
    ]


def set_bounds(service: ModelService, session_id: str, rxn_id: str,
               lower: float | None, upper: float | None) -> dict:
    lower = None if lower is None or lower == "" else float(lower)
    upper = None if upper is None or upper == "" else float(upper)
    rec = service.set_bounds(session_id, rxn_id, lower=lower, upper=upper)
    return asdict(rec)


def current_objective(service: ModelService, session_id: str) -> dict:
    s = service.summary(session_id)
    return {"objective": s["objective"], "direction": s["objective_direction"]}


def _parse_objective(expr: str) -> str | dict[str, float]:
    """A single reaction id, or a linear combination "r1, r2:0.5, r3:-1"."""
    expr = expr.strip()
    if "," not in expr and ":" not in expr:
        return expr
    coeffs: dict[str, float] = {}
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        rid, sep, coeff = part.partition(":")
        coeffs[rid.strip()] = float(coeff) if sep else 1.0
    return coeffs


def set_objective(service: ModelService, session_id: str, expr: str,
                  direction: str | None = None) -> dict:
    """Set the FBA objective to a reaction id (or linear combination) and sense."""
    service.set_objective(session_id, _parse_objective(expr), direction=direction)
    return current_objective(service, session_id)


# -- exchanges -------------------------------------------------------------- #

def exchange_rows(service: ModelService, session_id: str) -> list[dict]:
    rows = []
    for info in service.classify_exchanges(session_id):
        row = asdict(info)
        row["direction"] = info.direction.value   # plain string for the grid
        rows.append(row)
    return rows


def toggle_exchange(service: ModelService, session_id: str, rxn_id: str,
                    direction: str) -> dict:
    rec = service.toggle_exchange(session_id, rxn_id, ExchangeDirection(direction))
    return asdict(rec)


def _is_biomass(rxn_id: str, name: str | None) -> bool:
    return "biomass" in rxn_id.lower() or "biomass" in (name or "").lower()


def exchange_flux_diagram(service: ModelService, session_id: str,
                          fluxes: dict[str, float], tol: float = 1e-9) -> dict:
    """Split non-zero boundary fluxes into uptake (in) and secretion (out).

    Sign convention: negative flux = uptake (into the cell, drawn on the left),
    positive flux = secretion (out of the cell, drawn on the right). When the
    objective is the biomass reaction, growth is added as an outgoing flux too.
    Drives the schematic-cell figure on the analysis page.
    """
    uptake: list[dict] = []
    secretion: list[dict] = []
    for info in service.classify_exchanges(session_id):
        flux = fluxes.get(info.reaction_id, 0.0)
        if abs(flux) <= tol:
            continue
        entry = {"reaction": info.reaction_id, "metabolite": info.metabolite_id,
                 "name": info.name, "flux": flux}
        (uptake if flux < 0 else secretion).append(entry)
    uptake.sort(key=lambda e: e["flux"])          # largest uptake (most negative) first
    secretion.sort(key=lambda e: -e["flux"])       # largest secretion first

    # If the objective is the biomass reaction, show growth as an outgoing flux.
    objective = service.objective_reactions(session_id)
    if len(objective) == 1:
        bid = objective[0]
        name = service.get_reaction(session_id, bid)["name"]
        flux = fluxes.get(bid, 0.0)
        if _is_biomass(bid, name) and abs(flux) > tol:
            secretion.insert(0, {"reaction": bid, "metabolite": "biomass",
                                 "name": name, "flux": flux, "growth": True})
    return {"uptake": uptake, "secretion": secretion}


# -- fast analyses ---------------------------------------------------------- #

def _flux_summary(result) -> dict:
    active = sorted(
        ((rid, f) for rid, f in result.fluxes.items() if abs(f) > _ACTIVE),
        key=lambda kv: abs(kv[1]),
        reverse=True,
    )
    return {
        "objective_value": result.objective_value,
        "status": result.status,
        "n_active": len(active),
        "fluxes": [{"reaction": rid, "flux": f} for rid, f in active],
    }


def run_fba(service: ModelService, session_id: str) -> dict:
    return _flux_summary(service.fba(session_id))


def run_pfba(service: ModelService, session_id: str) -> dict:
    return _flux_summary(service.pfba(session_id))


# -- FVA as a job ----------------------------------------------------------- #

def submit_fva(
    service: ModelService,
    backend: JobBackend,
    session_id: str,
    reaction_list: list[str] | None = None,
    fraction_of_optimum: float = 1.0,
    loopless: bool = False,
    export_dir: str | None = None,
) -> str:
    """Export the current edited model to disk and submit an FVA job for it.

    The export is the local->SLURM bridge: the job references a path, never the
    in-memory model.
    """
    export_dir = export_dir or tempfile.mkdtemp(prefix="gem_app_")
    os.makedirs(export_dir, exist_ok=True)
    model_path = os.path.join(export_dir, f"{session_id}.xml")
    service.export_model(session_id, model_path, fmt="sbml")

    spec = JobSpec(
        job_type=JobType.FVA,
        model_path=model_path,
        params={
            "reaction_list": reaction_list or None,
            "fraction_of_optimum": fraction_of_optimum,
            "loopless": loopless,
            "processes": 1,
        },
        solver=service.solver,
        label=f"fva:{session_id[:8]}",
    )
    return backend.submit(spec)


def job_status(backend: JobBackend, job_id: str) -> dict:
    """Generic, JSON-able job status (works for any JobType)."""
    st = backend.status(job_id)
    return {
        "job_id": st.job_id,
        "state": st.state.value,
        "progress": st.progress,
        "done": st.state in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED),
        "succeeded": st.state == JobState.SUCCEEDED,
        "error": st.error,
    }


# kept for the analysis page / existing callers
fva_status = job_status


def fva_result_rows(backend: JobBackend, job_id: str) -> list[dict]:
    result = backend.result(job_id)
    return [
        {"reaction": rid, "minimum": lo, "maximum": hi}
        for rid, (lo, hi) in sorted(result.ranges.items())
    ]


def run_scan(service: ModelService, session_id: str,
             axis1: dict, axis2: dict | None = None) -> dict:
    """Scan the objective over 1 or 2 fixed fluxes (each {reaction_id,min,max,points})."""
    scan = [axis1] + ([axis2] if axis2 else [])
    return service.scan_objective(session_id, scan)


def fva_spans(backend: JobBackend, job_id: str, tol: float = 1e-9) -> list[dict]:
    """FVA ranges with a non-zero span (max - min > tol), widest span first.

    Drives the span plot: reactions pinned to a single value carry no variability
    and are dropped.
    """
    result = backend.result(job_id)
    rows = [
        {"reaction": rid, "minimum": lo, "maximum": hi, "span": hi - lo}
        for rid, (lo, hi) in result.ranges.items()
        if (hi - lo) > tol
    ]
    rows.sort(key=lambda r: r["span"], reverse=True)
    return rows


# -- strain design as a job ------------------------------------------------- #

def submit_strain_design(
    service: ModelService,
    backend: JobBackend,
    session_id: str,
    target_reaction: str,
    approach: str = "MCS",
    gene_level: bool = True,
    max_size: int | None = None,
    max_solutions: int = 1,
    min_growth: float | None = None,
    min_yield: float | None = None,
    ko_candidates: list[str] | None = None,
    ki_candidates: list[str] | None = None,
    ki_database: str | None = None,
    export_dir: str | None = None,
) -> str:
    """Export the current edited model and submit a strain-design job for it."""
    export_dir = export_dir or tempfile.mkdtemp(prefix="gem_app_")
    os.makedirs(export_dir, exist_ok=True)
    model_path = os.path.join(export_dir, f"{session_id}_sd.xml")
    service.export_model(session_id, model_path, fmt="sbml")

    params = StrainDesignParams(
        target_reaction=target_reaction,
        approach=approach,
        gene_level=gene_level,
        max_size=max_size,
        max_solutions=max_solutions,
        min_growth=min_growth,
        min_yield=min_yield,
        ko_candidates=ko_candidates,
        ki_candidates=ki_candidates,
        ki_database=ki_database,
    )
    spec = JobSpec(
        job_type=JobType.STRAIN_DESIGN,
        model_path=model_path,
        params=params.to_params(),
        solver=service.solver,
        label=f"sd:{approach}:{target_reaction}",
    )
    return backend.submit(spec)


def strain_design_solution_rows(backend: JobBackend, job_id: str) -> list[dict]:
    result = backend.result(job_id)
    return [
        {
            "#": i + 1,
            "level": sol.level,
            "cost": sol.cost,
            "knockouts": ", ".join(sol.knockouts),
            "knockins": ", ".join(sol.knockins),
        }
        for i, sol in enumerate(result.solutions)
    ]
