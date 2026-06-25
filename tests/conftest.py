"""Shared pytest fixtures.

Tests use e_coli_core only (per SPEC). GLPK is the test solver: it ships with
cobra and runs the textbook model in well under a second, so the suite needs no
Gurobi license.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gem_suite import ModelService

DATA_DIR = Path(__file__).parent / "data"
E_COLI_CORE = DATA_DIR / "e_coli_core.xml.gz"


@pytest.fixture
def model_path() -> str:
    return str(E_COLI_CORE)


@pytest.fixture
def service() -> ModelService:
    # GLPK, not Gurobi: no license needed for the test loop.
    return ModelService(solver="glpk")


@pytest.fixture
def session(service: ModelService, model_path: str) -> str:
    return service.load_model(model_path, label="e_coli_core")
