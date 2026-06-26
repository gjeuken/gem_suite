"""Strain design page: dynamic suppress/protect cards, presets, KI paste, and a
submit-and-poll job with post-run verification + EFM.

The `sd-modules` Store holds the module list — that JSON IS the job input (it
serializes straight into StrainDesignParams). Cards are built with Dash
pattern-matching callbacks (ALL/MATCH).
"""
from __future__ import annotations

import re

from dash import ALL, MATCH, Input, Output, State, callback_context, dcc, html, no_update
import dash_ag_grid as dag

from gem_suite.app import controllers

_APPROACHES = ["MCS", "OptKnock", "RobustKnock", "OptCouple"]
_SD_COLS = [
    {"field": "#", "width": 60},
    {"field": "level", "width": 90},
    {"field": "cost", "width": 70},
    {"field": "knockouts", "headerName": "Knock-outs", "flex": 1, "minWidth": 200},
    {"field": "knockins", "headerName": "Knock-ins", "flex": 1, "minWidth": 140},
    {"field": "verification", "headerName": "Verify", "width": 90},
    {"field": "efm", "headerName": "EFM", "width": 90},
]
_VERIF_COLS = [
    {"field": "module", "width": 110},
    {"field": "constraints", "headerName": "Region (constraints)", "flex": 1,
     "minWidth": 280},
    {"field": "result", "width": 90},
    {"field": "objective", "headerName": "obj", "width": 110},
]


def _parse_ids(text: str | None) -> list[str] | None:
    if not text or not text.strip():
        return None
    return [t for t in re.split(r"[,\s]+", text.strip()) if t]


def _modules_from_inputs(stored, ids, values):
    """Overlay live constraint-input text onto the stored module structure."""
    modules = [{"type": m["type"], "constraints": list(m["constraints"])}
               for m in (stored or [])]
    for cid, val in zip(ids or [], values or []):
        i, j = cid["i"], cid["j"]
        if i < len(modules) and j < len(modules[i]["constraints"]):
            modules[i]["constraints"][j] = val or ""
    return modules


def _help(summary_text, body):
    return html.Details([html.Summary(summary_text),
                         html.Div(body, style={"fontSize": "0.85rem",
                                               "opacity": 0.85})],
                        style={"margin": "0.25rem 0"})


