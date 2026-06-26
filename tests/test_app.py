"""Milestone-5 tests: app controllers against a live ModelService + app build.

The Dash callbacks are thin wiring over controllers.py, which is what we test
here (no browser). A separate test asserts the app object builds and registers
callbacks.
"""
from __future__ import annotations

import json
import math
import time

import pytest

from gem_suite.app import controllers
from gem_suite.app.main import create_app
from gem_suite.jobs import LocalProcessBackend

GROWTH = 0.8739215069684


@pytest.fixture
def backend():
    be = LocalProcessBackend(max_workers=1)
    try:
        yield be
    finally:
        be.shutdown(wait=False)


# -- load / structure ------------------------------------------------------- #

def test_load_model_controller(service, model_path):
    out = controllers.load_model(service, model_path, label="core")
    assert out["session_id"]
    assert out["summary"]["n_reactions"] == 95
    assert out["summary"]["label"] == "core"


def test_load_model_from_upload(service, model_path, tmp_path):
    import base64

    raw = open(model_path, "rb").read()
    contents = "data:application/gzip;base64," + base64.b64encode(raw).decode()
    out = controllers.load_model_from_upload(
        service, contents, "e_coli_core.xml.gz", label="uploaded",
        upload_dir=str(tmp_path),
    )
    assert out["summary"]["n_reactions"] == 95          # format inferred from name
    assert out["summary"]["label"] == "uploaded"
    # the bytes were materialised under the original basename
    assert (tmp_path / "e_coli_core.xml.gz").exists()


def test_load_model_from_upload_rejects_empty(service):
    with pytest.raises(ValueError):
        controllers.load_model_from_upload(service, "", "x.xml")


def test_reaction_rows_and_filter(service, session):
    assert len(controllers.reaction_rows(service, session)) == 95
    ex = controllers.reaction_rows(service, session, pattern="^EX_")
    assert ex and all(r["id"].startswith("EX_") for r in ex)


def test_set_bounds_controller(service, session):
    rec = controllers.set_bounds(service, session, "PFK", lower=-5, upper=500)
    assert rec["op"] == "set_bounds"
    assert service.get_reaction(session, "PFK")["lower_bound"] == -5.0


def test_set_bounds_handles_blank(service, session):
    # blank string from a grid cell means "leave unchanged"
    controllers.set_bounds(service, session, "PFK", lower="", upper=42)
    rxn = service.get_reaction(session, "PFK")
    assert rxn["lower_bound"] == 0.0 and rxn["upper_bound"] == 42.0


# -- exchanges -------------------------------------------------------------- #

def test_exchange_rows(service, session):
    rows = controllers.exchange_rows(service, session)
    assert len(rows) == 20
    glc = next(r for r in rows if r["reaction_id"] == "EX_glc__D_e")
    assert isinstance(glc["direction"], str)   # plain string, not enum
    assert glc["kind"] == "exchange"
    json.dumps(rows)                            # grid-serializable


def test_toggle_exchange_controller(service, session):
    controllers.toggle_exchange(service, session, "EX_glc__D_e", "blocked")
    rxn = service.get_reaction(session, "EX_glc__D_e")
    assert rxn["lower_bound"] == 0.0 and rxn["upper_bound"] == 0.0


# -- fast analyses ---------------------------------------------------------- #

def test_run_fba_controller(service, session):
    out = controllers.run_fba(service, session)
    assert out["status"] == "optimal"
    assert math.isclose(out["objective_value"], GROWTH, rel_tol=1e-4)
    assert out["n_active"] > 0
    # fluxes sorted by descending magnitude
    mags = [abs(f["flux"]) for f in out["fluxes"]]
    assert mags == sorted(mags, reverse=True)
    json.dumps(out)


def test_run_pfba_controller(service, session):
    out = controllers.run_pfba(service, session)
    assert out["status"] == "optimal"
    assert math.isclose(out["objective_value"], GROWTH, rel_tol=1e-4)


def test_run_scan_1d_and_figure(service, session):
    from gem_suite.app.pages.scan import build_scan_figure

    res = controllers.run_scan(
        service, session,
        {"reaction_id": "EX_glc__D_e", "min": -10, "max": -2, "points": 5})
    assert len(res["axes"]) == 1 and len(res["values"]) == 5
    fig = build_scan_figure(res)
    assert fig.data[0].type == "scatter"
    assert list(fig.data[0].x) == [-10, -8, -6, -4, -2]


