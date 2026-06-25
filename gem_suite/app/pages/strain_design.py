"""Strain design page: submit a strain-design job and render the solution sets.

MCS enumeration is NP-hard and explodes with cut-set size, so max_size and
max_solutions are exposed and defaulted conservatively (SPEC).
"""
from __future__ import annotations

import re

from dash import Input, Output, State, html, dcc, no_update
import dash_ag_grid as dag

from gem_suite.app import controllers

_APPROACHES = ["MCS", "OptKnock", "RobustKnock", "OptCouple"]
_SD_COLS = [
    {"field": "#", "width": 70},
    {"field": "level", "width": 110},
    {"field": "cost", "width": 90},
    {"field": "knockouts", "headerName": "Knock-outs", "flex": 1, "minWidth": 240},
    {"field": "knockins", "headerName": "Knock-ins", "flex": 1, "minWidth": 180},
]


def _parse_ids(text: str | None) -> list[str] | None:
    if not text or not text.strip():
        return None
    return [t for t in re.split(r"[,\s]+", text.strip()) if t]


def layout() -> html.Div:
    return html.Div(
        [
            dcc.Store(id="sd-job-store"),
            dcc.Interval(id="sd-interval", interval=600, disabled=True),
            html.H3("Strain design"),
            html.Div(
                [
                    dcc.Input(id="sd-target", type="text", value="EX_etoh_e",
                              placeholder="target reaction id", style={"width": "14rem"}),
                    dcc.Dropdown(id="sd-approach", options=_APPROACHES, value="MCS",
                                 clearable=False, style={"width": "11rem"}),
                    dcc.Checklist(id="sd-gene-level",
                                  options=[{"label": " gene-level", "value": "gene"}],
                                  value=["gene"]),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center",
                       "flexWrap": "wrap"},
            ),
            html.Div(
                [
                    html.Label("max size"),
                    dcc.Input(id="sd-max-size", type="number", value=3, min=1, step=1,
                              style={"width": "6rem"}),
                    html.Label("max solutions"),
                    dcc.Input(id="sd-max-sol", type="number", value=3, min=1, step=1,
                              style={"width": "6rem"}),
                    html.Label("min growth"),
                    dcc.Input(id="sd-min-growth", type="number", value=0.05, step=0.01,
                              style={"width": "6rem"}),
                    html.Label("min yield"),
                    dcc.Input(id="sd-min-yield", type="number", value=0.0, step=0.1,
                              style={"width": "6rem"}),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center",
                       "marginTop": "0.5rem", "flexWrap": "wrap"},
            ),
            html.Div(
                [
                    dcc.Input(id="sd-ko-cands", type="text", value="",
                              placeholder="KO candidates (blank = all)",
                              style={"width": "22rem"}),
                    html.Button("Submit strain design", id="sd-submit", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "marginTop": "0.5rem"},
            ),
            html.Div(id="sd-status", style={"marginTop": "0.5rem"}),
            dag.AgGrid(id="sd-grid", columnDefs=_SD_COLS, rowData=[],
                       defaultColDef={"sortable": True, "resizable": True},
                       style={"height": "45vh"}),
        ]
    )


def register_callbacks(app, service, backend) -> None:
    @app.callback(
        Output("sd-job-store", "data"),
        Output("sd-interval", "disabled"),
        Output("sd-status", "children"),
        Input("sd-submit", "n_clicks"),
        State("session-store", "data"),
        State("sd-target", "value"),
        State("sd-approach", "value"),
        State("sd-gene-level", "value"),
        State("sd-max-size", "value"),
        State("sd-max-sol", "value"),
        State("sd-min-growth", "value"),
        State("sd-min-yield", "value"),
        State("sd-ko-cands", "value"),
        prevent_initial_call=True,
    )
    def _submit(_n, session_id, target, approach, gene_level, max_size, max_sol,
                min_growth, min_yield, ko_cands):
        if not session_id:
            return no_update, True, "Load a model first."
        if not target:
            return no_update, True, "Provide a target reaction."
        try:
            job_id = controllers.submit_strain_design(
                service, backend, session_id,
                target_reaction=target,
                approach=approach,
                gene_level=bool(gene_level),
                max_size=int(max_size) if max_size else None,
                max_solutions=int(max_sol) if max_sol else 1,
                min_growth=float(min_growth) if min_growth not in (None, "") else None,
                min_yield=float(min_yield) if min_yield not in (None, "") else None,
                ko_candidates=_parse_ids(ko_cands),
            )
        except Exception as exc:
            return no_update, True, f"Submit failed: {type(exc).__name__}: {exc}"
        return job_id, False, f"Strain design submitted: {job_id[:8]}…"

    @app.callback(
        Output("sd-status", "children", allow_duplicate=True),
        Output("sd-interval", "disabled", allow_duplicate=True),
        Output("sd-grid", "rowData"),
        Input("sd-interval", "n_intervals"),
        State("sd-job-store", "data"),
        prevent_initial_call=True,
    )
    def _poll(_tick, job_id):
        if not job_id:
            return no_update, True, no_update
        st = controllers.job_status(backend, job_id)
        if not st["done"]:
            return f"Strain design {st['state']}…", False, no_update
        if st["succeeded"]:
            rows = controllers.strain_design_solution_rows(backend, job_id)
            return f"Done: {len(rows)} design(s).", True, rows
        return f"{st['state']}: {st['error']}", True, []