def layout() -> html.Div:
    return html.Div(
        [
            dcc.Store(id="sd-modules", data=[]),
            dcc.Store(id="sd-ki-store", data=[]),
            dcc.Store(id="sd-rxn-ids", data=[]),
            dcc.Store(id="sd-job-store"),
            dcc.Interval(id="sd-interval", interval=700, disabled=True),
            html.H3("Strain design"),

            # -- goal presets --------------------------------------------------
            html.Div(
                [
                    html.Span("Goal preset:"),
                    dcc.Dropdown(id="sd-preset", options=controllers.preset_options(),
                                 placeholder="choose a design goal",
                                 style={"width": "20rem"}),
                    dcc.Dropdown(id="sd-prod", options=[], placeholder="product (prod)",
                                 style={"width": "12rem"}),
                    dcc.Dropdown(id="sd-sub", options=[], placeholder="substrate (sub)",
                                 style={"width": "12rem"}),
                    dcc.Input(id="sd-ymin", type="number", value=0.2, step=0.05,
                              style={"width": "6rem"}),
                    html.Button("Apply preset", id="sd-apply-preset", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center",
                       "flexWrap": "wrap"},
            ),
            html.Div(id="sd-preset-note", style={"opacity": 0.8, "fontSize": "0.85rem",
                                                 "margin": "0.25rem 0"}),

            # -- module cards --------------------------------------------------
            html.Div(
                [
                    html.Button("+ suppress", id="sd-add-suppress", n_clicks=0),
                    html.Button("+ protect", id="sd-add-protect", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "marginTop": "0.75rem"},
            ),
            _help("? suppress / protect",
                  ["Suppress = make these flux states impossible (e.g. forbid low "
                   "yield at growth: ", html.Code("EX_prod_e + Ymin EX_sub_e <= 0"),
                   "; also exclude zero flux). Protect = keep states reachable "
                   "(e.g. ", html.Code("BIOMASS >= 0.2"), ")."]),
            html.Div(id="sd-cards"),

            # -- knock-in paste ------------------------------------------------
            html.H4("Knock-in candidates (paste)"),
            dcc.Textarea(id="sd-ki-text", placeholder="RXN_ID: a_c + b_c --> c_c",
                         style={"width": "100%", "height": "5rem"}),
            html.Div(id="sd-ki-feedback", style={"fontSize": "0.85rem"}),

            # -- settings ------------------------------------------------------
            html.Div(
                [
                    dcc.Dropdown(id="sd-approach", options=_APPROACHES, value="MCS",
                                 clearable=False, style={"width": "11rem"}),
                    dcc.Checklist(id="sd-gene-level",
                                  options=[{"label": " gene-level", "value": "gene"}],
                                  value=["gene"]),
                    html.Label("max size"),
                    dcc.Input(id="sd-max-size", type="number", value=5, min=1, step=1,
                              style={"width": "5rem"}),
                    html.Label("max solutions"),
                    dcc.Input(id="sd-max-sol", type="number", value=3, min=1, step=1,
                              style={"width": "5rem"}),
                    html.Label("time limit (s)"),
                    dcc.Input(id="sd-time", type="number", value=300, min=1, step=10,
                              style={"width": "6rem"}),
                    dcc.Input(id="sd-ko-cands", type="text", value="",
                              placeholder="KO candidates (blank = all)",
                              style={"width": "16rem"}),
                ],
                style={"display": "flex", "gap": "0.5rem", "alignItems": "center",
                       "flexWrap": "wrap", "marginTop": "0.5rem"},
            ),
            html.Div(
                [
                    html.Button("Submit strain design", id="sd-submit", n_clicks=0),
                    html.Button("Download manifest", id="sd-manifest-btn", n_clicks=0),
                ],
                style={"display": "flex", "gap": "0.5rem", "marginTop": "0.5rem"},
            ),
            dcc.Download(id="sd-manifest-dl"),
            html.Div(id="sd-status", style={"marginTop": "0.5rem"}),
            dag.AgGrid(id="sd-grid", columnDefs=_SD_COLS, rowData=[],
                       defaultColDef={"sortable": True, "resizable": True},
                       style={"height": "32vh"}),
            html.Div("Verification (solution 1)", style={"fontWeight": "bold",
                                                         "marginTop": "0.5rem"}),
            dag.AgGrid(id="sd-verif-grid", columnDefs=_VERIF_COLS, rowData=[],
                       defaultColDef={"resizable": True}, style={"height": "22vh"}),
        ]
    )


def _card(i, module, rxn_ids):
    kind = module["type"]
    rows = []
    for j, constraint in enumerate(module["constraints"]):
        check = controllers.validate_constraint(set(rxn_ids), constraint)
        msg = check["error"] if not check["ok"] else " · ".join(check["warnings"])
        color = "#c0392b" if not check["ok"] else "#b9770e"
        rows.append(html.Div(
            [
                dcc.Input(id={"kind": "sd-con", "i": i, "j": j}, value=constraint,
                          debounce=True, style={"width": "26rem"},
                          placeholder="e.g. BIOMASS >= 0.2"),
                html.Button("×", id={"kind": "sd-del-row", "i": i, "j": j},
                            n_clicks=0, title="remove constraint"),
                html.Span(msg, id={"kind": "sd-con-msg", "i": i, "j": j},
                          style={"color": color, "fontSize": "0.8rem",
                                 "marginLeft": "0.5rem"}),
            ],
            style={"display": "flex", "gap": "0.4rem", "alignItems": "center",
                   "margin": "0.2rem 0"},
        ))

    warn = ""
    if kind == "suppress" and controllers.suppress_needs_aux(module["constraints"]):
        warn = ("⚠ this suppress region includes the zero-flux vector — add a "
                "minimum-uptake/flux constraint (e.g. EX_sub_e <= -0.1).")

    return html.Div(
        [
            html.Div(
                [html.B(f"{kind.upper()} module {i + 1}"),
                 html.Button("remove module", id={"kind": "sd-del-card", "i": i},
                             n_clicks=0, style={"marginLeft": "0.5rem"})],
            ),
            *rows,
            html.Button("+ add constraint", id={"kind": "sd-add-row", "i": i},
                        n_clicks=0),
            html.Div(warn, style={"color": "#c0392b", "fontSize": "0.8rem"}),
        ],
        style={"border": "1px solid #d0d0d0", "borderRadius": "6px",
               "padding": "0.5rem", "margin": "0.5rem 0",
               "background": "#fafafa"},
    )


def register_callbacks(app, service, backend) -> None:
    # populate product/substrate dropdowns + reaction-id store on model load
    @app.callback(
        Output("sd-prod", "options"),
        Output("sd-sub", "options"),
        Output("sd-rxn-ids", "data"),
        Input("session-store", "data"),
        prevent_initial_call=True,
    )
    def _populate(session_id):
        if not session_id:
            return [], [], []
        opts = controllers.reaction_options(service, session_id)
        return opts, opts, service.reaction_ids(session_id)

    # modules manager: add/remove modules+rows and apply presets
    @app.callback(
        Output("sd-modules", "data"),
        Output("sd-approach", "value"),
        Output("sd-preset-note", "children"),
        Input("sd-add-suppress", "n_clicks"),
        Input("sd-add-protect", "n_clicks"),
        Input("sd-apply-preset", "n_clicks"),
        Input({"kind": "sd-del-card", "i": ALL}, "n_clicks"),
        Input({"kind": "sd-add-row", "i": ALL}, "n_clicks"),
        Input({"kind": "sd-del-row", "i": ALL, "j": ALL}, "n_clicks"),
        State("sd-modules", "data"),
        State({"kind": "sd-con", "i": ALL, "j": ALL}, "value"),
        State({"kind": "sd-con", "i": ALL, "j": ALL}, "id"),
        State("sd-preset", "value"),
        State("sd-prod", "value"),
        State("sd-sub", "value"),
        State("sd-ymin", "value"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _manage(_a, _b, _p, _dc, _ar, _dr, stored, con_vals, con_ids,
                preset, prod, sub, ymin, session_id):
        trig = callback_context.triggered_id
        modules = _modules_from_inputs(stored, con_ids, con_vals)

        if trig == "sd-apply-preset":
            if not (session_id and preset and prod and sub):
                return no_update, no_update, "Pick a preset, product and substrate."
            resolved = controllers.resolve_preset(service, session_id, preset,
                                                   prod, sub, float(ymin or 0.0))
            return resolved["modules"], resolved["approach"], \
                controllers.preset_note(preset)
        if trig == "sd-add-suppress":
            modules.append({"type": "suppress", "constraints": [""]})
        elif trig == "sd-add-protect":
            modules.append({"type": "protect", "constraints": [""]})
        elif isinstance(trig, dict):
            if trig["kind"] == "sd-del-card":
                if trig["i"] < len(modules):
                    del modules[trig["i"]]
            elif trig["kind"] == "sd-add-row":
                modules[trig["i"]]["constraints"].append("")
            elif trig["kind"] == "sd-del-row":
                cons = modules[trig["i"]]["constraints"]
                if trig["j"] < len(cons):
                    del cons[trig["j"]]
        return modules, no_update, no_update

    # render cards from the Store
    @app.callback(
        Output("sd-cards", "children"),
        Input("sd-modules", "data"),
        State("sd-rxn-ids", "data"),
    )
    def _render(modules, rxn_ids):
        return [_card(i, m, rxn_ids or []) for i, m in enumerate(modules or [])]

    # live per-row validation on edit
    @app.callback(
        Output({"kind": "sd-con-msg", "i": MATCH, "j": MATCH}, "children"),
        Output({"kind": "sd-con-msg", "i": MATCH, "j": MATCH}, "style"),
        Input({"kind": "sd-con", "i": MATCH, "j": MATCH}, "value"),
        State("sd-rxn-ids", "data"),
        prevent_initial_call=True,
    )
    def _validate_row(value, rxn_ids):
        check = controllers.validate_constraint(set(rxn_ids or []), value)
        msg = check["error"] if not check["ok"] else " · ".join(check["warnings"])
        color = "#c0392b" if not check["ok"] else "#b9770e"
        return msg, {"color": color, "fontSize": "0.8rem", "marginLeft": "0.5rem"}

    # KI paste parse + validation
    @app.callback(
        Output("sd-ki-store", "data"),
        Output("sd-ki-feedback", "children"),
        Input("sd-ki-text", "value"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _ki(text, session_id):
        if not text or not text.strip() or not session_id:
            return [], ""
        out = controllers.parse_ki(service, session_id, text)
        msgs = [html.Div(f"✓ parsed {len(out['reactions'])} reaction(s)")]
        msgs += [html.Div(f"error: {e}", style={"color": "#c0392b"})
                 for e in out["errors"]]
        msgs += [html.Div(f"warning: {w}", style={"color": "#b9770e"})
                 for w in out["warnings"]]
        return out["reactions"], msgs

    # submit
    @app.callback(
        Output("sd-job-store", "data"),
        Output("sd-interval", "disabled"),
        Output("sd-status", "children"),
        Input("sd-submit", "n_clicks"),
        State("sd-modules", "data"),
        State({"kind": "sd-con", "i": ALL, "j": ALL}, "value"),
        State({"kind": "sd-con", "i": ALL, "j": ALL}, "id"),
        State("sd-approach", "value"),
        State("sd-gene-level", "value"),
        State("sd-max-size", "value"),
        State("sd-max-sol", "value"),
        State("sd-time", "value"),
        State("sd-ko-cands", "value"),
        State("sd-ki-store", "data"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def _submit(_n, stored, con_vals, con_ids, approach, gene_level, max_size,
                max_sol, time_limit, ko_cands, ki_store, session_id):
        if not session_id:
            return no_update, True, "Load a model first."
        modules = _modules_from_inputs(stored, con_ids, con_vals)
        if not modules:
            return no_update, True, "Add at least one suppress/protect module."
        store = {
            "modules": modules,
            "approach": approach,
            "gene_level": bool(gene_level),
            "max_size": int(max_size) if max_size else None,
            "max_solutions": int(max_sol) if max_sol else 1,
            "time_limit_s": int(time_limit) if time_limit else None,
            "ko_candidates": _parse_ids(ko_cands),
            "ki_reactions": ki_store or None,
        }
        try:
            job_id = controllers.submit_strain_design(service, backend, session_id, store)
        except Exception as exc:
            return no_update, True, f"Submit failed: {type(exc).__name__}: {exc}"
        return job_id, False, f"Submitted: {job_id[:8]}…"

    # poll
    @app.callback(
        Output("sd-status", "children", allow_duplicate=True),
        Output("sd-interval", "disabled", allow_duplicate=True),
        Output("sd-grid", "rowData"),
        Output("sd-verif-grid", "rowData"),
        Input("sd-interval", "n_intervals"),
        State("sd-job-store", "data"),
        prevent_initial_call=True,
    )
    def _poll(_tick, job_id):
        if not job_id:
            return no_update, True, no_update, no_update
        st = controllers.job_status(backend, job_id)
        if not st["done"]:
            return f"Strain design {st['state']}…", False, no_update, no_update
        if st["succeeded"]:
            rows = controllers.strain_design_solution_rows(backend, job_id)
            verif = controllers.strain_design_verification_rows(backend, job_id, 0)
            return (f"Done: {len(rows)} design(s).", True, rows, verif)
        return f"{st['state']}: {st['error']}", True, [], []

    # manifest download
    @app.callback(
        Output("sd-manifest-dl", "data"),
        Input("sd-manifest-btn", "n_clicks"),
        State("sd-job-store", "data"),
        prevent_initial_call=True,
    )
    def _manifest(_n, job_id):
        if not job_id:
            return no_update
        out = controllers.strain_design_manifest_download(backend, job_id)
        if out is None:
            return no_update
        fname, data = out
        return dcc.send_bytes(data, fname)
