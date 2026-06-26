"""Analysis page: FBA/pFBA inline (synchronous), FVA as a polled job."""
from __future__ import annotations

import re

from dash import (
    ALL, Input, Output, State, callback_context, dcc, html, no_update,
)
import dash_ag_grid as dag
import plotly.graph_objects as go

from gem_suite.app import controllers

_FLUX_COLS = [
    {"field": "reaction", "headerName": "Reaction", "filter": True, "width": 180},
    {"field": "flux", "headerName": "Flux", "type": "numericColumn", "flex": 1},
]
_FVA_COLS = [
    {"field": "reaction", "headerName": "Reaction", "filter": True, "width": 180},
    {"field": "minimum", "headerName": "Min", "type": "numericColumn", "flex": 1},
    {"field": "maximum", "headerName": "Max", "type": "numericColumn", "flex": 1},
]
_BINDING_COLS = [
    {"field": "reaction_id", "headerName": "Reaction", "filter": True, "width": 160},
    {"field": "flux", "type": "numericColumn", "width": 110},
    {"field": "bound", "headerName": "At bound", "width": 100},
    {"field": "bound_value", "headerName": "Bound", "type": "numericColumn",
     "width": 110},
    {"field": "reduced_cost", "headerName": "Reduced cost", "type": "numericColumn",
     "flex": 1},
]


def _parse_reaction_list(text: str | None) -> list[str] | None:
    if not text or not text.strip():
        return None
    return [t for t in re.split(r"[,\s]+", text.strip()) if t]


_UPTAKE_COLOR = "#2ca02c"      # incoming nutrients
_SECRETION_COLOR = "#d62728"   # secreted by-products
_GROWTH_COLOR = "#9467bd"      # biomass / growth (when it is the objective)


def _row_ys(n: int) -> list[float]:
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    top, bottom = 0.9, 0.1
    return [top - (top - bottom) * i / (n - 1) for i in range(n)]


def build_exchange_flux_figure(diagram: dict) -> go.Figure:
    """Schematic cell: uptake arrows enter from the left, secretion exits right.

    Each arrow is labelled with its metabolite and its flux value.
    """
    uptake = diagram.get("uptake", [])
    secretion = diagram.get("secretion", [])
    fig = go.Figure()

    # the cell
    fig.add_shape(type="rect", x0=0.40, x1=0.60, y0=0.05, y1=0.95,
                  line={"color": "#5b8def", "width": 2}, fillcolor="#eaf0fb",
                  layer="below")
    fig.add_annotation(x=0.50, y=0.5, text="cell", showarrow=False,
                       font={"size": 18, "color": "#5b8def"})

    def _arrow(entry, y, tail_x, head_x, color, label_x, label_anchor):
        # flow arrow tail -> head
        fig.add_annotation(x=head_x, y=y, ax=tail_x, ay=y,
                           xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=3, arrowsize=1.3,
                           arrowwidth=2.2, arrowcolor=color, text="")
        # metabolite label at the outer end
        fig.add_annotation(x=label_x, y=y, text=entry["metabolite"],
                           showarrow=False, xanchor=label_anchor,
                           font={"size": 12})
        # flux value above the arrow
        fig.add_annotation(x=(tail_x + head_x) / 2, y=y, yshift=11,
                           text=f"{entry['flux']:.3g}", showarrow=False,
                           font={"size": 12, "color": color})

    for e, y in zip(uptake, _row_ys(len(uptake))):
        _arrow(e, y, tail_x=0.12, head_x=0.40, color=_UPTAKE_COLOR,
               label_x=0.02, label_anchor="left")
    for e, y in zip(secretion, _row_ys(len(secretion))):
        color = _GROWTH_COLOR if e.get("growth") else _SECRETION_COLOR
        _arrow(e, y, tail_x=0.60, head_x=0.88, color=color,
               label_x=0.98, label_anchor="right")

    if not uptake and not secretion:
        fig.add_annotation(x=0.5, y=0.5, yshift=-28, showarrow=False,
                           text="No non-zero exchange fluxes — run FBA/pFBA.",
                           font={"size": 12})

    fig.update_xaxes(visible=False, range=[0, 1])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(
        title="Exchange fluxes (uptake → cell → secretion)",
        template="plotly_white",
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
        height=max(360, 46 * max(len(uptake), len(secretion)) + 120),
    )
    return fig


