"""Parse and validate pasted knock-in reactions.

Each line is `RXN_ID: <stoichiometry>` with an arrow `-->` (irreversible) or
`<=>` (reversible), BiGG-style metabolite ids, optional coefficients (default 1):

    BDH: 1.0 a_c + 2.0 b_c --> c_c
    XYZ: x_c <=> y_c

Mechanically StrainDesign treats an addition as an inverse knockout, so a parsed
KI becomes an addable candidate carrying a `ki_cost` (wired in strain_design.py).
"""
from __future__ import annotations

import re

import cobra

_ARROWS = {"-->": False, "->": False, "<=>": True, "<->": True}
_TERM = re.compile(r"^\s*(-?\d*\.?\d+)?\s*([A-Za-z0-9_\[\]]+)\s*$")


def _parse_side(side: str) -> dict[str, float]:
    """'1.0 a_c + b_c' -> {'a_c': 1.0, 'b_c': 1.0}."""
    out: dict[str, float] = {}
    side = side.strip()
    if not side:
        return out
    for term in side.split("+"):
        m = _TERM.match(term)
        if not m:
            raise ValueError(f"bad term {term.strip()!r}")
        coeff, met = m.groups()
        out[met] = out.get(met, 0.0) + (float(coeff) if coeff else 1.0)
    return out


def parse_ki_line(line: str) -> dict:
    """Parse one `RXN_ID: lhs <arrow> rhs` line into a reaction dict. Raises ValueError."""
    if ":" not in line:
        raise ValueError("missing 'RXN_ID:' prefix")
    rxn_id, _, equation = line.partition(":")
    rxn_id = rxn_id.strip()
    if not rxn_id:
        raise ValueError("empty reaction id")

    arrow = next((a for a in ("<=>", "<->", "-->", "->") if a in equation), None)
    if arrow is None:
        raise ValueError("missing arrow ('-->' or '<=>')")
    lhs, _, rhs = equation.partition(arrow)
    reactants = _parse_side(lhs)
    products = _parse_side(rhs)
    if not reactants and not products:
        raise ValueError("no metabolites")

    metabolites: dict[str, float] = {}
    for met, c in reactants.items():
        metabolites[met] = metabolites.get(met, 0.0) - c   # reactants negative
    for met, c in products.items():
        metabolites[met] = metabolites.get(met, 0.0) + c   # products positive
    return {
        "id": rxn_id,
        "metabolites": metabolites,
        "reversible": _ARROWS[arrow],
        "equation": equation.strip(),
    }


def parse_ki_block(text: str) -> tuple[list[dict], list[str]]:
    """Parse a multi-line paste. Returns (reactions, errors). Lines with `#` after
    content are treated as trailing comments; blank/`#`-only lines are skipped."""
    reactions: list[dict] = []
    errors: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            reactions.append(parse_ki_line(line))
        except ValueError as exc:
            errors.append(f"{raw.strip()!r}: {exc}")
    return reactions, errors


def validate_kis(reactions: list[dict], model: cobra.Model) -> dict[str, list[str]]:
    """Orphan-metabolite / duplicate-id / balance checks against `model`."""
    errors: list[str] = []
    warnings: list[str] = []
    model_rxn_ids = {r.id for r in model.reactions}
    model_mets = {m.id for m in model.metabolites}
    seen: set[str] = set()

    for rxn in reactions:
        rid = rxn["id"]
        if rid in model_rxn_ids:
            errors.append(f"{rid}: duplicate of an existing model reaction")
        if rid in seen:
            errors.append(f"{rid}: duplicate id in paste")
        seen.add(rid)

        new_mets = [m for m in rxn["metabolites"] if m not in model_mets]
        if new_mets:
            warnings.append(
                f"{rid}: introduces metabolite(s) not in the model "
                f"({', '.join(new_mets)}) — likely a paste error or a true new species")
        else:
            unbalanced = _charge_mass_imbalance(rxn["metabolites"], model)
            if unbalanced:
                warnings.append(f"{rid}: may be unbalanced ({unbalanced})")
    return {"errors": errors, "warnings": warnings}


def _charge_mass_imbalance(metabolites: dict[str, float], model: cobra.Model) -> str:
    """Best-effort element/charge balance using existing metabolite formulae."""
    elements: dict[str, float] = {}
    charge = 0.0
    for met_id, coeff in metabolites.items():
        met = model.metabolites.get_by_id(met_id)
        if met.charge is not None:
            charge += coeff * met.charge
        for el, n in (met.elements or {}).items():
            elements[el] = elements.get(el, 0.0) + coeff * n
    bad = [f"{el}:{v:+g}" for el, v in elements.items() if abs(v) > 1e-6]
    if abs(charge) > 1e-6:
        bad.append(f"charge:{charge:+g}")
    return ", ".join(bad)


def add_ki_reactions(model: cobra.Model, ki_dicts: list[dict]) -> list[str]:
    """Add parsed KIs to `model` (reusing existing metabolites, creating missing
    ones). Returns the added reaction ids."""
    added: list[str] = []
    for d in ki_dicts:
        if model.reactions.has_id(d["id"]):
            continue
        rxn = cobra.Reaction(d["id"])
        rxn.bounds = (-1000.0, 1000.0) if d.get("reversible") else (0.0, 1000.0)
        model.add_reactions([rxn])
        resolved = {}
        for met_id, coeff in d["metabolites"].items():
            if model.metabolites.has_id(met_id):
                met = model.metabolites.get_by_id(met_id)
            else:
                met = cobra.Metabolite(met_id)
                if "_" in met_id:
                    comp = met_id.rsplit("_", 1)[1]
                    if comp in model.compartments:
                        met.compartment = comp
            resolved[met] = coeff
        rxn.add_metabolites(resolved)
        added.append(d["id"])
    return added
