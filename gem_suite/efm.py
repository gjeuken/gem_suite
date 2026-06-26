"""Elementary flux mode (EFM) test on a flux vector.

A flux vector is an elementary flux mode iff the stoichiometric submatrix on its
support — after dropping all-zero metabolite rows — has exactly one more column
than its row rank (nullity 1). This is the rank/nullity criterion from the spec;
loops in a non-loopless solution inflate the support, so prefer a loopless flux
vector as the input.
"""
from __future__ import annotations

import numpy as np


def is_elementary_flux_mode(N, v, tol: float = 1e-9) -> tuple[bool, dict]:
    """Test whether flux vector `v` is an EFM of stoichiometric matrix `N`.

    N: stoichiometric matrix (rows=metabolites, cols=reactions).
    v: flux vector aligned to N's columns.
    Returns (is_efm, info) where info has n_active, rank, nullity (+ reason on edges).
    """
    N = np.asarray(N, dtype=float)
    v = np.asarray(v, dtype=float)
    support = np.where(np.abs(v) > tol)[0]          # drop unused reactions
    if support.size == 0:
        return False, {"n_active": 0, "rank": 0, "nullity": 0, "reason": "zero flux"}

    Nsub = N[:, support]
    nz_rows = np.any(np.abs(Nsub) > tol, axis=1)     # drop all-zero metabolite rows
    Nred = Nsub[nz_rows, :]
    rank = int(np.linalg.matrix_rank(Nred, tol=tol))
    ncols = int(Nred.shape[1])
    nullity = ncols - rank

    info = {"n_active": ncols, "rank": rank, "nullity": nullity}
    if nullity == 0:
        info["reason"] = "degenerate (nullity 0); numerical or over-determined"
    elif nullity > 1:
        info["reason"] = "decomposable (nullity > 1); not elementary"
    return (nullity == 1), info
