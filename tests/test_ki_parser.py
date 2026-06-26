"""Tests for the knock-in paste parser and validation."""
from __future__ import annotations

import cobra
import pytest

from gem_suite.ki_parser import (
    add_ki_reactions,
    parse_ki_block,
    parse_ki_line,
    validate_kis,
)


@pytest.fixture
def core():
    return cobra.io.read_sbml_model("tests/data/e_coli_core.xml.gz")


def test_parse_irreversible_line():
    r = parse_ki_line("BDH: 1.0 a_c + 2.0 b_c --> c_c")
    assert r["id"] == "BDH"
    assert r["reversible"] is False
    assert r["metabolites"] == {"a_c": -1.0, "b_c": -2.0, "c_c": 1.0}


def test_parse_reversible_default_coeffs():
    r = parse_ki_line("XYZ: x_c <=> y_c")
    assert r["reversible"] is True
    assert r["metabolites"] == {"x_c": -1.0, "y_c": 1.0}


def test_parse_block_collects_errors_and_skips_comments():
    reactions, errors = parse_ki_block(
        "R1: a_c --> b_c   # a comment\n"
        "\n"
        "bad line without colon\n"
        "R2: missing arrow here\n"
    )
    assert [r["id"] for r in reactions] == ["R1"]
    assert len(errors) == 2


def test_validate_duplicate_and_orphan(core):
    reactions, _ = parse_ki_block(
        "PFK: a_c --> b_c\n"            # duplicate of existing reaction
        "NEWR: glc__D_e --> zzz_c\n"    # zzz_c is an orphan metabolite
    )
    out = validate_kis(reactions, core)
    assert any("duplicate" in e for e in out["errors"])
    assert any("zzz_c" in w for w in out["warnings"])


def test_validate_unbalanced_warns(core):
    # atp_c -> adp_c drops phosphate: mass/charge imbalance among existing mets
    reactions, _ = parse_ki_block("BADBAL: atp_c --> adp_c")
    out = validate_kis(reactions, core)
    assert any("unbalanced" in w for w in out["warnings"])


def test_add_ki_reactions_round_trip(core):
    reactions, _ = parse_ki_block("SINKZ: atp_c --> novel_c")
    added = add_ki_reactions(core, reactions)
    assert added == ["SINKZ"]
    assert core.reactions.has_id("SINKZ")
    assert core.metabolites.has_id("novel_c")        # missing metabolite created
