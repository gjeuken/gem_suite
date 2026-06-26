"""Process-wide service singletons for the Dash app.

The app runs against a LIVE ModelService in-process: sessions live here, server
side, and the browser holds only a session_id / job_id string (in dcc.Store) —
exactly the SPEC seam. FVA still goes through the job layer (LocalProcessBackend)
so the local->SLURM seam is exercised by the UI.

Solver is configurable via the GEM_SUITE_SOLVER environment variable. The default
is "glpk" — the license-free solver bundled with COBRApy, so the app runs anywhere
with no setup. Set GEM_SUITE_SOLVER=gurobi for the faster solver (you supply your
own license: gem_suite picks up a repo-root gurobi.lic when run from source,
otherwise Gurobi's standard locations such as ~/gurobi.lic / $GRB_LICENSE_FILE).
"""
from __future__ import annotations

import os

from gem_suite import ModelService
from gem_suite.jobs import LocalProcessBackend

SOLVER = os.environ.get("GEM_SUITE_SOLVER", "glpk")

# Module-level singletons used by the default app. Tests build their own.
SERVICE = ModelService(solver=SOLVER)
BACKEND = LocalProcessBackend()
