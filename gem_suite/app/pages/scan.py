"""Scan page: pin 1–2 fluxes over a grid, then plot anything against anything.

Each scanned reaction is pinned across its [min, max] range in `points` steps and
the model re-optimised (robustness analysis / phenotypic phase plane). The scan
records the objective AND every reaction flux at each grid point (kept
server-side), so you can add as many plots as you like and choose, per plot, what
goes on X and Y — the objective, a scanned flux, an exchange flux, an
intracellular flux, or any flux at all.
"""
from __future__ import annotations

import math

from dash import (
    ALL, MATCH, Input, Output, State, callback_context, dcc, html, no_update,
)
import plotly.graph_objects as go

from gem_suite.app import controllers

_MAX_PLOTS = 8
_CATEGORY_OPTIONS = [{"label": c, "value": c} for c in controllers.SCAN_CATEGORIES]


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #

def _label(key: str) -> str:
    return "objective" if key == "objective" else f"{key} flux"


def build_xy_figure(x_key: str, xs: list, y_key: str, ys: list) -> go.Figure:
    """Y vs X along the scan (both are series over the grid points)."""
    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="lines+markers", connectgaps=False,
        line={"color": "#4c78a8"},
    ))
    fig.update_layout(
        title=f"{_label(y_key)} vs {_label(x_key)}",
        xaxis_title=_label(x_key), yaxis_title=_label(y_key),
        template="plotly_white", height=380,
        margin={"l": 60, "r": 20, "t": 45, "b": 45},
    )
    return fig


def build_surface_figure(axes: list[dict], z_key: str, grid: list) -> go.Figure:
    """For a 2-D scan: the chosen quantity as a surface over both scanned axes."""
    z = [[(v if v is not None else math.nan) for v in row] for row in grid]
    fig = go.Figure(go.Surface(z=z, x=axes[1]["values"], y=axes[0]["values"],
                               colorbar={"title": _label(z_key)}))
    fig.update_layout(
        title=f"{_label(z_key)} surface",
        scene={"xaxis_title": f"{axes[1]['reaction_id']} flux",
               "yaxis_title": f"{axes[0]['reaction_id']} flux",
               "zaxis_title": _label(z_key)},
        template="plotly_white", height=480,
        margin={"l": 0, "r": 0, "t": 45, "b": 0},
    )
    return fig


def _empty_figure(msg: str = "Run a scan to plot.") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font={"size": 13})
    fig.update_layout(template="plotly_white", height=380,
                      xaxis={"visible": False}, yaxis={"visible": False})
    return fig


# Kept for the single-response API/tests (controllers.run_scan / scan_objective).
def build_scan_figure(result: dict) -> go.Figure:
    axes = result["axes"]
    values = result["values"]
    response = result.get("response", "objective")
    if len(axes) == 1:
        return build_xy_figure(axes[0]["reaction_id"], axes[0]["values"],
                               response, values)
    return build_surface_figure(axes, response, values)


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #

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


def _plot_card(i: int, meta: dict, catx: str, varx: str, caty: str, vary: str,
               surface: bool) -> html.Div:
    axis_picker = lambda kind, cat, var, label: html.Div(   # noqa: E731
        [
            html.Span(label, style={"width": "1.5rem"}),
            dcc.Dropdown(id={"kind": f"scan-cat{kind}", "i": i},
                         options=_CATEGORY_OPTIONS, value=cat, clearable=False,
                         style={"width": "9rem"}),
            dcc.Dropdown(id={"kind": f"scan-var{kind}", "i": i},
                         options=controllers.scan_axis_options(meta, cat),
                         value=var, clearable=False, searchable=True,
                         placeholder="pick a quantity",
                         style={"width": "17rem"}),
        ],
        style={"display": "flex", "gap": "0.4rem", "alignItems": "center"},
    )

    controls = [axis_picker("y", caty, vary, "Y:")]
    if surface:
        controls.append(html.Span("(2-D scan: plotted as a surface over both "
                                  "scanned fluxes — X is taken from the scan)",
                                  style={"opacity": 0.7, "fontSize": "0.8rem"}))
    else:
        controls.append(axis_picker("x", catx, varx, "X:"))

    return html.Div(
        [
            html.Div(f"Plot {i + 1}", style={"fontWeight": "bold"}),
            html.Div(controls, style={"display": "flex", "gap": "1rem",
                                      "flexWrap": "wrap", "margin": "0.25rem 0"}),
            dcc.Graph(id={"kind": "scan-graph", "i": i}, figure=_empty_figure()),
        ],
        style={"border": "1px solid #e0e0e0", "borderRadius": "6px",
               "padding": "0.5rem", "margin": "0.5rem 0"},
    )


