"""Bundled example data shipped with the package."""
from __future__ import annotations

from importlib import resources


def example_model_path() -> str:
    """Filesystem path to the bundled e_coli_core example model."""
    return str(resources.files("gem_suite.data") / "e_coli_core.xml.gz")
