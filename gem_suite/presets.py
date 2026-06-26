"""Goal presets for strain design.

A preset is a *data structure* (not hardcoded UI) that populates suppress/protect
module cards with editable inequalities, so users tweak numbers instead of
authoring the double-negative from scratch. Templates carry `{prod}` (product
exchange), `{sub}` (substrate exchange), `{Ymin}` (minimum yield) and `{bm}`
(biomass/growth reaction) placeholders, resolved by `resolve_preset`.

Each suppress region excludes the v=0 vector (via a minimum substrate uptake),
which is the StrainDesign manual's standard trick — a suppress region that allows
the zero-flux vector is satisfied trivially and the design is meaningless.
"""
from __future__ import annotations

from dataclasses import dataclass

_GROWTH = "0.05"   # default minimum growth used inside templates


@dataclass
class DesignPreset:
    key: str
    label: str
    description: str          # one line, shown under the dropdown
    approach: str             # "MCS" | "OptKnock" | ...
    objective: str | None     # for bilevel approaches; None for MCS
    modules: list[dict]       # suppress/protect with placeholders
    notes: str                # the "why", shown in an info strip


PRESETS: list[DesignPreset] = [
    DesignPreset(
        key="wgcp",
        label="Growth-coupled production (weak, wGCP)",
        description="Force minimum product yield at growth-maximal flux states.",
        approach="MCS", objective=None,
        modules=[
            {"type": "suppress",
             "constraints": ["{prod} + {Ymin} {sub} <= 0", "{sub} <= -0.1",
                             "{bm} >= " + _GROWTH]},
            {"type": "protect", "constraints": ["{bm} >= " + _GROWTH]},
        ],
        notes=("Eliminate states that grow and take up substrate but stay below the "
               "yield {Ymin} (product + Ymin·substrate ≤ 0, substrate negative). "
               "Protect keeps growth reachable."),
    ),
    DesignPreset(
        key="pgcp",
        label="Growth-coupled production (strong, pGCP)",
        description="Couple product to any nonzero growth (potent coupling).",
        approach="MCS", objective=None,
        modules=[
            {"type": "suppress",
             "constraints": ["{prod} + {Ymin} {sub} <= 0", "{sub} <= -0.1",
                             "{bm} >= 0.01"]},
            {"type": "protect", "constraints": ["{bm} >= " + _GROWTH]},
        ],
        notes="Like wGCP but enforced down to low growth (≥0.01), giving stronger coupling.",
    ),
    DesignPreset(
        key="sucp",
        label="Substrate-uptake coupling (SUCP)",
        description="Enforce a minimum product yield per substrate, regardless of growth.",
        approach="MCS", objective=None,
        modules=[
            {"type": "suppress",
             "constraints": ["{prod} + {Ymin} {sub} <= 0", "{sub} <= -0.1"]},
            {"type": "protect", "constraints": ["{bm} >= " + _GROWTH]},
        ],
        notes="Yield is tied to substrate uptake; production cannot be avoided while feeding.",
    ),
    DesignPreset(
        key="lethal",
        label="Synthetic lethals (prohibit growth)",
        description="Smallest intervention sets that make growth infeasible.",
        approach="MCS", objective=None,
        modules=[{"type": "suppress", "constraints": ["{bm} >= 0.01"]}],
        notes="Find minimal cut sets lethal to the organism (no protect region).",
    ),
    DesignPreset(
        key="condaux",
        label="Conditional auxotrophy (substrate-dependent)",
        description="Make growth depend on the chosen substrate being available.",
        approach="MCS", objective=None,
        modules=[
            {"type": "suppress", "constraints": ["{bm} >= 0.01", "{sub} >= -0.001"]},
            {"type": "protect", "constraints": ["{bm} >= " + _GROWTH]},
        ],
        notes=("Forbid growth when substrate uptake is ~0; protect growth when it is "
               "available — the strain becomes auxotrophic for the substrate."),
    ),
]

_BY_KEY = {p.key: p for p in PRESETS}


def get_preset(key: str) -> DesignPreset:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise ValueError(f"unknown preset {key!r}") from None


def resolve_preset(key: str, *, sub: str, prod: str, ymin: float,
                   growth: str) -> dict:
    """Resolve a preset's placeholders into a concrete module list (Store shape)."""
    preset = get_preset(key)
    repl = {"{sub}": sub, "{prod}": prod, "{Ymin}": str(ymin), "{bm}": growth}

    def fill(s: str) -> str:
        for token, value in repl.items():
            s = s.replace(token, value)
        return s

    modules = [
        {"type": m["type"], "constraints": [fill(c) for c in m["constraints"]]}
        for m in preset.modules
    ]
    return {
        "approach": preset.approach,
        "objective": fill(preset.objective) if preset.objective else None,
        "modules": modules,
    }
