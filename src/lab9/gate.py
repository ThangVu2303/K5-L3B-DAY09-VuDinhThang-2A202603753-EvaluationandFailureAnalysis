"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows = pr.get("rows") or []
    graded = _graded_metrics(spec)

    # 1. Aggregate metrics must be finite numbers (NaN < min is False: a naive gate passes it).
    for m, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {m} is {v} (NaN/inf hides a missing value)")

    # 2. Evaluator failures and missing / non-boolean row values for graded metrics.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), e.g. {pr['evaluator_failures'][0]!s:.80}")
    bad_vals: dict[str, int] = {}
    for r in rows:
        for m in graded:
            v = r.get(m)
            if v is None or (isinstance(v, float) and not math.isfinite(v)) or not isinstance(v, (bool, int, float)):
                bad_vals[m] = bad_vals.get(m, 0) + 1
    problems += [f"{n} row(s) with no value for graded metric {m} (crashed grader dropped from the mean)"
                 for m, n in sorted(bad_vals.items())]

    # 3. Row count, duplicates, and the exact (item, seed) grid of the baseline.
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    want = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), e.g. {dups[0]}")
    if man.get("items") != bman.get("items") or sorted(man.get("seeds") or []) != sorted(bman.get("seeds") or []):
        problems.append(f"manifest differs from baseline: items {man.get('items')} vs {bman.get('items')}, "
                        f"seeds {man.get('seeds')} vs {bman.get('seeds')}")
    pk = set(keys)
    bk = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if pk != bk:
        problems.append(f"(item, seed) set differs from baseline: {len(bk - pk)} missing, {len(pk - bk)} extra")

    # 4. Slice tags per item must match the baseline (relabelling hides a slice regression).
    def tags(rep: dict) -> dict[str, tuple[str, ...]]:
        out: dict[str, set[str]] = {}
        for r in rep.get("rows") or []:
            out.setdefault(r.get("item_id"), set()).update(r.get("slices") or [])
        return {k: tuple(sorted(v)) for k, v in out.items()}
    pt, bt = tags(pr), tags(base)
    relabelled = sorted(i for i in set(pt) & set(bt) if pt[i] != bt[i])
    if relabelled:
        problems.append(f"slice tags changed vs baseline on {len(relabelled)} item(s), e.g. {relabelled[0]}: "
                        f"{list(bt[relabelled[0]])} -> {list(pt[relabelled[0]])}")
    per_row = {}
    for r in rows:
        per_row.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
    mixed = sorted(i for i, s in per_row.items() if len(s) > 1)
    if mixed:
        problems.append(f"item {mixed[0]} carries different slice tags on different seeds")

    # 5. Reported aggregates must equal what the rows say (hand-edited metrics).
    if rows and not bad_vals:
        problems += _recompute_mismatch(pr, spec)

    # 6. Ratchet: on the same eval set a spec may only get stricter.
    if base_spec is not None:
        same_set = (spec.get("eval_set_version") == base_spec.get("eval_set_version")
                    or man.get("eval_set_sha") == bman.get("eval_set_sha"))
        if same_set:
            problems += ratchet_problems(spec, base_spec)
    return problems


def _graded_metrics(spec: dict) -> list[str]:
    """Spec metrics scored per row by a grader (not the derived pass_5 / cost_per_success)."""
    from lab9.graders import GRADERS
    return [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]


def _recompute_mismatch(pr: dict, spec: dict) -> list[str]:
    from lab9.eval import aggregate
    rows = pr["rows"]
    has_cost = all("cost" in r for r in rows)
    graded = [m for m in _graded_metrics(spec) if all(m in r for r in rows)]
    try:
        again = aggregate([r if has_cost else {**r, "cost": 0.0} for r in rows], graded,
                          k_values=spec.get("pass_k", []))
    except Exception as e:  # noqa: BLE001 - a report the aggregator cannot read is not trustworthy
        return [f"metrics cannot be recomputed from rows: {type(e).__name__}: {e}"]
    out = []
    for m, v in (pr.get("metrics") or {}).items():
        if m not in again or (m == "cost_per_success" and not has_cost):
            continue
        w = again[m]
        if v is None and w is None:
            continue
        if (v is None) != (w is None) or abs(float(v) - float(w)) > 1e-6:
            out.append(f"metric {m} = {v} but its rows give {w} (aggregate edited by hand)")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval set => thresholds may only tighten. Returns one line per loosening."""
    out: list[str] = []
    for f in ("eval_set", "labels", "seeds", "bootstrap", "adversarial_pack", "pass_k"):
        if f in base_spec and spec.get(f) != base_spec.get(f):
            out.append(f"RATCHET {f} changed ({base_spec.get(f)!r} -> {spec.get(f)!r}) on the same eval set")

    def compare(kind: str, key: str, new: dict | None, old: dict) -> None:
        if new is None:
            out.append(f"RATCHET {kind} {key} removed")
            return
        if old.get("blocking") and not new.get("blocking"):
            out.append(f"RATCHET {kind} {key} no longer blocking")
        ot, nt = old.get("threshold", old), new.get("threshold", new)
        for t in ("max", "max_increase"):
            if t in ot and (t not in nt or nt[t] > ot[t]):
                out.append(f"RATCHET {kind} {key} {t} loosened {ot[t]} -> {nt.get(t)}")
        if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
            out.append(f"RATCHET {kind} {key} min loosened {ot['min']} -> {nt.get('min')}")
        if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
            out.append(f"RATCHET {kind} {key} dropped no_significant_drop")

    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        compare("metric", m["id"], new_m.get(m["id"]), m)
    new_s = {(s["name"], s.get("metric")): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        compare("slice", f"{s['name']}/{s.get('metric')}", new_s.get((s["name"], s.get("metric"))), s)
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s.get("metric", "pass_rate")
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict, note = "missing", "no PR rows carry this slice"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<28} {label} (n={len(a)} items)")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
