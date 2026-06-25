"""GEM Suite — local tool for analysing genome-scale metabolic models."""
from __future__ import annotations

import os
from pathlib import Path


def _bootstrap_gurobi_license() -> None:
    """Point Gurobi at the repo's `gurobi.lic` unless the user set a license.

    Gurobi reads `GRB_LICENSE_FILE` (or default locations). We `setdefault` so a
    license bundled next to the source tree is found by the app, notebooks and
    scripts without manual env setup — and an explicitly set env var still wins.
    """
    if os.environ.get("GRB_LICENSE_FILE"):
        return
    lic = Path(__file__).resolve().parent.parent / "gurobi.lic"
    if lic.exists():
        os.environ["GRB_LICENSE_FILE"] = str(lic)


_bootstrap_gurobi_license()

from gem_suite.model_service import (
    ChangeRecord,
    ExchangeDirection,
    ExchangeInfo,
    FluxResult,
    FVAResult,
    ModelService,
)

__all__ = [
    "ModelService",
    "ChangeRecord",
    "ExchangeDirection",
    "ExchangeInfo",
    "FluxResult",
    "FVAResult",
]

__version__ = "0.1.0"
