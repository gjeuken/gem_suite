"""Process-wide service singletons for the Dash app.

The app runs against a LIVE ModelService in-process: sessions live here, server
side, and the browser holds only a session_id / job_id string (in dcc.Store) —
exactly the SPEC seam. FVA still goes through the job layer (LocalProcessBackend)
so the local->SLURM seam is exercised by the UI.

Solver is configurable via GEM_SUITE_SOLVER (default "gurobi"; the repo ships a
license that gem_suite points Gurobi at automatically — see _bootstrap_gurobi_
license in gem_suite/__init__.py). Set GEM_SUITE_SOLVER=glpk to fall back to the
license-free solver.
"""
from __future__ import annotations

import os

from gem_suite import ModelService
from gem_suite.jobs import LocalProcessBackend

SOLVER = os.environ.get("GEM_SUITE_SOLVER", "gurobi")

# Module-level singletons used by the default app. Tests build their own.
SERVICE = ModelService(solver=SOLVER)
BACKEND = LocalProcessBackend()
