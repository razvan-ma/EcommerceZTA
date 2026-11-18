"""Compare the latest baseline and Zero-Trust runs of the attack suite.

    python3 tests/security/compare.py [baseline.json zero-trust.json]

Writes results/security/summary.md: the scenario table for the thesis and a
Fisher's exact test of "attack blocked" against variant. The scenario is the
primary unit of analysis: repeated attempts of one scenario are deterministic
and not independent, so the attempt-level test is reported only as a
secondary figure.
"""

from __future__ import annotations

import json
import sys
from math import comb
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[2] / "results" / "security"
VARIANTS = ("baseline", "zero-trust")


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher's exact test p-value for the table [[a, b], [c, d]]."""
    row1, row2, col1, n = a + b, c + d, a + c, a + b + c + d

    def prob(x: int) -> float:
        return comb(row1, x) * comb(row2, col1 - x) / comb(n, col1)

    observed = prob(a)
    support = range(max(0, col1 - row2), min(row1, col1) + 1)
    return min(1.0, sum(p for p in map(prob, support) if p <= observed * (1 + 1e-7)))


def latest(variant: str) -> Path:
    runs = sorted(RESULTS.glob(f"{variant}-*.json"))
    if not runs:
        raise SystemExit(f"no {variant} results in {RESULTS}; run run_attacks.py first")
    return runs[-1]


def cell(scenario: dict | None) -> str:
    if not scenario or scenario["outcome"] == "n/a":
        return "n/a"
    total = sum(scenario["counts"].values())
    matching = scenario["counts"].get(scenario["outcome"], 0)
    text = f"{scenario['outcome']} {matching}/{total}" if scenario["runs"] else scenario["outcome"]
    if scenario["layers"]:
        text += f" ({', '.join(scenario['layers'])})"
    return text if scenario["outcome"] == scenario["expected"] else f"**{text}** (unexpected)"


def is_attack(scenario_id: str) -> bool:
    return not scenario_id.startswith("C-")


def main(argv: list[str]) -> int:
    paths = dict(zip(VARIANTS, map(Path, argv))) if len(argv) == 2 else {
        v: latest(v) for v in VARIANTS}
    reports = {v: json.loads(paths[v].read_text()) for v in VARIANTS}
    by_id = {v: {s["id"]: s for s in reports[v]["scenarios"]} for v in VARIANTS}
    ids = list(dict.fromkeys(i for v in VARIANTS for i in by_id[v]))

    lines = ["# Security evaluation: baseline vs Zero-Trust", ""]
    for v in VARIANTS:
        r = reports[v]
        lines.append(f"- **{v}**: `{paths[v].name}`, namespace `{r['namespace']}`, "
                     f"{r['repeat']} attempts per attack, commit `{r['environment']['git_commit']}`, "
                     f"sidecars: {r['environment']['istio_sidecar']}")
    lines += ["", "Outcome = what happened to the attack (`blocked` / `allowed`), "
              "attempts with that outcome / attempts, and the layer that stopped it.", "",
              "| ID | Threat | Scenario | Baseline | Zero-Trust |", "|---|---|---|---|---|"]
    for i in ids:
        any_s = by_id["zero-trust"].get(i) or by_id["baseline"].get(i)
        lines.append(f"| {i} | {any_s['threat']} | {any_s['title']} | "
                     f"{cell(by_id['baseline'].get(i))} | {cell(by_id['zero-trust'].get(i))} |")

    # Attacks that were run in both variants.
    common = [i for i in ids if is_attack(i) and all(
        by_id[v].get(i) and by_id[v][i]["outcome"] != "n/a" for v in VARIANTS)]
    stats = {}
    for v in VARIANTS:
        scen = [by_id[v][i] for i in common]
        stats[v] = {
            "scenarios_blocked": sum(s["outcome"] == "blocked" for s in scen),
            "scenarios": len(scen),
            "attempts_blocked": sum(s["counts"].get("blocked", 0) for s in scen),
            "attempts": sum(sum(s["counts"].values()) for s in scen),
        }
    zt, bl = stats["zero-trust"], stats["baseline"]
    p_scen = fisher_exact(zt["scenarios_blocked"], zt["scenarios"] - zt["scenarios_blocked"],
                          bl["scenarios_blocked"], bl["scenarios"] - bl["scenarios_blocked"])
    p_att = fisher_exact(zt["attempts_blocked"], zt["attempts"] - zt["attempts_blocked"],
                         bl["attempts_blocked"], bl["attempts"] - bl["attempts_blocked"])
    controls_ok = all(by_id[v][i]["outcome"] == "allowed"
                      for v in VARIANTS for i in ids if not is_attack(i) and i in by_id[v])

    lines += ["", "## Blocking rate (attacks run in both variants)", "",
              "| Variant | Scenarios blocked | Attempts blocked | Attack success rate |",
              "|---|---|---|---|"]
    for v in VARIANTS:
        s = stats[v]
        rate = 1 - s["attempts_blocked"] / s["attempts"] if s["attempts"] else 0
        lines.append(f"| {v} | {s['scenarios_blocked']}/{s['scenarios']} | "
                     f"{s['attempts_blocked']}/{s['attempts']} | {rate:.0%} |")
    lines += ["",
              f"Fisher's exact test, blocked vs not blocked by variant (two-sided):",
              f"- per scenario (primary): p = {p_scen:.3g}",
              f"- per attempt (secondary; attempts within a scenario are not independent): "
              f"p = {p_att:.3g}",
              "",
              f"Legitimate flow (C-*) succeeded in both variants: {'yes' if controls_ok else 'NO'}.",
              "Scenarios marked n/a have no counterpart in the baseline (it has no policy engine) "
              "and are left out of the test."]

    out = RESULTS / "summary.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
