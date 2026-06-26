"""Controller functions: the app's logic, decoupled from Dash.

Every function takes an explicit `service` (and `backend` where needed) and
returns plain JSON-able data — so the same logic is unit-tested directly against
a live ModelService and merely *wired* to inputs/outputs by the Dash callbacks.
No Dash imports here; no UI knowledge leaks into ModelService.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import asdict
from datetime import datetime
from typing import Any

import pandas as pd

from gem_suite import ExchangeDirection, ModelService
from gem_suite.jobs import JobBackend, JobSpec, JobState, JobType, StrainDesignParams
from gem_suite.manifest import build_manifest

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


def run_fba(service: ModelService, session_id: str, loopless: bool = False) -> dict:
    return _flux_summary(service.fba(session_id, loopless=loopless))


def run_pfba(service: ModelService, session_id: str, loopless: bool = False) -> dict:
    result = service.pfba(session_id, loopless=loopless)
    out = _flux_summary(result)
    # EFM verdict on the pFBA flux (prefer loopless — loops inflate the support)
    out["efm"] = service.efm_test(session_id, result.fluxes)
    return out


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


# -- CSV export (+ companion manifest, zipped) ------------------------------ #

_FBA_COLUMNS = ["reaction_id", "reaction_name", "subsystem", "flux",
                "lower_bound", "upper_bound"]
_FVA_COLUMNS = ["reaction_id", "reaction_name", "min_flux", "max_flux", "span",
                "fraction_of_optimum"]


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M")


def export_bundle(name: str, rows: list[dict], columns: list[str],
                  manifest: dict) -> tuple[str, bytes]:
    """A ZIP of {name}.csv + {name}_manifest.json (a CSV is never orphaned)."""
    df = pd.DataFrame(rows, columns=columns)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}.csv", df.to_csv(index=False))
        zf.writestr(f"{name}_manifest.json", json.dumps(manifest, indent=2, default=str))
    return f"{name}.zip", buf.getvalue()


def fba_table(service: ModelService, session_id: str, kind: str = "fba",
              loopless: bool = False) -> dict:
    result = (service.pfba(session_id, loopless=loopless) if kind == "pfba"
              else service.fba(session_id, loopless=loopless))
    rows = [
        {"reaction_id": r["id"], "reaction_name": r["name"],
         "subsystem": r["subsystem"], "flux": result.fluxes.get(r["id"], 0.0),
         "lower_bound": r["lower_bound"], "upper_bound": r["upper_bound"]}
        for r in service.list_reactions(session_id)
    ]
    return {"rows": rows, "status": result.status,
            "objective_value": result.objective_value}


def fva_table(service: ModelService, backend: JobBackend, job_id: str,
              session_id: str) -> dict:
    result = backend.result(job_id)
    names = {r["id"]: r["name"] for r in service.list_reactions(session_id)}
    rows = [
        {"reaction_id": rid, "reaction_name": names.get(rid, ""),
         "min_flux": lo, "max_flux": hi, "span": hi - lo,
         "fraction_of_optimum": result.fraction_of_optimum}
        for rid, (lo, hi) in sorted(result.ranges.items())
    ]
    return {"rows": rows, "status": result.status,
            "fraction_of_optimum": result.fraction_of_optimum,
            "loopless": result.loopless}


def analysis_export(service: ModelService, session_id: str, kind: str,
                    loopless: bool = False) -> tuple[str, bytes]:
    label = service.summary(session_id)["label"]
    tab = fba_table(service, session_id, kind, loopless)
    manifest = build_manifest(
        operation=kind, model_label=label,
        model_hash=service.model_hash(session_id), solver=service.solver,
        status=tab["status"], params={"loopless": loopless},
        extra={"objective_value": tab["objective_value"]},
    )
    return export_bundle(f"{label}_{kind}_{_timestamp()}", tab["rows"],
                         _FBA_COLUMNS, manifest)


def fva_export(service: ModelService, backend: JobBackend, job_id: str,
               session_id: str) -> tuple[str, bytes]:
    label = service.summary(session_id)["label"]
    tab = fva_table(service, backend, job_id, session_id)
    manifest = build_manifest(
        operation="fva", model_label=label,
        model_hash=service.model_hash(session_id), solver=service.solver,
        status=tab["status"],
        params={"fraction_of_optimum": tab["fraction_of_optimum"],
                "loopless": tab["loopless"]},
    )
    return export_bundle(f"{label}_fva_{_timestamp()}", tab["rows"],
                         _FVA_COLUMNS, manifest)


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


# -- strain design: presets, validation, KI parsing ------------------------ #

def preset_options() -> list[dict]:
    from gem_suite.presets import PRESETS
    return [{"label": p.label, "value": p.key} for p in PRESETS]


def preset_note(key: str) -> str:
    from gem_suite.presets import get_preset
    return get_preset(key).notes


def resolve_preset(service: ModelService, session_id: str, key: str,
                   product: str, substrate: str, ymin: float) -> dict:
    """Resolve a preset into a module list using the model's growth reaction."""
    from gem_suite.presets import resolve_preset as _resolve
    growth = (service.objective_reactions(session_id) or ["BIOMASS"])[0]
    return _resolve(key, sub=substrate, prod=product, ymin=ymin, growth=growth)


