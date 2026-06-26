"""Unit tests for the EFM (elementary flux mode) rank/nullity criterion."""
from __future__ import annotations

import numpy as np

from gem_suite.efm import is_elementary_flux_mode


def test_known_efm_linear_pathway():
    # ->A->B->  with v=[1,1,1]; N rows A,B  -> rank 2, cols 3, nullity 1
    N = np.array([[1.0, -1.0, 0.0],
                  [0.0, 1.0, -1.0]])
    is_efm, info = is_elementary_flux_mode(N, [1.0, 1.0, 1.0])
    assert is_efm is True
    assert info == {"n_active": 3, "rank": 2, "nullity": 1}


def test_superposition_of_two_modes_is_not_efm():
    # two parallel ->A-> modes superimposed; one row, 4 active cols -> nullity 3
    N = np.array([[1.0, -1.0, 1.0, -1.0]])
    is_efm, info = is_elementary_flux_mode(N, [1.0, 1.0, 1.0, 1.0])
    assert is_efm is False
    assert info["nullity"] == 3


def test_zero_flux_is_not_efm():
    N = np.array([[1.0, -1.0]])
    is_efm, info = is_elementary_flux_mode(N, [0.0, 0.0])
    assert is_efm is False
    assert info["reason"] == "zero flux"


def test_degenerate_nullity_zero():
    # single active reaction consuming A -> rank 1, cols 1, nullity 0
    N = np.array([[-1.0]])
    is_efm, info = is_elementary_flux_mode(N, [1.0])
    assert is_efm is False
    assert info["nullity"] == 0
    assert "degenerate" in info["reason"]


def test_support_filtering_ignores_zero_flux_columns():
    # inactive 4th reaction must be dropped from the support before the test
    N = np.array([[1.0, -1.0, 0.0, 7.0],
                  [0.0, 1.0, -1.0, 3.0]])
    is_efm, info = is_elementary_flux_mode(N, [1.0, 1.0, 1.0, 0.0])
    assert is_efm is True
    assert info["n_active"] == 3