def layout() -> html.Div:
    return html.Div(
        [
            dcc.Store(id="scan-meta"),
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
            html.Div(
                [
                    html.Button("Run scan", id="scan-run-btn", n_clicks=0),
                    html.Label("plots"),
                    dcc.Input(id="scan-nplots", type="number", value=1, min=1,
                              max=_MAX_PLOTS, step=1, style={"width": "5rem"}),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center",
                       "marginTop": "0.75rem"},
            ),
            html.Div(id="scan-status", style={"marginTop": "0.5rem"}),
            html.Div(id="scan-plots"),
        ]
    )


# --------------------------------------------------------------------------- #
# Callbacks
# --------------------------------------------------------------------------- #

def register_callbacks(app, service, backend) -> None:
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

    @app.callback(
        Output("scan-axis2-row", "style"),
        Input("scan-2d", "value"),
    )
    def _toggle_axis2(two_d):
        base = {"gap": "0.5rem", "alignItems": "center", "marginTop": "0.5rem"}
        base["display"] = "flex" if two_d else "none"
        return base

    # objective selection (the objective is model-wide)
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

    # run the scan: records every flux server-side, returns metadata only
    @app.callback(
        Output("scan-meta", "data"),
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
            meta = controllers.run_scan_fluxes(service, session_id, axis1, axis2)
        except Exception as exc:
            return no_update, f"Scan failed: {type(exc).__name__}: {exc}"
        return meta, (f"Scanned {meta['n_points']} point(s); recorded the objective "
                      f"and {len(meta['exchanges']) + len(meta['intracellular'])} "
                      f"fluxes. Choose what to plot below.")

    # render N plot cards, preserving existing axis choices
    @app.callback(
        Output("scan-plots", "children"),
        Input("scan-nplots", "value"),
        Input("scan-meta", "data"),
        State({"kind": "scan-catx", "i": ALL}, "value"),
        State({"kind": "scan-varx", "i": ALL}, "value"),
        State({"kind": "scan-caty", "i": ALL}, "value"),
        State({"kind": "scan-vary", "i": ALL}, "value"),
        prevent_initial_call=True,
    )
    def _render(nplots, meta, catx, varx, caty, vary):
        if not meta:
            return html.Div("Run a scan to configure plots.",
                            style={"opacity": 0.7, "marginTop": "0.5rem"})
        n = max(1, min(int(nplots or 1), _MAX_PLOTS))
        surface = meta.get("ndim", 1) == 2
        scanned = meta.get("scanned") or ["objective"]
        cards = []
        for i in range(n):
            cards.append(_plot_card(
                i, meta,
                catx=(catx[i] if i < len(catx or []) and catx[i] else "scanned"),
                varx=(varx[i] if i < len(varx or []) and varx[i] else scanned[0]),
                caty=(caty[i] if i < len(caty or []) and caty[i] else "objective"),
                vary=(vary[i] if i < len(vary or []) and vary[i] else "objective"),
                surface=surface,
            ))
        return cards

    # category -> variable options (per axis, per plot)
    @app.callback(
        Output({"kind": "scan-varx", "i": MATCH}, "options"),
        Input({"kind": "scan-catx", "i": MATCH}, "value"),
        State("scan-meta", "data"),
        prevent_initial_call=True,
    )
    def _optsx(category, meta):
        return controllers.scan_axis_options(meta, category)

    @app.callback(
        Output({"kind": "scan-vary", "i": MATCH}, "options"),
        Input({"kind": "scan-caty", "i": MATCH}, "value"),
        State("scan-meta", "data"),
        prevent_initial_call=True,
    )
    def _optsy(category, meta):
        return controllers.scan_axis_options(meta, category)

    # (re)draw every plot when a selection or the scan changes
    @app.callback(
        Output({"kind": "scan-graph", "i": ALL}, "figure"),
        Input({"kind": "scan-varx", "i": ALL}, "value"),
        Input({"kind": "scan-vary", "i": ALL}, "value"),
        Input("scan-meta", "data"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _draw(varx, vary, meta, session_id):
        n = len(vary or [])
        if not n:
            return []
        if not meta or not session_id:
            return [_empty_figure() for _ in range(n)]
        surface = meta.get("ndim", 1) == 2
        axes = meta["axes"]
        figures = []
        for i in range(n):
            y_key = vary[i]
            x_key = varx[i] if i < len(varx or []) else None
            try:
                if not y_key:
                    figures.append(_empty_figure("Pick a Y quantity."))
                    continue
                ys = controllers.scan_series(service, session_id, y_key)
                if surface:
                    figures.append(build_surface_figure(axes, y_key, ys))
                else:
                    if not x_key:
                        figures.append(_empty_figure("Pick an X quantity."))
                        continue
                    xs = controllers.scan_series(service, session_id, x_key)
                    figures.append(build_xy_figure(x_key, xs, y_key, ys))
            except Exception as exc:
                figures.append(_empty_figure(f"{type(exc).__name__}: {exc}"))
        return figures
