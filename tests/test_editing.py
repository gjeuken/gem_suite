"""Milestone-3 tests: add/remove reactions, set objective, reset, export."""
from __future__ import annotations

import json
import math
from dataclasses import asdict

import pytest

from gem_suite import ChangeRecord, ModelService

N_REACTIONS = 95


# -- add_reaction ----------------------------------------------------------- #

def test_add_reaction(service: ModelService, session: str):
    rec = service.add_reaction(
        session, "ATPSINK", "ATP sink",
        {"atp_c": -1.0, "adp_c": 1.0},
        lower_bound=0.0, upper_bound=500.0,
        gene_reaction_rule="b9999",
    )
    assert isinstance(rec, ChangeRecord)
    assert rec.op == "add_reaction"
    assert rec.before == {}
    assert rec.after["upper_bound"] == 500.0
    assert rec.after["gene_reaction_rule"] == "b9999"

    rxn = service.get_reaction(session, "ATPSINK")
    assert rxn["lower_bound"] == 0.0 and rxn["upper_bound"] == 500.0
    assert len(service.list_reactions(session)) == N_REACTIONS + 1
    # new gene was created
    assert "b9999" in service.get_reaction(session, "ATPSINK")["gene_reaction_rule"]


def test_add_reaction_duplicate_raises(service: ModelService, session: str):
    with pytest.raises(ValueError):
        service.add_reaction(session, "PFK", "dup", {"atp_c": -1.0})


def test_add_reaction_unknown_metabolite_raises(service: ModelService, session: str):
    with pytest.raises(ValueError):
        service.add_reaction(session, "NEWRXN", "n", {"nonexist_c": -1.0})


def test_add_reaction_creates_missing_metabolite(service: ModelService, session: str):
    n_mets = service.summary(session)["n_metabolites"]
    service.add_reaction(
        session, "NEWRXN", "n",
        {"atp_c": -1.0, "novel_c": 1.0},
        create_missing_metabolites=True,
    )
    assert service.summary(session)["n_metabolites"] == n_mets + 1


def test_add_reaction_invalid_bounds(service: ModelService, session: str):
    with pytest.raises(ValueError):
        service.add_reaction(session, "NEWRXN", "n", {"atp_c": -1.0},
                             lower_bound=10.0, upper_bound=-10.0)


# -- remove_reaction -------------------------------------------------------- #

def test_remove_reaction(service: ModelService, session: str):
    rec = service.remove_reaction(session, "PFK")
    assert rec.op == "remove_reaction"
    assert rec.target == "PFK"
    assert rec.before["id"] == "PFK"
    assert rec.after == {}
    assert len(service.list_reactions(session)) == N_REACTIONS - 1
    with pytest.raises(KeyError):
        service.get_reaction(session, "PFK")


def test_remove_reaction_unknown_raises(service: ModelService, session: str):
    with pytest.raises(KeyError):
        service.remove_reaction(session, "NOPE")


def test_remove_reaction_remove_orphans(service: ModelService, session: str):
    # add an isolated reaction with its own metabolite + gene, then remove it
    service.add_reaction(session, "ORPHRXN", "o",
                         {"orphan_c": -1.0}, gene_reaction_rule="gorph",
                         create_missing_metabolites=True)
    n_mets = service.summary(session)["n_metabolites"]
    service.remove_reaction(session, "ORPHRXN", remove_orphans=True)
    assert service.summary(session)["n_metabolites"] == n_mets - 1


# -- set_objective ---------------------------------------------------------- #

def test_set_objective_string(service: ModelService, session: str):
    rec = service.set_objective(session, "ATPM")
    assert rec.op == "set_objective"
    assert rec.target == "ATPM"
    assert "Biomass" in rec.before["expression"]
    assert "ATPM" in rec.after["expression"]
    # optimizing now maximizes ATPM
    assert service.summary(session)["objective"].count("ATPM") >= 1


def test_set_objective_dict(service: ModelService, session: str):
    rec = service.set_objective(session, {"PFK": 1.0, "PGI": 0.5})
    assert "PFK" in rec.after["expression"]
    assert "PGI" in rec.after["expression"]