def build_span_figure(spans: list[dict]) -> go.Figure:
    """Floating horizontal bars: one bar per reaction, from its FVA min to max."""
    if not spans:
        fig = go.Figure()
        fig.add_annotation(text="No reactions with a non-zero span.",
                           showarrow=False, font={"size": 14})
        fig.update_layout(template="plotly_white",
                          xaxis={"visible": False}, yaxis={"visible": False})
        return fig

    reactions = [r["reaction"] for r in spans]
    fig = go.Figure(go.Bar(
        y=reactions,
        x=[r["span"] for r in spans],          # bar width = span
        base=[r["minimum"] for r in spans],    # bar starts at min, ends at max
        orientation="h",
        marker_color="#4c78a8",
        customdata=[[r["minimum"], r["maximum"]] for r in spans],
        hovertemplate=("%{y}<br>min=%{customdata[0]:.4g}"
                       "<br>max=%{customdata[1]:.4g}<extra></extra>"),
    ))
    fig.update_layout(
        title="FVA flux ranges (non-zero span)",
        xaxis_title="flux (mmol gDW⁻¹ h⁻¹)",
        yaxis_title="reaction",
        yaxis={"autorange": "reversed"},       # widest span on top
        template="plotly_white",
        margin={"l": 120, "r": 20, "t": 50, "b": 40},
        height=max(320, 22 * len(reactions) + 120),
        bargap=0.35,
    )
    fig.add_vline(x=0, line_width=1, line_dash="dot", line_color="grey")
    return fig


