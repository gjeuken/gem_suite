"""Every goal preset must resolve, build, solve, and verify on e_coli_core."""
from __future__ import annotations

import cobra
import pytest

from gem_suite.presets import PRESETS, resolve_preset
from gem_suite.jobs.spec import StrainDesignParams
from gem_suite.strain_design import design_strains

BIOMASS = "Biomass_Ecoli_core"
# a central-metabolism candidate set that gives small, fast cut sets
KO_CANDS = ["PFK", "PYK", "LDH_D", "PFL", "ACALD", "FRD7", "SUCDi", "PTAr",
            "ACKr", "ME1", "ME2", "MDH", "NADH16", "CYTBD", "ATPS4r", "PGI"]


@pytest.fixture
def core():
    return cobra.io.read_sbml_model("tests/data/e_coli_core.xml.gz")


def test_resolve_preset_fills_placeholders():
    resolved = resolve_preset("wgcp", sub="EX_glc__D_e", prod="EX_etoh_e",
                              ymin=0.2, growth=BIOMASS)
    assert resolved["approach"] == "MCS"
    blob = " ".join(c for m in resolved["modules"] for c in m["constraints"])
    assert "{" not in blob and "}" not in blob          # no unresolved placeholders
    assert "EX_etoh_e" in blob and "EX_glc__D_e" in blob and BIOMASS in blob


@pytest.mark.parametrize("preset", [p.key for p in PRESETS])
def test_preset_designs_and_verifies(core, preset):
    resolved = resolve_preset(preset, sub="EX_glc__D_e", prod="EX_etoh_e",
                              ymin=0.2, growth=BIOMASS)
    params = StrainDesignParams(
        approach=resolved["approach"], modules=resolved["modules"],
        gene_level=False, ko_candidates=KO_CANDS, max_size=4, max_solutions=1,
    )
    result = design_strains(core, params, solver="glpk")
    assert result.status in ("optimal", "infeasible", "time_limit")
    # if a design was found, its verification must pass (protect feasible,
    # suppress infeasible) on the intervened model
    for sol in result.solutions:
        assert sol.verification                          # was verified
        assert all(v["passed"] for v in sol.verification)
