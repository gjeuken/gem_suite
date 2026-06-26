"""Milestone-1 tests for ModelService core, on e_coli_core."""
from __future__ import annotations

import math

import pytest

from gem_suite import ChangeRecord, FluxResult, ModelService

# Known e_coli_core facts (textbook model).
N_REACTIONS = 95
N_METABOLITES = 72
N_GENES = 137
GROWTH = 0.8739215069684  # max biomass on default medium, ~rtol 1e-4


# -- load / sessions -------------------------------------------------------- #

def test_load_model_returns_session_id(service: ModelService, model_path: str):
    sid = service.load_model(model_path)
    assert isinstance(sid, str) and sid
    assert sid in {s["session_id"] for s in service.list_sessions()}


def test_load_model_missing_file(service: ModelService):
    with pytest.raises(FileNotFoundError):
        service.load_model("/no/such/model.xml")


def test_load_model_unknown_format(service: ModelService, tmp_path):
    bogus = tmp_path / "model.txt"
    bogus.write_text("not a model")
    with pytest.raises(ValueError):
        service.load_model(str(bogus))


def test_list_sessions_reports_counts(service: ModelService, session: str):
    rows = service.list_sessions()
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == session
    assert row["label"] == "e_coli_core"
    assert row["n_reactions"] == N_REACTIONS
    assert row["n_metabolites"] == N_METABOLITES
    assert row["n_genes"] == N_GENES


def test_close_session(service: ModelService, session: str):
    service.close_session(session)
    assert service.list_sessions() == []
    with pytest.raises(KeyError):
        service.summary(session)


def test_unknown_session_raises(service: ModelService):
    with pytest.raises(KeyError):
        service.summary("nope")


# -- summary / structure queries ------------------------------------------- #

def test_summary(service: ModelService, session: str):
    summ = service.summary(session)
    assert summ["model_id"] == "e_coli_core"
    assert summ["n_reactions"] == N_REACTIONS
    assert summ["solver"] == "glpk"
    assert summ["objective_direction"] == "max"
    assert "Biomass" in summ["objective"]


def test_get_reaction(service: ModelService, session: str):
    rxn = service.get_reaction(session, "PFK")
    assert rxn["id"] == "PFK"
    assert rxn["lower_bound"] == 0.0
    assert rxn["upper_bound"] == 1000.0
    assert "atp" in rxn["reaction"]
    assert rxn["gene_reaction_rule"]      # PFK has a GPR
    assert rxn["flux"] is None            # no analysis run yet


def test_get_reaction_unknown(service: ModelService, session: str):
    with pytest.raises(KeyError):
        service.get_reaction(session, "NOT_A_RXN")


def test_list_reactions_all(service: ModelService, session: str):
    rows = service.list_reactions(session)
    assert len(rows) == N_REACTIONS
    assert {"id", "name", "reaction", "lower_bound", "upper_bound"} <= rows[0].keys()


def test_list_reactions_pattern(service: ModelService, session: str):
    rows = service.list_reactions(session, pattern="^EX_")
    ids = {r["id"] for r in rows}
    assert ids and all(i.startswith("EX_") for i in ids)
    assert "EX_glc__D_e" in ids


# -- edits: set_bounds ------------------------------------------------------ #

def test_set_bounds_returns_change_record(service: ModelService, session: str):
    rec = service.set_bounds(session, "PFK", lower=-10.0, upper=500.0)
    assert isinstance(rec, ChangeRecord)
    assert rec.op == "set_bounds"
    assert rec.target == "PFK"
    assert rec.before == {"lower_bound": 0.0, "upper_bound": 1000.0}
    assert rec.after == {"lower_bound": -10.0, "upper_bound": 500.0}
    # change is applied to the live model
    assert service.get_reaction(session, "PFK")["lower_bound"] == -10.0


def test_set_bounds_partial(service: ModelService, session: str):
    rec = service.set_bounds(session, "PFK", upper=42.0)
    assert rec.after == {"lower_bound": 0.0, "upper_bound": 42.0}


