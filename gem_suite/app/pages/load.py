"""Load page: pick a model file (upload or server path), load it, show summary."""
from __future__ import annotations

from dash import Input, Output, State, html, dcc, no_update, callback_context

from gem_suite.app import controllers

_DEFAULT = "tests/data/e_coli_core.xml.gz"


def _summary_text(out: dict) -> str:
    s = out["summary"]
    return (
        f"session: {out['session_id']}\n"
        f"label: {s['label']}    model: {s['model_id']}\n"
        f"reactions: {s['n_reactions']}   metabolites: {s['n_metabolites']}   "
        f"genes: {s['n_genes']}\n"
        f"objective: {s['objective']}  ({s['objective_direction']})\n"
        f"solver: {s['solver']}"
    )


def layout() -> html.Div:
    return html.Div(
        [
            html.H3("Load model"),
            dcc.Input(id="load-label", type="text", value="",
                      placeholder="label (optional)", style={"width": "16rem"}),
            # File picker: native browse dialog + drag-and-drop.
            dcc.Upload(
                id="load-upload",
                children=html.Div(["Drag & drop or ", html.A("browse for a model file"),
                                   " (SBML / JSON / MAT)"]),
                multiple=False,
                style={
                    "width": "100%", "height": "70px", "lineHeight": "70px",
                    "borderWidth": "1px", "borderStyle": "dashed",
                    "borderRadius": "6px", "textAlign": "center",
                    "marginTop": "0.5rem",
                },
            ),
            # Alternative: load a file already on the server (e.g. large GEMs).
            html.Details(
                [
                    html.Summary("…or load a server-side file by path"),
                    html.Div(
                        [
                            dcc.Input(id="load-path", type="text", value=_DEFAULT,
                                      placeholder="path to SBML / JSON / MAT",
                                      style={"width": "32rem"}),
                            html.Button("Load path", id="load-btn", n_clicks=0),
                        ],
                        style={"display": "flex", "gap": "0.5rem", "marginTop": "0.5rem"},
                    ),
                ],
                style={"marginTop": "0.75rem"},
            ),
            html.Pre(id="load-summary", style={"marginTop": "1rem"}),
        ]
    )


def register_callbacks(app, service, backend) -> None:
    @app.callback(
        Output("session-store", "data"),
        Output("load-summary", "children"),
        Input("load-upload", "contents"),
        Input("load-btn", "n_clicks"),
        State("load-upload", "filename"),
        State("load-path", "value"),
        State("load-label", "value"),
        prevent_initial_call=True,
    )
    def _load(contents, _n_clicks, filename, path, label):
        label = label or None
        try:
            if callback_context.triggered_id == "load-upload":
                if not contents:
                    return no_update, no_update
                out = controllers.load_model_from_upload(
                    service, contents, filename, label=label)
            else:
                if not path:
                    return no_update, "Provide a model path."
                out = controllers.load_model(service, path, label=label)
        except Exception as exc:   # surface load errors to the UI
            return no_update, f"Load failed: {type(exc).__name__}: {exc}"
        return out["session_id"], _summary_text(out)
