"""Run manifests — the reproducibility backbone.

Every analysis or design run persists a JSON manifest: model label + structural
hash, the operation and its parameters, solver, status, package versions, and any
operation-specific extras (for designs: modules, KO/KI, verification, EFM). CSV
exports are written with a companion manifest so a result is never orphaned from
the conditions that produced it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import cobra


def model_hash(model: cobra.Model) -> str:
    """Stable short hash of model structure (reactions+bounds, metabolites, objective)."""
    payload = {
        "reactions": sorted(
            [r.id, float(r.lower_bound), float(r.upper_bound)] for r in model.reactions
        ),
        "metabolites": sorted(m.id for m in model.metabolites),
        "objective": str(model.objective.expression),
        "direction": model.objective.direction,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def versions() -> dict[str, str | None]:
    """Versions of the packages that affect a result."""
    import importlib.metadata as md

    out: dict[str, str | None] = {}
    for pkg in ("cobra", "optlang", "straindesign", "gurobipy"):
        try:
            out[pkg] = md.version(pkg)
        except Exception:
            out[pkg] = None
    try:
        import gem_suite
        out["gem_suite"] = getattr(gem_suite, "__version__", None)
    except Exception:
        out["gem_suite"] = None
    return out


def build_manifest(
    *,
    operation: str,
    model_label: str,
    model_hash: str,
    solver: str,
    status: str,
    params: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a JSON-serializable run manifest."""
    manifest = {
        "tool": "gem_suite",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "model_label": model_label,
        "model_hash": model_hash,
        "solver": solver,
        "status": status,
        "params": params or {},
        "versions": versions(),
    }
    if extra:
        manifest.update(extra)
    return manifest


def write_manifest(manifest: dict[str, Any], path: str) -> str:
    with open(path, "w") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    return path
