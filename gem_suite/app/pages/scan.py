"""Scan page: objective value as a function of one or two scanned fluxes.

Pick 1 reaction → a 2-D line plot of objective vs that flux; pick 2 → a 3-D
surface. The objective (and its sense) can be selected here too. Each scanned
reaction is pinned across its [min, max] range in `points` steps and the model
re-optimised (robustness analysis / phenotypic phase plane).
"""
from __future__ import annotations

import math

from dash import Input, Output, State, html, dcc, no_update, callback_context
import plotly.graph_objects as go

from gem_suite.app import controllers


def build_scan_figure(result: dict) -> go.Figure:
    axes = result["axes"]
    values = result["values"]
    obj = result["objective"]

    if len(axes) == 1:
        fig = go.Figure(go.Scatter(
            x=axes[0]["values"], y=values, mode="lines+markers",
            connectgaps=False, line={"color": "#4c78a8"},
        ))
        fig.update_layout(
            title=f"Objective vs {axes[0]['reaction_id']}",
            xaxis_title=f"{axes[0]['reaction_id']} flux",
            yaxis_title="objective",
            template="plotly_white", height=480,
        )
        return fig

    # two axes -> surface. None (infeasible) -> NaN so Plotly leaves a gap.
    z = [[(v if v is not None else math.nan) for v in row] for row in values]
    fig = go.Figure(go.Surface(
        z=z, x=axes[1]["values"], y=axes[0]["values"],
        colorbar={"title": "objective"},
    ))
    fig.update_layout(
        title="Objective surface",
        scene={"xaxis_title": f"{axes[1]['reaction_id']} flux",
               "yaxis_title": f"{axes[0]['reaction_id']} flux",
               "zaxis_title": "objective"},
        template="plotly_white", height=620,
        margin={"l": 0, "r": 0, "t": 50, "b": 0},
    )
    return fig


def _axis_controls(idx: int, *, hidden: bool = False) -> html.Div:
    return html.Div(
        [
            html.Span(f"Flux {idx}:"),
            dcc.Dropdown(id=f"scan-rxn{idx}", options=[], value=None,
                         placeholder="search a reaction…", searchable=True,
                         style={"width": "18rem"}),
            html.Label("min"),
            dcc.Input(id=f"scan-min{idx}", type="number", value=-10,
                      style={"width": "6rem"}),
            html.Label("max"),
            dcc.Input(id=f"scan-max{idx}", type="number", value=0,
                      style={"width": "6rem"}),
            html.Label("points"),
            dcc.Input(id=f"scan-points{idx}", type="number", value=11, min=1, step=1,
                      style={"width": "5rem"}),
        ],
        id=f"scan-axis{idx}-row",
        style={"display": "none" if hidden else "flex", "gap": "0.5rem",
               "alignItems": "center", "marginTop": "0.5rem"},
    )


def layout() -> html.Div:
    return html.Div(
        [
            html.H3("Objective scan"),
            html.Div(
                [
                    html.Span("Objective:"),
                    dcc.Dropdown(id="scan-objective-input", options=[], value=None,
                                 placeholder="search a reaction…", searchable=True,
                                 clearable=True, style={"width": "20rem"}),
                    dcc.RadioItems(id="scan-objective-direction",
                                   options=[{"label": " max", "value": "max"},
                                            {"label": " min", "value": "min"}],
                                   value="max", inline=True),
                    html.Button("Set objective", id="scan-set-objective-btn", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center"},
            ),
            html.Div(id="scan-objective-display",
                     style={"marginTop": "0.25rem", "opacity": 0.85}),
            dcc.Checklist(id="scan-2d",
                          options=[{"label": " scan a second flux (3-D surface)",
                                    "value": "2d"}],
                          value=[], style={"marginTop": "0.75rem"}),
            _axis_controls(1),
            _axis_controls(2, hidden=True),
            html.Button("Run scan", id="scan-run-btn", n_clicks=0,
                        style={"marginTop": "0.75rem"}),
            html.Div(id="scan-status", style={"marginTop": "0.5rem"}),
            dcc.Graph(id="scan-plot"),
        ]
    )


def register_callbacks(app, service, backend) -> None:
    # populate reaction dropdowns (objective + both axes) on model load
    @app.callback(
        Output("scan-objective-input", "options"),
        Output("scan-rxn1", "options"),
        Output("scan-rxn2", "options"),
        Input("session-store", "data"),
        prevent_initial_call=True,
    )
    def _options(session_id):
        if not session_id:
            return [], [], []
        opts = controllers.reaction_options(service, session_id)
        return opts, opts, opts

    # show/hide the second-axis row
    @app.callback(
        Output("scan-axis2-row", "style"),
        Input("scan-2d", "value"),
    )
    def _toggle_axis2(two_d):
        base = {"gap": "0.5rem", "alignItems": "center", "marginTop": "0.5rem"}
        base["display"] = "flex" if two_d else "none"
        return base

    # objective selection (mirrors the analysis tab; objective is model-wide)
    @app.callback(
        Output("scan-objective-display", "children"),
        Output("scan-objective-direction", "value"),
        Input("scan-set-objective-btn", "n_clicks"),
        Input("session-store", "data"),
        State("scan-objective-input", "value"),
        State("scan-objective-direction", "value"),
        prevent_initial_call=True,
    )
    def _objective(_n, session_id, expr, direction):
        if not session_id:
            return "No model loaded.", no_update
        if callback_context.triggered_id == "scan-set-objective-btn":
            if not expr:
                return "Pick a reaction to set as the objective.", no_update
            try:
                out = controllers.set_objective(service, session_id, expr,
                                                direction=direction)
            except Exception as exc:
                return f"Failed: {type(exc).__name__}: {exc}", no_update
        else:
            out = controllers.current_objective(service, session_id)
        return (f"Current objective: {out['objective']}  ({out['direction']})",
                out["direction"])

    @app.callback(
        Output("scan-plot", "figure"),
        Output("scan-status", "children"),
        Input("scan-run-btn", "n_clicks"),
        State("session-store", "data"),
        State("scan-2d", "value"),
        State("scan-rxn1", "value"),
        State("scan-min1", "value"), State("scan-max1", "value"),
        State("scan-points1", "value"),
        State("scan-rxn2", "value"),
        State("scan-min2", "value"), State("scan-max2", "value"),
        State("scan-points2", "value"),
        prevent_initial_call=True,
    )
    def _run(_n, session_id, two_d, r1, mn1, mx1, p1, r2, mn2, mx2, p2):
        if not session_id:
            return no_update, "Load a model first."
        if not r1:
            return no_update, "Pick a reaction for flux 1."
        axis1 = {"reaction_id": r1, "min": mn1, "max": mx1, "points": int(p1 or 1)}
        axis2 = None
        if two_d:
            if not r2:
                return no_update, "Pick a reaction for flux 2 (or uncheck the second flux)."
            axis2 = {"reaction_id": r2, "min": mn2, "max": mx2, "points": int(p2 or 1)}
        try:
            result = controllers.run_scan(service, session_id, axis1, axis2)
        except Exception as exc:
            return no_update, f"Scan failed: {type(exc).__name__}: {exc}"
        n = len(result["values"]) * (len(result["values"][0]) if axis2 else 1)
        return build_scan_figure(result), f"Scanned {n} point(s)."
