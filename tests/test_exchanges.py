"""Milestone-2 tests: exchange classification, toggling, and medium."""
from __future__ import annotations

import json
import math
from dataclasses import asdict

import pytest

from gem_suite import ChangeRecord, ExchangeDirection, ExchangeInfo, ModelService
from gem_suite.model_service import _direction_from_bounds

GROWTH = 0.8739215069684


# -- pure direction logic (no model needed) -------------------------------- #

@pytest.mark.parametrize(
    "lower, upper, expected",
    [
        (-10.0, 1000.0, ExchangeDirection.BOTH),
        (-1000.0, 1000.0, ExchangeDirection.BOTH),
        (0.0, 1000.0, ExchangeDirection.SECRETION),
        (-1000.0, 0.0, ExchangeDirection.UPTAKE),
        (0.0, 0.0, ExchangeDirection.BLOCKED),
        (-5.0, -1.0, ExchangeDirection.UPTAKE),   # forced uptake
        (1.0, 5.0, ExchangeDirection.SECRETION),  # forced secretion
    ],
)
def test_direction_from_bounds(lower, upper, expected):
    assert _direction_from_bounds(lower, upper) == expected


# -- classify_exchanges ----------------------------------------------------- #

def test_classify_exchanges_counts_and_kinds(service: ModelService, session: str):
    infos = service.classify_exchanges(session)
    assert len(infos) == 20
    assert all(isinstance(i, ExchangeInfo) for i in infos)
    # e_coli_core has only true exchanges (no demands/sinks)
    assert {i.kind for i in infos} == {"exchange"}


def test_classify_exchanges_glucose(service: ModelService, session: str):
    info = next(i for i in service.classify_exchanges(session)
                if i.reaction_id == "EX_glc__D_e")
    assert info.metabolite_id == "glc__D_e"
    assert info.lower_bound == -10.0
    assert info.upper_bound == 1000.0
    assert info.direction == ExchangeDirection.BOTH
    assert "Glucose" in info.name


def test_classify_exchanges_reflects_edits(service: ModelService, session: str):
    service.set_bounds(session, "EX_glc__D_e", lower=0.0)
    info = next(i for i in service.classify_exchanges(session)
                if i.reaction_id == "EX_glc__D_e")
    assert info.direction == ExchangeDirection.SECRETION


def test_classify_exchanges_serializable(service: ModelService, session: str):
    infos = service.classify_exchanges(session)
    json.dumps([asdict(i) for i in infos])  # raises if not plain


# -- toggle_exchange -------------------------------------------------------- #

def test_toggle_uptake_preserves_magnitude(service: ModelService, session: str):
    rec = service.toggle_exchange(session, "EX_glc__D_e", ExchangeDirection.UPTAKE)
    assert isinstance(rec, ChangeRecord)
    assert rec.op == "toggle_exchange"
    assert rec.before == {"lower_bound": -10.0, "upper_bound": 1000.0}
    assert rec.after["lower_bound"] == -10.0   # magnitude preserved
    assert rec.after["upper_bound"] == 0.0
    assert rec.after["direction"] == "uptake"


def test_toggle_secretion(service: ModelService, session: str):
    rec = service.toggle_exchange(session, "EX_glc__D_e", ExchangeDirection.SECRETION)
    assert rec.after["lower_bound"] == 0.0
    assert rec.after["upper_bound"] == 1000.0


def test_toggle_blocked_then_both_uses_default(service: ModelService, session: str):
    service.toggle_exchange(session, "EX_glc__D_e", ExchangeDirection.BLOCKED)
    assert service.get_reaction(session, "EX_glc__D_e")["lower_bound"] == 0.0
    # from a fully-closed bound, BOTH falls back to the default magnitude
    rec = service.toggle_exchange(session, "EX_glc__D_e", ExchangeDirection.BOTH)
    assert rec.after["lower_bound"] == -1000.0
    assert rec.after["upper_bound"] == 1000.0


def test_toggle_accepts_raw_string(service: ModelService, session: str):
    rec = service.toggle_exchange(session, "EX_glc__D_e", "blocked")
    assert rec.after["lower_bound"] == 0.0
    assert rec.after["upper_bound"] == 0.0


@pytest.mark.filterwarnings("ignore:Solver status is 'infeasible'")
def test_toggle_blocked_kills_growth(service: ModelService, session: str):
    service.toggle_exchange(session, "EX_glc__D_e", ExchangeDirection.BLOCKED)
    res = service.fba(session)
    assert res.objective_value < 1e-6


def test_toggle_non_boundary_raises(service: ModelService, session: str):
    with pytest.raises(ValueError):
        service.toggle_exchange(session, "PFK", ExchangeDirection.UPTAKE)


def test_toggle_appended_to_change_log(service: ModelService, session: str):
    service.toggle_exchange(session, "EX_glc__D_e", ExchangeDirection.UPTAKE)
    log = service.change_log(session)
    assert log[-1].op == "toggle_exchange"


# -- set_medium ------------------------------------------------------------- #

def test_set_medium_applies_and_records(service: ModelService, session: str):
    medium = {"EX_glc__D_e": 5.0, "EX_o2_e": 1000.0,
              "EX_nh4_e": 1000.0, "EX_pi_e": 1000.0,
              "EX_h2o_e": 1000.0, "EX_h_e": 1000.0, "EX_co2_e": 1000.0}
    rec = service.set_medium(session, medium)
    assert isinstance(rec, ChangeRecord)
    assert rec.op == "set_medium"
    assert rec.before["EX_glc__D_e"] == 10.0
    assert rec.after["EX_glc__D_e"] == 5.0


def test_set_medium_closes_unlisted_exchanges(service: ModelService, session: str):
    # a medium without glucose closes glucose uptake
    service.set_medium(session, {"EX_o2_e": 1000.0, "EX_nh4_e": 1000.0,
                                 "EX_pi_e": 1000.0, "EX_h2o_e": 1000.0,
                                 "EX_h_e": 1000.0})
    glc = service.get_reaction(session, "EX_glc__D_e")
    assert glc["lower_bound"] == 0.0   # uptake closed


def test_set_medium_changes_growth(service: ModelService, session: str):
    full = service.fba(session).objective_value
    service.set_medium(session, {"EX_glc__D_e": 5.0, "EX_o2_e": 1000.0,
                                 "EX_nh4_e": 1000.0, "EX_pi_e": 1000.0,
                                 "EX_h2o_e": 1000.0, "EX_h_e": 1000.0,
                                 "EX_co2_e": 1000.0})
    limited = service.fba(session).objective_value
    assert math.isclose(full, GROWTH, rel_tol=1e-4)
    assert limited < full        # less glucose -> less growth

def test_set_medium_serializable(service: ModelService, session: str):
    rec = service.set_medium(session, {"EX_glc__D_e": 8.0, "EX_o2_e": 1000.0,
                                       "EX_nh4_e": 1000.0, "EX_pi_e": 1000.0,
                                       "EX_h2o_e": 1000.0, "EX_h_e": 1000.0,
                                       "EX_co2_e": 1000.0})
    json.dumps(asdict(rec))