def test_set_objective_unknown_raises(service: ModelService, session: str):
    with pytest.raises(KeyError):
        service.set_objective(session, "NOPE")


def test_set_objective_changes_fba(service: ModelService, session: str):
    service.set_objective(session, "ATPM")
    res = service.fba(session)
    assert res.status == "optimal"
    # ATPM max flux far exceeds the biomass objective value
    assert res.objective_value > 1.0


def test_set_objective_direction_min(service: ModelService, session: str):
    rec = service.set_objective(session, "ATPM", direction="min")
    assert rec.after["direction"] == "min"
    res = service.fba(session)
    assert res.status == "optimal"
    # minimising ATPM drives it to its lower bound
    lb = service.get_reaction(session, "ATPM")["lower_bound"]
    assert math.isclose(res.objective_value, lb, rel_tol=1e-4)


def test_set_objective_direction_default_preserves_sense(service: ModelService, session: str):
    # no direction given -> keep the model's current sense (max)
    rec = service.set_objective(session, "ATPM")
    assert rec.after["direction"] == "max"


def test_set_objective_invalid_direction_raises(service: ModelService, session: str):
    with pytest.raises(ValueError):
        service.set_objective(session, "ATPM", direction="sideways")


# -- reset ------------------------------------------------------------------ #

def test_reset_reverts_edits(service: ModelService, session: str):
    service.set_bounds(session, "PFK", lower=-999.0)
    service.remove_reaction(session, "PGI")
    service.add_reaction(session, "NEWRXN", "n", {"atp_c": -1.0})
    service.set_objective(session, "ATPM")

    service.reset(session)

    assert len(service.list_reactions(session)) == N_REACTIONS
    assert service.get_reaction(session, "PFK")["lower_bound"] == 0.0
    assert service.get_reaction(session, "PGI")["id"] == "PGI"   # back
    with pytest.raises(KeyError):
        service.get_reaction(session, "NEWRXN")                  # gone
    assert "Biomass" in service.summary(session)["objective"]
    assert service.change_log(session) == []


def test_reset_clears_flux_cache(service: ModelService, session: str):
    service.fba(session)
    assert service.get_reaction(session, "PFK")["flux"] is not None
    service.reset(session)
    assert service.get_reaction(session, "PFK")["flux"] is None


def test_reset_snapshot_is_independent(service: ModelService, session: str):
    """Editing after a reset must not corrupt the pristine snapshot."""
    service.set_bounds(session, "PFK", lower=-1.0)
    service.reset(session)
    service.set_bounds(session, "PFK", lower=-2.0)
    service.reset(session)
    assert service.get_reaction(session, "PFK")["lower_bound"] == 0.0


# -- export_model ----------------------------------------------------------- #

@pytest.mark.parametrize("fmt, ext", [("sbml", "xml"), ("json", "json"), ("mat", "mat")])
def test_export_model_roundtrip(service: ModelService, session: str, tmp_path, fmt, ext):
    # edit, export, reload into a fresh session: edits must survive
    service.set_bounds(session, "PFK", upper=123.0)
    out = tmp_path / f"edited.{ext}"
    returned = service.export_model(session, str(out), fmt=fmt)
    assert returned == str(out)
    assert out.exists()

    sid2 = service.load_model(str(out))
    assert service.get_reaction(sid2, "PFK")["upper_bound"] == 123.0


def test_export_model_unknown_format(service: ModelService, session: str, tmp_path):
    with pytest.raises(ValueError):
        service.export_model(session, str(tmp_path / "x.foo"), fmt="foo")


# -- change-log serializability across edit types -------------------------- #

def test_change_log_serializable(service: ModelService, session: str):
    service.set_bounds(session, "PFK", upper=10.0)
    service.add_reaction(session, "NEWRXN", "n", {"atp_c": -1.0})
    service.remove_reaction(session, "PGI")
    service.set_objective(session, "ATPM")
    log = service.change_log(session)
    assert [r.op for r in log] == [
        "set_bounds", "add_reaction", "remove_reaction", "set_objective",
    ]
    json.dumps([asdict(r) for r in log])