def test_run_scan_2d_and_surface(service, session):
    from gem_suite.app.pages.scan import build_scan_figure

    res = controllers.run_scan(
        service, session,
        {"reaction_id": "EX_glc__D_e", "min": -10, "max": -4, "points": 3},
        {"reaction_id": "EX_o2_e", "min": -20, "max": -5, "points": 3})
    assert len(res["axes"]) == 2
    fig = build_scan_figure(res)
    assert fig.data[0].type == "surface"
    assert list(fig.data[0].x) == res["axes"][1]["values"]   # x = second axis
    assert list(fig.data[0].y) == res["axes"][0]["values"]   # y = first axis


def test_exchange_flux_diagram(service, session):
    out = controllers.run_fba(service, session)
    fluxes = {f["reaction"]: f["flux"] for f in out["fluxes"]}
    diagram = controllers.exchange_flux_diagram(service, session, fluxes)

    up = {e["reaction"]: e["flux"] for e in diagram["uptake"]}
    sec = {e["reaction"]: e["flux"] for e in diagram["secretion"]}
    # glucose + O2 are taken up (negative); CO2 is secreted (positive)
    assert up["EX_glc__D_e"] < 0 and up["EX_o2_e"] < 0
    assert sec["EX_co2_e"] > 0
    assert all(e["flux"] < 0 for e in diagram["uptake"])
    assert all(e["flux"] > 0 for e in diagram["secretion"])
    # uptake sorted most-negative first
    up_fluxes = [e["flux"] for e in diagram["uptake"]]
    assert up_fluxes == sorted(up_fluxes)
    json.dumps(diagram)


def test_exchange_flux_diagram_includes_biomass_when_objective(service, session):
    # default objective is biomass -> growth shown as an outgoing flux
    out = controllers.run_fba(service, session)
    fluxes = {f["reaction"]: f["flux"] for f in out["fluxes"]}
    diagram = controllers.exchange_flux_diagram(service, session, fluxes)
    growth = [e for e in diagram["secretion"] if e.get("growth")]
    assert len(growth) == 1
    assert "Biomass" in growth[0]["reaction"]
    assert math.isclose(growth[0]["flux"], GROWTH, rel_tol=1e-4)
    assert growth[0]["metabolite"] == "biomass"


def test_exchange_flux_diagram_no_biomass_for_other_objective(service, session):
    # objective changed to a non-biomass reaction -> no growth arrow
    controllers.set_objective(service, session, "ATPM")
    out = controllers.run_fba(service, session)
    fluxes = {f["reaction"]: f["flux"] for f in out["fluxes"]}
    diagram = controllers.exchange_flux_diagram(service, session, fluxes)
    assert not any(e.get("growth") for e in diagram["secretion"])


def test_build_exchange_flux_figure():
    from gem_suite.app.pages.analysis import build_exchange_flux_figure

    diagram = {
        "uptake": [{"reaction": "EX_glc__D_e", "metabolite": "glc__D_e",
                    "name": "D-Glucose exchange", "flux": -10.0}],
        "secretion": [{"reaction": "EX_co2_e", "metabolite": "co2_e",
                       "name": "CO2 exchange", "flux": 22.8}],
    }
    fig = build_exchange_flux_figure(diagram)
    assert fig.layout.shapes                                  # the cell rectangle
    texts = [a.text for a in fig.layout.annotations]
    assert "cell" in texts
    assert "glc__D_e" in texts and "co2_e" in texts           # metabolite labels
    assert "-10" in texts and "22.8" in texts                 # flux values on arrows
    # one flow arrow per exchange
    arrows = [a for a in fig.layout.annotations if a.showarrow]
    assert len(arrows) == 2

    empty = build_exchange_flux_figure({"uptake": [], "secretion": []})
    assert any("No non-zero exchange" in (a.text or "") for a in empty.layout.annotations)


def test_build_exchange_flux_figure_growth_colored():
    from gem_suite.app.pages.analysis import (
        _GROWTH_COLOR, build_exchange_flux_figure,
    )

    diagram = {"uptake": [],
               "secretion": [{"reaction": "Biomass_Ecoli_core", "metabolite": "biomass",
                              "name": "biomass", "flux": 0.87, "growth": True}]}
    fig = build_exchange_flux_figure(diagram)
    arrows = [a for a in fig.layout.annotations if a.showarrow]
    assert len(arrows) == 1
    assert arrows[0].arrowcolor == _GROWTH_COLOR        # growth gets its own colour