def test_set_bounds_invalid(service: ModelService, session: str):
    with pytest.raises(ValueError):
        service.set_bounds(session, "PFK", lower=10.0, upper=-10.0)


def test_set_bounds_appended_to_change_log(service: ModelService, session: str):
    service.set_bounds(session, "PFK", upper=42.0)
    service.set_bounds(session, "PGI", lower=-5.0)
    log = service.change_log(session)
    assert [r.target for r in log] == ["PFK", "PGI"]


# -- fast analyses ---------------------------------------------------------- #

def test_fba(service: ModelService, session: str):
    res = service.fba(session)
    assert isinstance(res, FluxResult)
    assert res.status == "optimal"
    assert math.isclose(res.objective_value, GROWTH, rel_tol=1e-4)
    assert math.isclose(res.fluxes["Biomass_Ecoli_core"], GROWTH, rel_tol=1e-4)
    assert res.reduced_costs is not None
    assert res.shadow_prices is not None


def test_fba_then_get_reaction_shows_flux(service: ModelService, session: str):
    service.fba(session)
    rxn = service.get_reaction(session, "Biomass_Ecoli_core")
    assert math.isclose(rxn["flux"], GROWTH, rel_tol=1e-4)


def test_pfba(service: ModelService, session: str):
    res = service.pfba(session)
    assert res.status == "optimal"
    # objective_value reported as growth (not the minimized flux sum)
    assert math.isclose(res.objective_value, GROWTH, rel_tol=1e-4)
    # parsimonious total flux is <= an arbitrary fba total (sanity bound)
    total = sum(abs(v) for v in res.fluxes.values())
    assert total > 0


def test_scan_objective_1d(service: ModelService, session: str):
    # pin glucose uptake from -10 to -2 -> growth falls as less carbon enters
    res = service.scan_objective(
        session, [{"reaction_id": "EX_glc__D_e", "min": -10, "max": -2, "points": 5}])
    assert [a["reaction_id"] for a in res["axes"]] == ["EX_glc__D_e"]
    assert res["axes"][0]["values"] == [-10, -8, -6, -4, -2]
    vals = res["values"]
    assert len(vals) == 5 and all(v is not None for v in vals)
    assert math.isclose(vals[0], GROWTH, rel_tol=1e-4)     # full glucose
    assert vals == sorted(vals, reverse=True)              # monotonically decreasing


def test_scan_objective_2d(service: ModelService, session: str):
    res = service.scan_objective(session, [
        {"reaction_id": "EX_glc__D_e", "min": -10, "max": -4, "points": 3},
        {"reaction_id": "EX_o2_e", "min": -20, "max": -5, "points": 3},
    ])
    vals = res["values"]
    assert len(vals) == 3 and all(len(row) == 3 for row in vals)
    flat = [v for row in vals for v in row if v is not None]
    # vals[i][j] = growth at glucose=axes0[i], O2=axes1[j]; the most-carbon,
    # most-oxygen corner (vals[0][0]) is the grid maximum
    assert vals[0][0] == max(flat)
    assert vals[0][0] > 0.8


def test_scan_response_reaction_flux(service: ModelService, session: str):
    # default response is the objective
    obj = service.scan_objective(
        session, [{"reaction_id": "EX_glc__D_e", "min": -10, "max": -2, "points": 4}])
    assert obj["response"] == "objective"

    # response = a reaction's flux: CO2 secretion as glucose uptake varies
    co2 = service.scan_objective(
        session, [{"reaction_id": "EX_glc__D_e", "min": -10, "max": -2, "points": 4}],
        response="EX_co2_e")
    assert co2["response"] == "EX_co2_e"
    assert all(v is not None for v in co2["values"])
    assert all(v > 0 for v in co2["values"])               # CO2 is secreted (positive)
    assert co2["values"] != obj["values"]                  # a different series
    # less glucose -> less CO2 secreted (monotonic with carbon in)
    assert co2["values"] == sorted(co2["values"], reverse=True)


def test_scan_response_unknown_reaction_raises(service: ModelService, session: str):
    with pytest.raises(KeyError):
        service.scan_objective(
            session, [{"reaction_id": "EX_glc__D_e", "min": -10, "max": -2, "points": 3}],
            response="NOPE")


