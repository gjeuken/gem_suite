"""Exchanges page: classify boundary reactions and toggle uptake/secretion."""
from __future__ import annotations

from dash import Input, Output, State, html, dcc, no_update
import dash_ag_grid as dag

from gem_suite import ExchangeDirection
from gem_suite.app import controllers

_COLUMN_DEFS = [
    {"field": "reaction_id", "headerName": "Exchange", "filter": True, "width": 160},
    {"field": "metabolite_id", "headerName": "Metabolite", "filter": True, "width": 150},
    {"field": "name", "headerName": "Name", "flex": 1, "minWidth": 200},
    {"field": "kind", "headerName": "Kind", "width": 110},
    {"field": "lower_bound", "headerName": "LB", "width": 110},
    {"field": "upper_bound", "headerName": "UB", "width": 110},
    {"field": "direction", "headerName": "Capability", "width": 130},
]

_DIRECTIONS = [d.value for d in ExchangeDirection]


def layout() -> html.Div:
    return html.Div(
        [
            html.H3("Exchanges"),
            html.Div(
                [
                    html.Span("Selected exchange + direction → Apply:"),
                    dcc.Dropdown(id="exch-direction", options=_DIRECTIONS,
                                 value="both", clearable=False,
                                 style={"width": "12rem"}),
                    html.Button("Apply toggle", id="exch-apply", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center"},
            ),
            dag.AgGrid(
                id="exchanges-grid",
                columnDefs=_COLUMN_DEFS,
                rowData=[],
                defaultColDef={"sortable": True, "resizable": True},
                dashGridOptions={"rowSelection": "single"},
                style={"height": "55vh", "marginTop": "0.5rem"},
            ),
            html.Div(id="exchanges-msg", style={"marginTop": "0.5rem"}),
        ]
    )


def register_callbacks(app, service, backend) -> None:
    @app.callback(
        Output("exchanges-grid", "rowData"),
        Input("session-store", "data"),
        Input("exchanges-msg", "children"),   # refresh after a toggle
        prevent_initial_call=True,
    )
    def _populate(session_id, _msg):
        if not session_id:
            return []
        try:
            return controllers.exchange_rows(service, session_id)
        except Exception:
            return []

    @app.callback(
        Output("exchanges-msg", "children"),
        Input("exch-apply", "n_clicks"),
        State("exchanges-grid", "selectedRows"),
        State("exch-direction", "value"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _toggle(n_clicks, selected, direction, session_id):
        if not session_id or not selected:
            return "Select an exchange row first."
        rxn_id = selected[0]["reaction_id"]
        try:
            controllers.toggle_exchange(service, session_id, rxn_id, direction)
        except Exception as exc:
            return f"Toggle failed: {type(exc).__name__}: {exc}"
        return f"{rxn_id} → {direction}"
