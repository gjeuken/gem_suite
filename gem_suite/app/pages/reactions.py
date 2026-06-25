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
                ]
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
