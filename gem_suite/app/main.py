"""Dash app entry point.

Builds a single-page app with tabs over the panels (load, reactions, exchanges,
analysis, scan), sharing a `session-store` (the only model handle the browser
holds) and a `job-store`. The app drives a LIVE ModelService and a
LocalProcessBackend in-process — see gem_suite/app/services.py.

Strain design is deliberately NOT exposed in the local UI: the MILPs are far too
slow to run interactively without a cluster. The code is intact and still driven
from Python / the job layer (see gem_suite/strain_design.py and
gem_suite/app/pages/strain_design.py), ready for the SLURM backend. To re-enable
the tab, add `strain_design` back to the imports, `_PAGES` and the tab list below.

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
)

# Brand assets (logos + theme.css) ship inside the package at gem_suite/app/assets,
# which is Dash's default assets folder for Dash(__name__) — so they are found
# both from a source checkout and from an installed wheel/pipx.

# Custom index so the favicon is the SVG logo (Dash only auto-wires favicon.ico).
_INDEX = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        <link rel="icon" type="image/svg+xml" href="/assets/littlegem_favicon.svg">
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>{%config%}{%scripts%}{%renderer%}</footer>
    </body>
</html>"""


def create_app(service=None, backend=None) -> Dash:
    """Create the Dash app wired to `service`/`backend` (defaults: the singletons)."""
    if service is None or backend is None:
        from gem_suite.app.services import BACKEND, SERVICE
        service = service or SERVICE
        backend = backend or BACKEND

    app = Dash(__name__, suppress_callback_exceptions=True, title="GEM Suite")
    app.index_string = _INDEX

    tab_style = {"fontWeight": 400}
    tab_selected = {"fontWeight": 700, "color": "#047857",
                    "borderTop": "2px solid #10B981"}

    def _tab(label, value, page):
        return dcc.Tab(label=label, value=value, style=tab_style,
                       selected_style=tab_selected,
                       children=html.Div(page.layout(), className="card"))

    app.layout = html.Div(
        [
            # The browser's entire model handle: a session_id string.
            dcc.Store(id="session-store"),
            html.Header(
                html.Img(src=app.get_asset_url("littlegem_wordmark.svg"),
                         alt="GEM Suite", style={"height": "56px"}),
                className="gs-header",
            ),
            dcc.Tabs(
                id="tabs",
                value="tab-load",
                children=[
                    _tab("Load", "tab-load", load),
                    _tab("Reactions", "tab-reactions", reactions),
                    _tab("Exchanges", "tab-exchanges", exchanges),
                    _tab("Analysis", "tab-analysis", analysis),
                    _tab("Scan", "tab-scan", scan),
                ],
            ),
        ],
        style={"maxWidth": "1200px", "margin": "0 auto", "fontFamily": "sans-serif",
               "padding": "0 1rem 2rem"},
    )

    # Strain design is intentionally absent (see module docstring).
    for page in (load, reactions, exchanges, analysis, scan):
        page.register_callbacks(app, service, backend)

    return app


def main() -> None:
    create_app().run(debug=True)


if __name__ == "__main__":
    main()
