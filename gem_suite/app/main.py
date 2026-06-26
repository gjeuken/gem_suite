"""Dash app entry point.

Builds a single-page app with tabs over the four panels (load, reactions,
exchanges, analysis), sharing a `session-store` (the only model handle the
browser holds) and a `job-store`. The app drives a LIVE ModelService and a
LocalProcessBackend in-process — see gem_suite/app/services.py.

Run:  python -m gem_suite.app.main
"""
from __future__ import annotations

from pathlib import Path

from dash import Dash, dcc, html

from gem_suite.app.pages import (
    analysis,
    exchanges,
    load,
    reactions,
    scan,
    strain_design,
)

# Brand assets live in the repo's top-level `logos/` folder; serve it as the
# Dash assets folder so the SVGs are available at /assets/<name>.
_LOGOS_DIR = Path(__file__).resolve().parents[2] / "logos"

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

    app = Dash(__name__, suppress_callback_exceptions=True,
               title="GEM Suite", assets_folder=str(_LOGOS_DIR))
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
                    _tab("Strain design", "tab-strain", strain_design),
                ],
            ),
        ],
        style={"maxWidth": "1200px", "margin": "0 auto", "fontFamily": "sans-serif",
               "padding": "0 1rem 2rem"},
    )

    for page in (load, reactions, exchanges, analysis, scan, strain_design):
        page.register_callbacks(app, service, backend)

    return app


def main() -> None:
    create_app().run(debug=True)


if __name__ == "__main__":
    main()
