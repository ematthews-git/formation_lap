"""Validation helpers for the undercut model — consensus ranking + a table dump.

``circuit_stats.diagnose()`` produces the per-circuit decomposition; this module scores
it against a curated consensus of how strong each circuit's undercut is generally held
to be, and renders a readable table. Used by the ``circuit-stats diagnose`` CLI command.
No DB or network here — pure ranking math (no scipy dependency).
"""

from __future__ import annotations

import math

# Curated consensus undercut strength, 0 (overcut / weak) .. 1 (undercut is king).
# Reflects paddock/commentary consensus and historical strategy: high-deg, hard-to-
# follow circuits reward the undercut; cold, low-deg, easy-passing circuits don't.
CONSENSUS_UNDERCUT: dict[str, float] = {
    "hungaroring": 0.95,
    "barcelona": 0.85,
    "singapore": 0.85,
    "zandvoort": 0.82,
    "monaco": 0.80,
    "suzuka": 0.65,
    "silverstone": 0.60,
    "shanghai": 0.55,
    "melbourne": 0.52,
    "miami": 0.50,
    "austin": 0.50,
    "madrid": 0.50,
    "lusail": 0.50,
    "mexico_city": 0.48,
    "sao_paulo": 0.48,
    "abu_dhabi": 0.45,
    "montreal": 0.45,
    "red_bull_ring": 0.40,
    "spa": 0.35,
    "baku": 0.30,
    "las_vegas": 0.25,
    "monza": 0.20,
}


def _ranks(values: list[float]) -> list[float]:
    """Average (tie-aware) ranks of ``values``, smallest value -> rank 1."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-based average rank across the tie group
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(computed: dict[str, float], reference: dict[str, float]) -> float | None:
    """Spearman rank correlation over circuits present in both maps; None if < 3."""
    keys = [k for k in computed if k in reference]
    if len(keys) < 3:
        return None
    rc = _ranks([computed[k] for k in keys])
    rr = _ranks([reference[k] for k in keys])
    n = len(keys)
    mc, mr = sum(rc) / n, sum(rr) / n
    cov = sum((a - mc) * (b - mr) for a, b in zip(rc, rr))
    vc = sum((a - mc) ** 2 for a in rc) ** 0.5
    vr = sum((b - mr) ** 2 for b in rr) ** 0.5
    if vc == 0 or vr == 0:
        return None
    return cov / (vc * vr)


# (title, row key, column width, format kind): "s" string, "d" int, "f<p>" float prec p.
# Model-driven columns first, then the empirical pair-miner cross-check (emp_swing / n /
# swap), which is diagnostic only — it does not feed undercut_strength.
_COLUMNS = [
    ("circuit", "circuit_id", 13, "s"),
    ("undercut", "undercut_strength", 8, "f2"),
    ("overcut", "overcut_strength", 7, "f2"),
    ("swing", "undercut_laptime_swing", 6, "f2"),
    ("deg", "tyre_deg_rate", 6, "f3"),
    ("warmup", "warmup_penalty", 6, "f2"),
    ("age", "typical_stop_age", 4, "f0"),
    ("overtk", "overtaking_difficulty", 6, "f2"),
    ("emp_sw", "emp_swing", 6, "f2"),
    ("n", "undercut_sample_size", 4, "d"),
    ("swap", "swap_rate", 5, "f2"),
]
# A circuit with real degradation but a zero undercut (i.e. classed as overcut) is a red
# flag the model is wrong, so the validation gate calls it out.
_HIGH_DEG = 0.04


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _cell(value, width: int, kind: str, align: str) -> str:
    if kind == "s":
        return f"{str(value):{align}{width}}"
    if _missing(value):
        return f"{'-':{align}{width}}"
    if kind == "d":
        return f"{int(value):{align}{width}d}"
    return f"{value:{align}{width}.{int(kind[1])}f}"  # f0 / f2 / f3


def validation_report(rows: list[dict]) -> list[str]:
    """Cheap correctness gate — flags the failure modes that broke earlier versions."""
    bad_deg = [r["circuit_id"] for r in rows if not (r["tyre_deg_rate"] > 0)]
    high_deg_overcut = [
        r["circuit_id"]
        for r in rows
        if r["tyre_deg_rate"] >= _HIGH_DEG and r["undercut_strength"] <= 0
    ]
    lines = []
    lines.append(
        "deg gate: all circuits deg>0 ✓"
        if not bad_deg
        else f"deg gate FAIL (deg<=0): {', '.join(bad_deg)}"
    )
    lines.append(
        "overcut gate: no high-deg circuit classed overcut ✓"
        if not high_deg_overcut
        else f"overcut gate FAIL (high-deg but overcut): {', '.join(high_deg_overcut)}"
    )
    return lines


def format_table(rows: list[dict]) -> str:
    """Render the decomposition rows as a table, sorted by undercut_strength desc."""
    rows = sorted(rows, key=lambda r: r["undercut_strength"], reverse=True)

    def align(key: str) -> str:
        return "<" if key == "circuit_id" else ">"

    header = " ".join(
        _cell(title, width, "s", align(key)) for title, key, width, _ in _COLUMNS
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            " ".join(_cell(r[key], width, kind, align(key)) for _, key, width, kind in _COLUMNS)
        )

    rho = spearman(
        {r["circuit_id"]: r["undercut_strength"] for r in rows}, CONSENSUS_UNDERCUT
    )
    lines.append("")
    lines.extend(validation_report(rows))
    lines.append(
        f"Spearman(undercut_strength, consensus) = {rho:.3f}"
        if rho is not None
        else "Spearman: n/a (too few circuits)"
    )
    return "\n".join(lines)
