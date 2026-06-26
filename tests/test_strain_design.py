"""Milestone-6 tests: strain design on e_coli_core (MCS, KO + KI plumbing).

All runs are kept tiny (restricted candidates, small max_size/max_solutions) so
they finish in ~1s on GLPK — genome-scale models are never used in the loop.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict

import cobra
import pytest

from gem_suite.app import controllers
from gem_suite.jobs import (
    JobSpec,
    JobType,
    LocalProcessBackend,
    StrainDesignParams,
)
from gem_suite.jobs.runners import (
    read_strain_design_json,
    run_strain_design,
    write_strain_design_json,
)
from gem_suite.strain_design import (
    StrainDesignResult,
    StrainDesignSolution,
    _prepare_knockins,
    design_strains,
)

# central-metabolism reactions that yield small ethanol-coupling cut sets fast
KO_CANDS = ["PFK", "PYK", "LDH_D", "PFL", "ACALD", "FRD7", "SUCDi",
            "PTAr", "ACKr", "ME1", "ME2", "MDH", "NADH16", "CYTBD", "ATPS4r"]


@pytest.fixture
def core() -> cobra.Model:
    return cobra.io.read_sbml_model("tests/data/e_coli_core.xml.gz")


@pytest.fixture
def backend():
    be = LocalProcessBackend(max_workers=1)
    try:
        yield be
    finally:
        be.shutdown(wait=False)


def _mcs_params(**over) -> StrainDesignParams:
    base = dict(target_reaction="EX_etoh_e", approach="MCS", gene_level=False,
                ko_candidates=KO_CANDS, min_growth=0.05, min_yield=0.0,
                max_size=3, max_solutions=3)
    base.update(over)
    return StrainDesignParams(**base)


# -- wrapper: MCS reaction-level ------------------------------------------- #

def test_mcs_reaction_level(core):
    res = design_strains(core, _mcs_params(), solver="glpk")
    assert isinstance(res, StrainDesignResult)
    assert res.status == "optimal"
    assert res.gene_level is False
    assert res.solutions
    for sol in res.solutions:
        assert sol.level == "reaction"
        assert sol.knockouts                      # non-empty cut set
        assert set(sol.knockouts) <= set(KO_CANDS)
        assert sol.knockins == []
        assert sol.cost == len(sol.knockouts)


def test_mcs_respects_max_size(core):
    res = design_strains(core, _mcs_params(max_size=1), solver="glpk")
    for sol in res.solutions:
        assert len(sol.knockouts) <= 1


# -- wrapper: MCS gene-level ----------------------------------------------- #

def test_mcs_gene_level(core):
    res = design_strains(
        core,
        _mcs_params(gene_level=True, ko_candidates=None, max_size=2, max_solutions=2),
        solver="glpk",
    )
    assert res.status == "optimal"
    assert res.gene_level is True
    assert res.solutions
    for sol in res.solutions:
        assert sol.level == "gene"
        assert all(k.startswith("b") for k in sol.knockouts)   # e_coli_core gene ids


# -- knock-in plumbing ------------------------------------------------------ #

def test_prepare_knockins_merges_from_database(core, model_path):
    core.remove_reactions([core.reactions.PGI])
    assert not core.reactions.has_id("PGI")
    ki = _prepare_knockins(
        core,
        StrainDesignParams(target_reaction="x", ki_candidates=["PGI"],
                           ki_database=model_path),
    )
    assert ki == {"PGI": 1.0}
    assert core.reactions.has_id("PGI")            # re-added from the database


def test_prepare_knockins_missing_without_db_raises(core):
    with pytest.raises(ValueError):
        _prepare_knockins(
            core,
            StrainDesignParams(target_reaction="x", ki_candidates=["NOT_A_RXN"]),
        )


def test_prepare_knockins_none_when_no_candidates(core):
    assert _prepare_knockins(core, StrainDesignParams(target_reaction="x")) is None


# -- result JSON serde ------------------------------------------------------ #

def test_strain_design_json_roundtrip(tmp_path):
    result = StrainDesignResult(
        status="optimal", approach="MCS", gene_level=False,
        solutions=[StrainDesignSolution(["ATPS4r", "NADH16"], [], 2.0, "reaction")],
    )
    path = str(tmp_path / "sd.json")
    write_strain_design_json(result, path)
    loaded = read_strain_design_json(path)
    assert loaded == result
    json.dumps(asdict(result))   # plain/serializable


def test_run_strain_design_from_spec(model_path):
    spec = JobSpec(job_type=JobType.STRAIN_DESIGN, model_path=model_path,
                   params=_mcs_params().to_params(), solver="glpk")
    res = run_strain_design(spec)
    assert res.status == "optimal"
    assert res.solutions


# -- end-to-end through the job layer -------------------------------------- #

def test_strain_design_job_end_to_end(backend, model_path):
    spec = JobSpec(job_type=JobType.STRAIN_DESIGN, model_path=model_path,
                   params=_mcs_params().to_params(), solver="glpk")
    job_id = backend.submit(spec)
    deadline = time.time() + 180
    while time.time() < deadline:
        st = backend.status(job_id)
        if st.state.value in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert st.state.value == "succeeded", st.error
    assert st.result_path.endswith(".json")        # per-type artifact suffix
    result = backend.result(job_id)
    assert isinstance(result, StrainDesignResult)
    assert result.solutions


# -- modules-based design + verification ----------------------------------- #

def test_modules_design_verifies(core):
    params = StrainDesignParams(
        approach="MCS", gene_level=False, ko_candidates=KO_CANDS,
        max_size=3, max_solutions=2,
        modules=[
            {"type": "suppress",
             "constraints": ["Biomass_Ecoli_core >= 0.05", "EX_etoh_e <= 0",
                             "EX_glc__D_e <= -0.1"]},
            {"type": "protect", "constraints": ["Biomass_Ecoli_core >= 0.05"]},
        ],
    )
    result = design_strains(core, params, solver="glpk")
    assert result.status == "optimal" and result.solutions
    for sol in result.solutions:
        kinds = {v["module_type"]: v["passed"] for v in sol.verification}
        assert kinds == {"suppress": True, "protect": True}
        assert sol.efm is not None and "is_efm" in sol.efm


def test_verification_detects_wrong_design(core):
    from gem_suite.strain_design import StrainDesignSolution, verify_design

    params = StrainDesignParams(approach="MCS", gene_level=False, modules=[
        {"type": "suppress",
         "constraints": ["Biomass_Ecoli_core >= 0.05", "EX_etoh_e <= 0",
                         "EX_glc__D_e <= -0.1"]}])
    empty = StrainDesignSolution(knockouts=[], knockins=[], cost=0.0, level="reaction")
    rows = verify_design(core, params, empty, "glpk")
    # with no knockouts the suppress region is still feasible -> FAIL
    assert rows[0]["module_type"] == "suppress" and rows[0]["passed"] is False


# -- app controllers -------------------------------------------------------- #

def test_submit_strain_design_controller(service, session, backend, tmp_path):
    store = {
        "modules": [
            {"type": "suppress",
             "constraints": ["Biomass_Ecoli_core >= 0.05", "EX_etoh_e <= 0",
                             "EX_glc__D_e <= -0.1"]},
            {"type": "protect", "constraints": ["Biomass_Ecoli_core >= 0.05"]},
        ],
        "approach": "MCS", "gene_level": False, "ko_candidates": KO_CANDS,
        "max_size": 3, "max_solutions": 3,
    }
    job_id = controllers.submit_strain_design(service, backend, session, store,
                                              export_dir=str(tmp_path))
    deadline = time.time() + 180
    while time.time() < deadline:
        if controllers.job_status(backend, job_id)["done"]:
            break
        time.sleep(0.05)
    rows = controllers.strain_design_solution_rows(backend, job_id)
    assert rows
    assert {"#", "level", "cost", "knockouts", "knockins", "verification",
            "efm"} == set(rows[0])
    # verification ran and passed for the returned designs
    verif = controllers.strain_design_verification_rows(backend, job_id, 0)
    assert verif and all(v["result"] == "PASS" for v in verif)
    json.dumps(rows)