def layout() -> html.Div:
    return html.Div(
        [
            dcc.Store(id="job-store"),
            dcc.Interval(id="fva-interval", interval=400, disabled=True),
            html.H3("Fast analysis (synchronous)"),
            html.Div(
                [
                    html.Span("Objective:"),
                    dcc.Dropdown(id="objective-input", options=[], value=[],
                                 placeholder="search reaction(s) — pick one or more",
                                 searchable=True, clearable=True, multi=True,
                                 style={"width": "30rem"}),
                    dcc.RadioItems(id="objective-direction",
                                   options=[{"label": " max", "value": "max"},
                                            {"label": " min", "value": "min"}],
                                   value="max", inline=True),
                    html.Button("Set objective", id="set-objective-btn", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center",
                       "flexWrap": "wrap"},
            ),
            # one coefficient field per selected reaction (linear combination)
            html.Div(id="objective-coeffs",
                     style={"display": "flex", "gap": "0.75rem", "flexWrap": "wrap",
                            "marginTop": "0.25rem"}),
            html.Div(id="objective-display",
                     style={"marginTop": "0.25rem", "opacity": 0.85}),
            html.Div(
                [
                    html.Button("Run FBA", id="fba-btn", n_clicks=0),
                    html.Button("Run pFBA", id="pfba-btn", n_clicks=0),
                    dcc.Checklist(id="fast-loopless",
                                  options=[{"label": " loopless", "value": "loopless"}],
                                  value=[]),
                    html.Button("Export CSV", id="fast-export-btn", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "marginTop": "0.5rem",
                       "alignItems": "center"},
            ),
            dcc.Store(id="fast-run"),
            dcc.Download(id="fast-download"),
            html.Div(id="analysis-objective", style={"marginTop": "0.5rem",
                                                     "fontWeight": "bold"}),
            html.Div(id="efm-display", style={"marginTop": "0.25rem", "opacity": 0.85}),
            dag.AgGrid(id="flux-grid", columnDefs=_FLUX_COLS, rowData=[],
                       defaultColDef={"sortable": True, "resizable": True},
                       style={"height": "35vh"}),
            html.Div("Binding constraints (bounds met with equality at the optimum)",
                     style={"fontWeight": "bold", "marginTop": "0.5rem"}),
            dag.AgGrid(id="binding-grid", columnDefs=_BINDING_COLS, rowData=[],
                       defaultColDef={"sortable": True, "resizable": True},
                       style={"height": "25vh"}),
            dcc.Graph(id="exchange-plot",
                      figure=build_exchange_flux_figure({"uptake": [], "secretion": []})),
            html.Hr(),
            html.H3("FVA (job)"),
            html.Div(
                [
                    dcc.Input(id="fva-reactions", type="text", value="",
                              placeholder="reactions (blank = all)",
                              style={"width": "20rem"}),
                    dcc.Input(id="fva-fraction", type="number", value=1.0,
                              min=0, max=1, step=0.05, style={"width": "8rem"}),
                    dcc.Checklist(id="fva-loopless",
                                  options=[{"label": " loopless", "value": "loopless"}],
                                  value=[]),
                    html.Button("Submit FVA", id="fva-submit", n_clicks=0),
                    html.Button("Export CSV", id="fva-export-btn", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center"},
            ),
            dcc.Download(id="fva-download"),
            html.Div(id="fva-status", style={"marginTop": "0.5rem"}),
            dcc.Graph(id="fva-plot", figure=build_span_figure([])),
            dag.AgGrid(id="fva-grid", columnDefs=_FVA_COLS, rowData=[],
                       defaultColDef={"sortable": True, "resizable": True},
                       style={"height": "35vh"}),
        ]
    )


def register_callbacks(app, service, backend) -> None:
    @app.callback(
        Output("objective-input", "options"),
        Input("session-store", "data"),
        prevent_initial_call=True,
    )
    def _objective_options(session_id):
        if not session_id:
            return []
        try:
            return controllers.reaction_options(service, session_id)
        except Exception:
            return []

    # a coefficient field per selected reaction (linear combination); preserve
    # already-entered coefficients when the selection changes
    @app.callback(
        Output("objective-coeffs", "children"),
        Input("objective-input", "value"),
        State({"kind": "obj-coef", "rxn": ALL}, "value"),
        State({"kind": "obj-coef", "rxn": ALL}, "id"),
        prevent_initial_call=True,
    )
    def _coeffs(selected, cur_vals, cur_ids):
        selected = selected or []
        existing = {cid["rxn"]: v for cid, v in zip(cur_ids or [], cur_vals or [])}
        if len(selected) <= 1:
            return ""        # single reaction: coefficient is implicitly 1.0
        return [
            html.Span(
                [html.Span(f"{rid} ×", style={"marginRight": "0.2rem"}),
                 dcc.Input(id={"kind": "obj-coef", "rxn": rid}, type="number",
                           value=existing.get(rid, 1.0), step=0.1,
                           style={"width": "5rem"})],
                style={"display": "inline-flex", "alignItems": "center"})
            for rid in selected
        ]

    @app.callback(
        Output("objective-display", "children"),
        Output("objective-direction", "value"),
        Input("set-objective-btn", "n_clicks"),
        Input("session-store", "data"),
        State("objective-input", "value"),
        State({"kind": "obj-coef", "rxn": ALL}, "value"),
        State({"kind": "obj-coef", "rxn": ALL}, "id"),
        State("objective-direction", "value"),
        prevent_initial_call=True,
    )
    def _objective(_n, session_id, selected, coef_vals, coef_ids, direction):
        if not session_id:
            return "No model loaded.", no_update
        if callback_context.triggered_id == "set-objective-btn":
            selected = selected or []
            if not selected:
                return "Select at least one reaction for the objective.", no_update
            coeffs = {cid["rxn"]: v for cid, v in zip(coef_ids or [], coef_vals or [])}
            terms = {rid: float(coeffs.get(rid, 1.0) or 0.0) for rid in selected}
            try:
                out = controllers.set_objective_combination(
                    service, session_id, terms, direction=direction)
            except Exception as exc:
                return f"Failed: {type(exc).__name__}: {exc}", no_update
        else:  # session changed → show current objective + sync the toggle to it
            out = controllers.current_objective(service, session_id)
        return (f"Current objective: {out['objective']}  ({out['direction']})",
                out["direction"])

    @app.callback(
        Output("analysis-objective", "children"),
        Output("flux-grid", "rowData"),
        Output("binding-grid", "rowData"),
        Output("exchange-plot", "figure"),
        Output("fast-run", "data"),
        Output("efm-display", "children"),
        Input("fba-btn", "n_clicks"),
        Input("pfba-btn", "n_clicks"),
        State("fast-loopless", "value"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _fast(_n_fba, _n_pfba, loopless, session_id):
        empty = build_exchange_flux_figure({"uptake": [], "secretion": []})
        if not session_id:
            return "Load a model first.", [], [], empty, None, ""
        ll = bool(loopless)
        try:
            if callback_context.triggered_id == "pfba-btn":
                out = controllers.run_pfba(service, session_id, loopless=ll)
                kind, label = "pfba", "pFBA"
            else:
                out = controllers.run_fba(service, session_id, loopless=ll)
                kind, label = "fba", "FBA"
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}", [], [], empty, None, ""
        text = (f"{label}{' (loopless)' if ll else ''}: "
                f"objective = {out['objective_value']:.6g}  "
                f"({out['status']}, {out['n_active']} active fluxes, "
                f"{len(out['binding'])} binding)")
        fluxes = {f["reaction"]: f["flux"] for f in out["fluxes"]}
        diagram = controllers.exchange_flux_diagram(service, session_id, fluxes)
        efm_text = ""
        if out.get("efm"):
            e = out["efm"]
            verdict = "is an EFM ✓" if e["is_efm"] else "is not an EFM"
            efm_text = (f"pFBA solution {verdict}  "
                        f"(active {e['n_active']}, rank {e['rank']}, "
                        f"nullity {e['nullity']})")
        return (text, out["fluxes"], out["binding"],
                build_exchange_flux_figure(diagram),
                {"kind": kind, "loopless": ll}, efm_text)

    @app.callback(
        Output("fast-download", "data"),
        Input("fast-export-btn", "n_clicks"),
        State("fast-run", "data"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _export_fast(_n, run, session_id):
        if not session_id or not run:
            return no_update
        fname, data = controllers.analysis_export(
            service, session_id, run["kind"], run.get("loopless", False))
        return dcc.send_bytes(data, fname)

    @app.callback(
        Output("fva-download", "data"),
        Input("fva-export-btn", "n_clicks"),
        State("job-store", "data"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _export_fva(_n, job_id, session_id):
        if not session_id or not job_id:
            return no_update
        try:
            fname, data = controllers.fva_export(service, backend, job_id, session_id)
        except Exception:
            return no_update
        return dcc.send_bytes(data, fname)

    @app.callback(
        Output("job-store", "data"),
        Output("fva-interval", "disabled"),
        Output("fva-status", "children"),
        Input("fva-submit", "n_clicks"),
        State("session-store", "data"),
        State("fva-reactions", "value"),
        State("fva-fraction", "value"),
        State("fva-loopless", "value"),
        prevent_initial_call=True,
    )
    def _submit(_n, session_id, reactions, fraction, loopless):
        if not session_id:
            return no_update, True, "Load a model first."
        try:
            job_id = controllers.submit_fva(
                service, backend, session_id,
                reaction_list=_parse_reaction_list(reactions),
                fraction_of_optimum=float(fraction or 1.0),
                loopless=bool(loopless),
            )
        except Exception as exc:
            return no_update, True, f"Submit failed: {type(exc).__name__}: {exc}"
        return job_id, False, f"FVA submitted: {job_id[:8]}…"

    @app.callback(
        Output("fva-status", "children", allow_duplicate=True),
        Output("fva-interval", "disabled", allow_duplicate=True),
        Output("fva-grid", "rowData"),
        Output("fva-plot", "figure"),
        Input("fva-interval", "n_intervals"),
        State("job-store", "data"),
        prevent_initial_call=True,
    )
    def _poll(_tick, job_id):
        if not job_id:
            return no_update, True, no_update, no_update
        st = controllers.fva_status(backend, job_id)
        if not st["done"]:
            return f"FVA {st['state']}… ({st['progress']:.0%})", False, no_update, no_update
        if st["succeeded"]:
            rows = controllers.fva_result_rows(backend, job_id)
            spans = controllers.fva_spans(backend, job_id)
            msg = (f"FVA done: {len(rows)} reactions, "
                   f"{len(spans)} with non-zero span.")
            return msg, True, rows, build_span_figure(spans)
        return f"FVA {st['state']}: {st['error']}", True, [], build_span_figure([])