def test_reaction_options(service, session):
    opts = controllers.reaction_options(service, session)
    assert len(opts) == 95
    assert {"label", "value"} == set(opts[0])
    values = {o["value"] for o in opts}
    assert "ATPM" in values and "PFK" in values
    # label is searchable by id + name
    atpm = next(o for o in opts if o["value"] == "ATPM")
    assert atpm["label"].startswith("ATPM")
    json.dumps(opts)


def test_current_objective(service, session):
    obj = controllers.current_objective(service, session)
    assert "Biomass" in obj["objective"]
    assert obj["direction"] == "max"


# -- strain-design validation helpers -------------------------------------- #

def test_validate_constraint(service, session):
    ids = set(service.reaction_ids(session))
    assert controllers.validate_constraint(ids, "Biomass_Ecoli_core >= 0.1")["ok"]
    bad = controllers.validate_constraint(ids, "NOPE_rxn >= 1")
    assert not bad["ok"] and "unknown" in bad["error"]
    ex = controllers.validate_constraint(ids, "EX_glc__D_e <= -1")
    assert ex["ok"] and any("uptake is negative" in w for w in ex["warnings"])
    assert not controllers.validate_constraint(ids, "Biomass_Ecoli_core 0.1")["ok"]


def test_suppress_needs_aux():
    assert controllers.suppress_needs_aux(["EX_etoh_e <= 0"]) is True      # zero allowed
    assert controllers.suppress_needs_aux(["EX_glc__D_e <= -0.1"]) is False  # excludes 0
    assert controllers.suppress_needs_aux(["Biomass_Ecoli_core >= 0.05"]) is False


def test_resolve_preset_controller(service, session):
    resolved = controllers.resolve_preset(service, session, "wgcp",
                                          "EX_etoh_e", "EX_glc__D_e", 0.2)
    blob = " ".join(c for m in resolved["modules"] for c in m["constraints"])
    assert "Biomass_Ecoli_core" in blob and "{" not in blob


def test_parse_ki_controller(service, session):
    out = controllers.parse_ki(service, session, "PFK: a_c --> b_c\nNEW: x_c <=> y_c")
    ids = [r["id"] for r in out["reactions"]]
    assert ids == ["PFK", "NEW"]
    assert any("duplicate" in e for e in out["errors"])     # PFK exists


def test_run_pfba_includes_efm(service, session):
    out = controllers.run_pfba(service, session)
    assert "efm" in out and "is_efm" in out["efm"]
    assert out["efm"]["nullity"] == out["efm"]["n_active"] - out["efm"]["rank"]


def test_fba_table_and_export_bundle(service, session):
    import io
    import zipfile

    tab = controllers.fba_table(service, session, "fba")
    assert len(tab["rows"]) == 95
    assert set(tab["rows"][0]) == {"reaction_id", "reaction_name", "subsystem",
                                   "flux", "lower_bound", "upper_bound"}
    fname, data = controllers.analysis_export(service, session, "fba")
    assert fname.endswith(".zip")
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert any(n.endswith(".csv") for n in names)
    assert any(n.endswith("_manifest.json") for n in names)
    csv = zf.read(next(n for n in names if n.endswith(".csv"))).decode()
    assert csv.splitlines()[0] == \
        "reaction_id,reaction_name,subsystem,flux,lower_bound,upper_bound"


def test_fva_table_and_export(service, session, backend, tmp_path):
    import io
    import zipfile

    job_id = controllers.submit_fva(service, backend, session,
                                    reaction_list=["PFK", "PGI"],
                                    export_dir=str(tmp_path))
    deadline = time.time() + 120
    while time.time() < deadline:
        if controllers.job_status(backend, job_id)["done"]:
            break
        time.sleep(0.05)
    tab = controllers.fva_table(service, backend, job_id, session)
    assert set(tab["rows"][0]) == {"reaction_id", "reaction_name", "min_flux",
                                   "max_flux", "span", "fraction_of_optimum"}
    fname, data = controllers.fva_export(service, backend, job_id, session)
    assert fname.endswith(".zip")
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert any(n.endswith(".csv") for n in names)
    assert any(n.endswith("_manifest.json") for n in names)