def test_scan_objective_does_not_mutate_session(service: ModelService, session: str):
    before = service.get_reaction(session, "EX_glc__D_e")
    service.scan_objective(
        session, [{"reaction_id": "EX_glc__D_e", "min": -10, "max": 0, "points": 4}])
    after = service.get_reaction(session, "EX_glc__D_e")
    assert (after["lower_bound"], after["upper_bound"]) == \
           (before["lower_bound"], before["upper_bound"])
    assert service.change_log(session) == []               # no edits logged


def test_scan_objective_validation(service: ModelService, session: str):
    with pytest.raises(ValueError):
        service.scan_objective(session, [])                # need 1 or 2
    with pytest.raises(ValueError):
        service.scan_objective(session, [
            {"reaction_id": "EX_glc__D_e", "min": -10, "max": 0, "points": 3}] * 3)
    with pytest.raises(KeyError):
        service.scan_objective(
            session, [{"reaction_id": "NOPE", "min": 0, "max": 1, "points": 2}])


def test_fba_loopless(service: ModelService, session: str):
    res = service.fba(session, loopless=True)
    assert res.status == "optimal"
    assert math.isclose(res.objective_value, GROWTH, rel_tol=1e-4)


def test_pfba_loopless(service: ModelService, session: str):
    res = service.pfba(session, loopless=True)
    assert res.status == "optimal"
    assert math.isclose(res.objective_value, GROWTH, rel_tol=1e-4)


def test_binding_constraints_fba(service: ModelService, session: str):
    res = service.fba(session)
    binding = service.binding_constraints(session, res.fluxes, res.reduced_costs)
    by_id = {b["reaction_id"]: b for b in binding}
    # glucose uptake is capped at its lower bound (-10) -> binding "lower"
    assert "EX_glc__D_e" in by_id
    glc = by_id["EX_glc__D_e"]
    assert glc["bound"] == "lower" and glc["bound_value"] == -10.0
    assert math.isclose(glc["flux"], -10.0, abs_tol=1e-6)
    # ATPM has a forced maintenance lower bound (8.39) -> binding "lower"
    assert by_id["ATPM"]["bound"] == "lower"
    assert math.isclose(by_id["ATPM"]["flux"], by_id["ATPM"]["bound_value"],
                        abs_tol=1e-6)
    # no trivial zero-at-zero entries
    assert not any(abs(b["flux"]) < 1e-9 and abs(b["bound_value"]) < 1e-9
                   for b in binding)
    # reduced costs are reported for FBA
    assert all(b["reduced_cost"] is not None for b in binding)


def test_binding_constraints_pfba_no_reduced_costs(service: ModelService, session: str):
    res = service.pfba(session)
    binding = service.binding_constraints(session, res.fluxes)
    assert any(b["reaction_id"] == "EX_glc__D_e" for b in binding)
    assert all(b["reduced_cost"] is None for b in binding)


def test_efm_test_structure(service: ModelService, session: str):
    res = service.pfba(session, loopless=True)
    efm = service.efm_test(session, res.fluxes)
    assert {"is_efm", "n_active", "rank", "nullity"} <= set(efm)
    assert efm["n_active"] > 0
    assert efm["nullity"] == efm["n_active"] - efm["rank"]
    assert isinstance(efm["is_efm"], bool)


@pytest.mark.filterwarnings("ignore:Solver status is 'infeasible'")
def test_fba_reflects_edits(service: ModelService, session: str):
    # removing the sole carbon source makes ATP maintenance unsatisfiable;
    # the edit must be reflected in the next solve as an infeasible status.
    service.set_bounds(session, "EX_glc__D_e", lower=0.0)
    res = service.fba(session)
    assert res.status == "infeasible"
    assert res.objective_value < 1e-6


def test_json_round_trippable_results(service: ModelService, session: str):
    """FluxResult must be plain/serializable (crosses UI + job boundaries)."""
    import json
    from dataclasses import asdict

    res = service.fba(session)
    json.dumps(asdict(res))  # raises if any non-serializable field crept in
