"""Tests for run manifests."""
from __future__ import annotations

import json

import cobra

from gem_suite.manifest import build_manifest, model_hash, versions


def test_versions_reports_cobra():
    v = versions()
    assert "cobra" in v and v["cobra"]
    assert "gem_suite" in v


def test_model_hash_stable_and_edit_sensitive():
    m1 = cobra.io.read_sbml_model("tests/data/e_coli_core.xml.gz")
    m2 = cobra.io.read_sbml_model("tests/data/e_coli_core.xml.gz")
    h = model_hash(m1)
    assert h == model_hash(m2)                 # stable across reloads
    m1.reactions.PFK.upper_bound = 42.0
    assert model_hash(m1) != h                 # changes with an edit


def test_build_manifest_is_serializable_and_complete():
    man = build_manifest(
        operation="fba", model_label="e_coli_core", model_hash="abc123",
        solver="glpk", status="optimal", params={"loopless": False},
        extra={"objective_value": 0.873},
    )
    json.dumps(man)                            # plain/serializable
    assert man["operation"] == "fba"
    assert man["objective_value"] == 0.873     # extra merged at top level
    assert man["versions"]["cobra"]
    assert "created_at" in man
