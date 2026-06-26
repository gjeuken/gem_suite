"""Reactions page: editable AG Grid of reactions; edits set bounds server-side."""
from __future__ import annotations

from dash import Input, Output, State, html, dcc, no_update
import dash_ag_grid as dag

from gem_suite.app import controllers

_COLUMN_DEFS = [
    {"field": "id", "headerName": "ID", "filter": True, "pinned": "left", "width": 140},
    {"field": "name", "headerName": "Name", "filter": True, "width": 220},
    {"field": "reaction", "headerName": "Reaction", "flex": 1, "minWidth": 260},
    {"field": "lower_bound", "headerName": "LB", "editable": True,
     "type": "numericColumn", "width": 110},
    {"field": "upper_bound", "headerName": "UB", "editable": True,
     "type": "numericColumn", "width": 110},
    {"field": "subsystem", "headerName": "Subsystem", "filter": True, "width": 160},
    {"field": "gene_reaction_rule", "headerName": "GPR", "width": 160},
]


def layout() -> html.Div:
    return html.Div(
        [
            html.H3("Reactions"),
            html.Div(
                [
                    dcc.Input(id="rxn-filter", type="text", value="",
                              placeholder="filter id/name (regex)",
                              debounce=True, style={"width": "20rem"}),
                    html.Span("edit LB/UB cells to change bounds",
                              style={"opacity": 0.6, "marginLeft": "0.5rem"}),
                    html.Button("Export SBML", id="rxn-export-btn", n_clicks=0,
                                style={"marginLeft": "auto"}),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            dcc.Download(id="rxn-download"),

            # -- add a new reaction -------------------------------------------
            html.Details(
                [
                    html.Summary("➕ Add a reaction"),
                    html.Div(
                        [
                            dcc.Input(id="add-rxn-id", type="text",
                                      placeholder="reaction id", style={"width": "10rem"}),
                            dcc.Input(id="add-rxn-name", type="text",
                                      placeholder="name (optional)",
                                      style={"width": "12rem"}),
                            dcc.Input(id="add-rxn-eqn", type="text",
                                      placeholder="a_c + b_c --> c_c   (or <=>)",
                                      style={"width": "24rem"}),
                        ],
                        style={"display": "flex", "gap": "0.5rem",
                               "marginTop": "0.5rem", "flexWrap": "wrap"},
                    ),
                    html.Div(
                        [
                            html.Label("LB"),
                            dcc.Input(id="add-rxn-lb", type="number", placeholder="auto",
                                      style={"width": "6rem"}),
                            html.Label("UB"),
                            dcc.Input(id="add-rxn-ub", type="number", placeholder="auto",
                                      style={"width": "6rem"}),
                            dcc.Input(id="add-rxn-gpr", type="text",
                                      placeholder="GPR (optional)",
                                      style={"width": "12rem"}),
                            dcc.Checklist(id="add-rxn-create",
                                          options=[{"label": " create missing metabolites",
                                                    "value": "create"}], value=[]),
                            html.Button("Add reaction", id="add-rxn-btn", n_clicks=0),
                        ],
                        style={"display": "flex", "gap": "0.5rem",
                               "alignItems": "center", "marginTop": "0.5rem",
                               "flexWrap": "wrap"},
                    ),
                    html.Div(id="add-rxn-msg", style={"marginTop": "0.25rem"}),
                ],
                style={"margin": "0.5rem 0"},
            ),

            dag.AgGrid(
                id="reactions-grid",
                columnDefs=_COLUMN_DEFS,
                rowData=[],
                defaultColDef={"sortable": True, "resizable": True},
                dashGridOptions={"animateRows": False, "rowSelection": "single"},
                style={"height": "60vh"},
            ),
            html.Div(id="reactions-msg", style={"marginTop": "0.5rem"}),
        ]
    )


def register_callbacks(app, service, backend) -> None:
    @app.callback(
        Output("reactions-grid", "rowData"),
        Input("session-store", "data"),
        Input("rxn-filter", "value"),
        prevent_initial_call=True,
    )
    def _populate(session_id, pattern):
        if not session_id:
            return []
        try:
            return controllers.reaction_rows(service, session_id, pattern)
        except Exception:
            return []

    @app.callback(
        Output("add-rxn-msg", "children"),
        Output("reactions-grid", "rowData", allow_duplicate=True),
        Input("add-rxn-btn", "n_clicks"),
        State("add-rxn-id", "value"),
        State("add-rxn-name", "value"),
        State("add-rxn-eqn", "value"),
        State("add-rxn-lb", "value"),
        State("add-rxn-ub", "value"),
        State("add-rxn-gpr", "value"),
        State("add-rxn-create", "value"),
        State("rxn-filter", "value"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _add(_n, rxn_id, name, eqn, lb, ub, gpr, create, pattern, session_id):
        if not session_id:
            return "Load a model first.", no_update
        if not eqn or not eqn.strip():
            return "Enter a reaction equation.", no_update
        try:
            rec = controllers.add_reaction(
                service, session_id, rxn_id, name, eqn, lower=lb, upper=ub,
                gpr=gpr, create_missing=bool(create))
        except Exception as exc:
            return f"Add failed: {type(exc).__name__}: {exc}", no_update
        rows = controllers.reaction_rows(service, session_id, pattern)
        return f"Added {rec['after']['id']}: {rec['after']['reaction']}", rows

    @app.callback(
        Output("rxn-download", "data"),
        Input("rxn-export-btn", "n_clicks"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _export(_n, session_id):
        if not session_id:
            return no_update
        fname, data = controllers.export_sbml(service, session_id)
        return dcc.send_bytes(data, fname)

    @app.callback(
        Output("reactions-msg", "children"),
        Input("reactions-grid", "cellValueChanged"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _edit(changed, session_id):
        if not changed or not session_id:
            return no_update
        # dash-ag-grid sends a list of change events (use the latest)
        event = changed[-1] if isinstance(changed, list) else changed
        row = event["data"]
        try:
            controllers.set_bounds(service, session_id, row["id"],
                                   row.get("lower_bound"), row.get("upper_bound"))
        except Exception as exc:
            return f"Edit rejected: {type(exc).__name__}: {exc}"
        return f"{row['id']} bounds → ({row['lower_bound']}, {row['upper_bound']})"
