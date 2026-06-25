"""Dash app entry point.

Builds a single-page app with tabs over the four panels (load, reactions,
exchanges, analysis), sharing a `session-store` (the only model handle the
browser holds) and a `job-store`. The app drives a LIVE ModelService and a
LocalProcessBackend in-process — see gem_suite/app/services.py.

Run:  python -m gem_suite.app.main
"""
from __future__ import annotations

from dash import Dash, dcc, html

from gem_suite.app.pages import (
    analysis,
    exchanges,
    load,
    reactions,
    scan,
    strain_design,
)


def create_app(service=None, backend=None) -> Dash:
    """Create the Dash app wired to `service`/`backend` (defaults: the singletons)."""
    if service is None or backend is None:
        from gem_suite.app.services import BACKEND, SERVICE
        service = service or SERVICE
        backend = backend or BACKEND

    app = Dash(__name__, suppress_callback_exceptions=True,
               title="GEM Suite")

    app.layout = html.Div(
        [
            # The browser's entire model handle: a session_id string.
            dcc.Store(id="session-store"),
            html.H2("GEM Suite"),
            dcc.Tabs(
                id="tabs",
                value="tab-load",
                children=[
                    dcc.Tab(label="Load", value="tab-load", children=load.layout()),
                    dcc.Tab(label="Reactions", value="tab-reactions",
                            children=reactions.layout()),
                    dcc.Tab(label="Exchanges", value="tab-exchanges",
                            children=exchanges.layout()),
                    dcc.Tab(label="Analysis", value="tab-analysis",
                            children=analysis.layout()),
                    dcc.Tab(label="Scan", value="tab-scan",
                            children=scan.layout()),
                    dcc.Tab(label="Strain design", value="tab-strain",
                            children=strain_design.layout()),
                ],
            ),
        ],
        style={"maxWidth": "1200px", "margin": "0 auto", "fontFamily": "sans-serif"},
    )

    for page in (load, reactions, exchanges, analysis, scan, strain_design):
        page.register_callbacks(app, service, backend)

    return app


def main() -> None:
    create_app().run(debug=True)


if __name__ == "__main__":
    main()