def test_set_objective_changes_fba(service, session):
    out = controllers.set_objective(service, session, "ATPM")
    assert "ATPM" in out["objective"]
    # the next FBA now optimises ATPM (far larger than the biomass objective)
    res = controllers.run_fba(service, session)
    assert res["status"] == "optimal"
    assert res["objective_value"] > 1.0


def test_set_objective_linear_combination(service, session):
    out = controllers.set_objective(service, session, "PFK, PGI:0.5")
    assert "PFK" in out["objective"] and "PGI" in out["objective"]


def test_set_objective_direction_toggle(service, session):
    out = controllers.set_objective(service, session, "ATPM", direction="min")
    assert out["direction"] == "min"
    res = controllers.run_fba(service, session)
    lb = service.get_reaction(session, "ATPM")["lower_bound"]
    assert math.isclose(res["objective_value"], lb, rel_tol=1e-4)


def test_set_objective_unknown_raises(service, session):
    with pytest.raises(KeyError):
        controllers.set_objective(service, session, "NOT_A_RXN")


# -- FVA job through the controllers --------------------------------------- #

def test_fva_submit_poll_result(service, session, backend, tmp_path):
    job_id = controllers.submit_fva(
        service, backend, session,
        reaction_list=["PFK", "PGI"], fraction_of_optimum=1.0,
        export_dir=str(tmp_path),
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        st = controllers.fva_status(backend, job_id)
        if st["done"]:
            break
        time.sleep(0.05)
    assert st["succeeded"]
    rows = controllers.fva_result_rows(backend, job_id)
    assert {r["reaction"] for r in rows} == {"PFK", "PGI"}
    for r in rows:
        assert r["minimum"] <= r["maximum"]
    json.dumps(rows)


def test_fva_spans_filters_zero_span(service, session, backend, tmp_path):
    # fraction < 1 leaves genuine variability, so several spans are non-zero
    job_id = controllers.submit_fva(
        service, backend, session,
        reaction_list=["PFK", "PGI", "PGK", "ENO"], fraction_of_optimum=0.9,
        export_dir=str(tmp_path),
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if controllers.fva_status(backend, job_id)["done"]:
            break
        time.sleep(0.05)
    spans = controllers.fva_spans(backend, job_id)
    assert spans                                            # at least one varies
    for r in spans:
        assert r["span"] > 0
        assert r["span"] == r["maximum"] - r["minimum"]
    # sorted widest-first
    widths = [r["span"] for r in spans]
    assert widths == sorted(widths, reverse=True)
    json.dumps(spans)


def test_build_span_figure():
    from gem_suite.app.pages.analysis import build_span_figure

    spans = [
        {"reaction": "PFK", "minimum": 1.0, "maximum": 25.0, "span": 24.0},
        {"reaction": "PGI", "minimum": -14.0, "maximum": 10.0, "span": 24.0},
    ]
    fig = build_span_figure(spans)
    bar = fig.data[0]
    assert list(bar.y) == ["PFK", "PGI"]
    assert list(bar.base) == [1.0, -14.0]
    assert list(bar.x) == [24.0, 24.0]          # widths = spans
    assert bar.orientation == "h"

    empty = build_span_figure([])               # graceful empty case
    assert empty.data == ()
    assert empty.layout.annotations


def test_submit_fva_exports_current_edits(service, session, backend, tmp_path):
    # an edit before submitting must be reflected in the job's model. Block O2
    # (non-essential: the model stays feasible anaerobically) and confirm the
    # exported model's FVA range for O2 collapses to (0, 0).
    controllers.toggle_exchange(service, session, "EX_o2_e", "blocked")
    job_id = controllers.submit_fva(
        service, backend, session,
        reaction_list=["EX_o2_e"], export_dir=str(tmp_path),
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if controllers.fva_status(backend, job_id)["done"]:
            break
        time.sleep(0.05)
    rows = controllers.fva_result_rows(backend, job_id)
    o2 = next(r for r in rows if r["reaction"] == "EX_o2_e")
    assert o2["minimum"] == 0.0 and o2["maximum"] == 0.0   # blocked in export


# -- app build -------------------------------------------------------------- #

def test_create_app_builds(service, backend):
    app = create_app(service=service, backend=backend)
    assert app.layout is not None
    # all four pages registered callbacks
    assert len(app.callback_map) >= 6
    rendered = str(app.layout)
    assert "session-store" in rendered and "job-store" in rendered