def _parse_ineq(text: str) -> tuple[str, float] | None:
    """Return (operator, rhs) for 'lhs <=|>=|= rhs', or None if unparseable."""
    op = next((o for o in ("<=", ">=") if o in text), "=" if "=" in text else None)
    if op is None:
        return None
    _, _, rhs = text.partition(op)
    try:
        return op, float(rhs.strip())
    except ValueError:
        return None


def validate_constraint(reaction_ids: set[str], text: str) -> dict:
    """Validate one free-text inequality row. {ok, error, warnings}."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty constraint", "warnings": []}
    parsed = _parse_ineq(text)
    if parsed is None:
        return {"ok": False, "error": "expected 'lhs <=|>=|= number'", "warnings": []}
    lhs = text.split(parsed[0])[0]
    ids = re.findall(r"[A-Za-z_]\w*", lhs)
    warnings = []
    if any(i.startswith("EX_") for i in ids):
        warnings.append("exchange term: uptake is negative, secretion positive")
    unknown = [i for i in ids if i not in reaction_ids]
    if unknown:
        return {"ok": False, "error": f"unknown reaction id(s): {', '.join(unknown)}",
                "warnings": warnings}
    return {"ok": True, "error": None, "warnings": warnings}


def suppress_needs_aux(constraints: list[str]) -> bool:
    """True if the suppress region includes the v=0 vector (the trivial trap)."""
    def zero_satisfies(c: str) -> bool:
        parsed = _parse_ineq(c)
        if parsed is None:
            return True
        op, rhs = parsed
        if op == ">=":
            return 0.0 >= rhs
        if op == "<=":
            return 0.0 <= rhs
        return rhs == 0.0
    return all(zero_satisfies(c) for c in constraints)


def parse_ki(service: ModelService, session_id: str, text: str) -> dict:
    """Parse + validate a KI paste block against the session model."""
    from gem_suite.ki_parser import parse_ki_block
    reactions, errors = parse_ki_block(text)
    val = (service.validate_knockins(session_id, reactions)
           if reactions else {"errors": [], "warnings": []})
    return {"reactions": reactions, "errors": errors + val["errors"],
            "warnings": val["warnings"]}


# -- strain design as a job ------------------------------------------------- #

def submit_strain_design(service: ModelService, backend: JobBackend,
                         session_id: str, store: dict,
                         export_dir: str | None = None) -> str:
    """Submit a strain-design job from the modules Store (the JSON IS the input)."""
    export_dir = export_dir or tempfile.mkdtemp(prefix="gem_app_")
    os.makedirs(export_dir, exist_ok=True)
    model_path = os.path.join(export_dir, f"{session_id}_sd.xml")
    service.export_model(session_id, model_path, fmt="sbml")

    params = StrainDesignParams(
        approach=store.get("approach", "MCS"),
        modules=store.get("modules"),
        ko_candidates=store.get("ko_candidates"),
        ki_reactions=store.get("ki_reactions"),
        ki_candidates=store.get("ki_candidates"),
        gene_level=bool(store.get("gene_level", True)),
        max_solutions=int(store.get("max_solutions", 1)),
        max_size=store.get("max_size"),
        time_limit_s=store.get("time_limit_s"),
        target_reaction=store.get("target_reaction"),
        min_growth=store.get("min_growth"),
        min_yield=store.get("min_yield"),
    )
    spec = JobSpec(
        job_type=JobType.STRAIN_DESIGN,
        model_path=model_path,
        params=params.to_params(),
        solver=service.solver,
        label=store.get("model_label") or f"sd:{params.approach}",
    )
    return backend.submit(spec)


def strain_design_solution_rows(backend: JobBackend, job_id: str) -> list[dict]:
    result = backend.result(job_id)
    rows = []
    for i, sol in enumerate(result.solutions):
        n = len(sol.verification)
        passed = sum(1 for v in sol.verification if v["passed"])
        rows.append({
            "#": i + 1,
            "level": sol.level,
            "cost": sol.cost,
            "knockouts": ", ".join(sol.knockouts),
            "knockins": ", ".join(sol.knockins),
            "verification": (f"{'✓' if passed == n else '✗'} {passed}/{n}"
                             if n else "—"),
            "efm": ("EFM" if sol.efm and sol.efm["is_efm"]
                    else "not EFM" if sol.efm else "—"),
        })
    return rows


def strain_design_verification_rows(backend: JobBackend, job_id: str,
                                    solution_index: int = 0) -> list[dict]:
    result = backend.result(job_id)
    if solution_index >= len(result.solutions):
        return []
    out = []
    for v in result.solutions[solution_index].verification:
        out.append({
            "module": v["module_type"],
            "constraints": " ; ".join(v["constraints"]),
            "result": "PASS" if v["passed"] else "FAIL",
            "objective": v["objective"],
        })
    return out


def strain_design_manifest_download(backend: JobBackend,
                                    job_id: str) -> tuple[str, bytes] | None:
    """The companion manifest written next to the design result."""
    from gem_suite.jobs.runners import manifest_path_for
    st = backend.status(job_id)
    if st.state != JobState.SUCCEEDED or not st.result_path:
        return None
    path = manifest_path_for(st.result_path)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return os.path.basename(path), fh.read()
