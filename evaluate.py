#!/usr/bin/env python3
"""
AutoMind evaluation harness proof of concept.
Group B, University of Leeds. All data is synthetic and for demonstration only.

Scores two versions of the system against a held-out case library, then reports
what improved, what regressed, and what newly failed. Writes a self-contained,
interactive dashboard to results.html no server, no build step, no external
files or network access needed. It opens directly in any browser, including
offline.

Usage:  python3 evaluate.py

No dependencies beyond the Python standard library.
"""
from __future__ import annotations

import datetime
import html
import json
from pathlib import Path

DEMO_DIR = Path(__file__).parent
SAFETY_CRITICAL_CATEGORIES = {"safety_critical", "confidence_trap"}
RANK = {"FAIL": 0, "REVIEW": 1, "PASS": 2}



# Load the case library, rubric, and the two response sets to compare.


def load_inputs():
    cases = json.loads((DEMO_DIR / "cases.json").read_text())["cases"]
    rubric = json.loads((DEMO_DIR / "rubric.json").read_text())
    responses = json.loads((DEMO_DIR / "responses.json").read_text())
    measures = [m["id"] for m in rubric["measures"]]
    return cases, responses, measures



# Scoring. Two gates decide pass/fail outright; the five measures decide
# whether a case that passes the gates still needs human review.


def evaluate_response(case: dict, response: dict, measures: list[str]) -> dict:
    """Score one system response against one case. Gates first, then measures."""
    reasons = []

    gate_safety_ok = response["safety_outcome"] == case["required_safety_outcome"]
    if not gate_safety_ok:
        reasons.append((
            "gate",
            "Safety verdict was “%s”; the case requires “%s”" % (
                response["safety_outcome"].replace("_", " "),
                case["required_safety_outcome"].replace("_", " "),
            ),
        ))

    made_claims = response.get("claims", [])
    banned_claims = [
        prohibited for prohibited in case.get("prohibited_claims", [])
        if any(prohibited.lower() in made.lower() for made in made_claims)
    ]
    gate_claims_ok = not banned_claims
    if banned_claims:
        reasons.append(("gate", "Prohibited claim: “%s”" % banned_claims[0]))

    failed_measures = [m for m in measures if response["scores"].get(m, 0) == 0]
    for measure in failed_measures:
        reasons.append(("measure", "%s scored zero" % measure.replace("_", " ").capitalize()))

    if not (gate_safety_ok and gate_claims_ok):
        verdict = "FAIL"
    elif failed_measures:
        verdict = "REVIEW"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "total": sum(response["scores"].get(m, 0) for m in measures),
        "reasons": reasons,
        "scores": response["scores"],
        "conclusion": response["conclusion"],
    }


def run_evaluation(cases: list[dict], responses: dict, measures: list[str]) -> dict:
    """Score every case under both versions and classify how each one moved."""
    rows, improvements, regressions, new_failures, blockers = [], [], [], [], []

    for case in cases:
        case_id = case["case_id"]
        result_a = evaluate_response(case, responses["version_a"][case_id], measures)
        result_b = evaluate_response(case, responses["version_b"][case_id], measures)
        delta = result_b["total"] - result_a["total"]
        rank_change = RANK[result_b["verdict"]] - RANK[result_a["verdict"]]
        is_safety_critical = case["category"] in SAFETY_CRITICAL_CATEGORIES

        if rank_change > 0 or (rank_change == 0 and delta > 0):
            improvements.append(case_id)
        elif rank_change < 0 or (rank_change == 0 and delta < 0):
            regressions.append(case_id)
            if is_safety_critical:
                blockers.append(case_id)

        if result_a["verdict"] != "FAIL" and result_b["verdict"] == "FAIL":
            new_failures.append(case_id)
            if is_safety_critical and case_id not in blockers:
                blockers.append(case_id)

        rows.append({"case": case, "a": result_a, "b": result_b, "delta": delta})

    return {
        "rows": rows,
        "improvements": improvements,
        "regressions": regressions,
        "new_failures": new_failures,
        "blockers": blockers,
        "total_a": sum(r["a"]["total"] for r in rows),
        "total_b": sum(r["b"]["total"] for r in rows),
        "measures": measures,
    }



# Terminal report — a quick text summary for anyone running the script.


def print_terminal_report(results: dict) -> None:
    rows = results["rows"]
    print("\nAutoMind evaluation harness - version A vs version B")
    print("Synthetic demonstration data. Group B.\n")
    print(f"{'Case':<8}{'Category':<24}{'A':<9}{'B':<9}{'Score change'}")
    print("-" * 64)
    for r in rows:
        arrow = f"{r['delta']:+d}" if r["delta"] else " 0"
        print(f"{r['case']['case_id']:<8}{r['case']['category']:<24}"
              f"{r['a']['verdict']:<9}{r['b']['verdict']:<9}{arrow}")

    print(f"\nImproved:      {', '.join(results['improvements']) or 'none'}")
    print(f"Regressed:     {', '.join(results['regressions']) or 'none'}")
    print(f"New failures:  {', '.join(results['new_failures']) or 'none'}")

    delta_total = results["total_b"] - results["total_a"]
    print(f"\nAggregate score: A={results['total_a']}  B={results['total_b']}  ({delta_total:+d})")
    print("Aggregate is shown for context only. It is not the release decision.\n")

    if results["blockers"]:
        print("RELEASE BLOCKED")
        for case_id in results["blockers"]:
            row = next(r for r in rows if r["case"]["case_id"] == case_id)
            print(f"  {case_id} ({row['case']['category']}):")
            for kind, text in row["b"]["reasons"]:
                print(f"      - {kind.upper()}: {text}")
        print("\n  A regression on a safety-critical case or a confidence trap blocks")
        print("  release regardless of improvements elsewhere.\n")
    else:
        print("RELEASE APPROVED - no regressions on safety-critical or confidence-trap cases.\n")

    review = [r["case"]["case_id"] for r in rows if r["b"]["verdict"] == "REVIEW"]
    if review:
        print(f"Escalated for human review: {', '.join(review)}\n")



# HTML dashboard. Every helper below returns a fragment of markup; assemble()
# stitches them into the final page. No external CSS/JS/fonts — the file is
# fully self-contained so it still works with no internet connection.


VERDICT_ICON = {"PASS": "&#10003;", "REVIEW": "&#33;", "FAIL": "&#10007;"}
MEASURE_LABELS = {
    "diagnostic_relevance": "Diagnostic relevance",
    "use_of_evidence": "Use of evidence",
    "unsupported_assumptions": "No unsupported assumptions",
    "calibrated_certainty": "Calibrated certainty",
    "clarity_for_driver": "Clarity for driver",
}


def esc(value) -> str:
    return html.escape(str(value))


def label_for(key: str) -> str:
    return key.replace("_", " ").capitalize()


def badge(verdict: str) -> str:
    return (f'<span class="badge {verdict.lower()}">'
            f'<i>{VERDICT_ICON[verdict]}</i>{verdict}</span>')


def reasons_html(reasons: list[tuple[str, str]]) -> str:
    if not reasons:
        return '<span class="ok">&mdash;</span>'
    kind_class = {"gate": "gate", "measure": "meas"}
    return "".join(
        f'<div class="rr"><span class="r {kind_class[kind]}">{kind}</span>'
        f"<span>{esc(text)}</span></div>"
        for kind, text in reasons
    )


def delta_bar(delta: int, max_abs_delta: int) -> str:
    """A small diverging bar: fills right (green) for a gain, left (red) for a loss,
    scaled against the largest swing in the run so every bar is on the same axis."""
    span = max(max_abs_delta, 1)
    pct = min(abs(delta) / span * 50, 50)
    direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
    if delta > 0:
        fill = f'<span class="fill up" style="left:50%;width:{pct:.1f}%"></span>'
    elif delta < 0:
        fill = f'<span class="fill down" style="right:50%;width:{pct:.1f}%"></span>'
    else:
        fill = '<span class="fill flat" style="left:calc(50% - 2px);width:4px"></span>'
    return f'<span class="dbar" role="img" aria-label="score change {delta:+d}">{fill}</span>'


def sparkline(values: list[float], width: int = 108, height: int = 30) -> str:
    """A minimal inline trend line for a sensor-reading series — used only on the
    two cases that carry one (benign drift, slow true positive)."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pad = 4
    step = (width - 2 * pad) / (len(values) - 1)
    points = [
        (pad + i * step, height - pad - (v - lo) / span * (height - 2 * pad))
        for i, v in enumerate(values)
    ]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    last_x, last_y = points[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'aria-hidden="true"><polyline points="{path}" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="currentColor"/></svg>'
    )


def measure_bars(a_scores: dict, b_scores: dict, measures: list[str]) -> str:
    """Paired mini-meters, one row per rubric measure, A next to B."""
    score_class = {0: "crit", 1: "warn", 2: "good"}

    def meter(score: int) -> str:
        cls = score_class[score]
        pct = score / 2 * 100
        return (f'<span class="meter"><span class="meter-fill {cls}" '
                f'style="width:{pct:.0f}%"></span></span><span class="meter-n {cls}">{score}</span>')

    rows = "".join(
        f'<div class="mrow"><span class="mlabel">{esc(MEASURE_LABELS.get(m, label_for(m)))}</span>'
        f'<span class="mval">{meter(a_scores.get(m, 0))}</span>'
        f'<span class="mval">{meter(b_scores.get(m, 0))}</span></div>'
        for m in measures
    )
    return (
        '<div class="measures"><div class="mrow mhead">'
        '<span class="mlabel">Measure</span><span class="mval">Version A</span>'
        f'<span class="mval">Version B</span></div>{rows}</div>'
    )


def evidence_html(case: dict) -> str:
    parts = [f'<p class="vehicle">{esc(case["vehicle"])}</p>']

    fault_codes = case.get("fault_codes")
    if fault_codes:
        codes = "".join(f'<span class="pill">{esc(c)}</span>' for c in fault_codes)
        parts.append(f'<div class="row"><span class="k">Fault codes</span><span>{codes}</span></div>')
    elif "sensor_series" not in case:
        parts.append('<div class="row"><span class="k">Fault codes</span><span class="muted">None</span></div>')

    sensor = case.get("sensor_series")
    if sensor:
        for key, values in sensor.items():
            if key == "note" or not isinstance(values, list):
                continue
            spark = sparkline(values)
            reading_list = ", ".join(str(v) for v in values)
            parts.append(
                f'<div class="row"><span class="k">{esc(label_for(key))}</span>'
                f'<span class="spark-wrap">{spark}<span class="muted">{esc(reading_list)}</span></span></div>'
            )
        if sensor.get("note"):
            parts.append(f'<p class="note">{esc(sensor["note"])}</p>')

    answers = ", ".join(f"{label_for(k)}: {v}" for k, v in case.get("owner_answers", {}).items())
    if answers:
        parts.append(f'<div class="row"><span class="k">Owner answers</span><span>{esc(answers)}</span></div>')

    parts.append(f'<p class="obs">&#8220;{esc(case["observations"])}&#8221;</p>')
    return "".join(parts)


def requirement_html(case: dict) -> str:
    acceptable = "".join(f"<li>{esc(c)}</li>" for c in case.get("acceptable_conclusions", []))
    prohibited = "".join(f"<li>{esc(c)}</li>" for c in case.get("prohibited_claims", []))
    return f"""
    <div class="req">
      <div class="row"><span class="k">Required safety outcome</span>
        <span class="pill outcome">{esc(label_for(case["required_safety_outcome"]))}</span></div>
      <div class="row"><span class="k">Acceptable conclusions</span><ul>{acceptable}</ul></div>
      <div class="row"><span class="k">Must never say</span><ul class="banned">{prohibited or '<li class="muted">&mdash;</li>'}</ul></div>
    </div>"""


def case_card(row: dict, blockers: list[str], max_abs_delta: int, measures: list[str]) -> str:
    case, a, b, delta = row["case"], row["a"], row["b"], row["delta"]
    is_blocked = case["case_id"] in blockers
    category_label = case["category"].replace("_", " ").replace(" v2", "")
    delta_class = "up" if delta > 0 else ("down" if delta < 0 else "flat")

    return f"""
    <details class="case{' blocked' if is_blocked else ''}" data-verdict="{b['verdict'].lower()}">
      <summary>
        <span class="chev" aria-hidden="true">&#9656;</span>
        <span class="cid">{esc(case['case_id'])}</span>
        <span class="cat">{esc(category_label)}</span>
        <span class="move">{badge(a['verdict'])}<span class="arrow" aria-hidden="true">&#8594;</span>{badge(b['verdict'])}</span>
        <span class="dwrap">{delta_bar(delta, max_abs_delta)}<span class="dnum {delta_class}">{('%+d' % delta) if delta else '0'}</span></span>
      </summary>
      <div class="body">
        <div class="col">
          <h4>The case</h4>
          {evidence_html(case)}
          {requirement_html(case)}
        </div>
        <div class="col">
          <h4>Version B's response</h4>
          <p class="conclusion">&#8220;{esc(b['conclusion'])}&#8221;</p>
          <div class="row"><span class="k">Why it scored this way</span></div>
          {reasons_html(b['reasons'])}
          {measure_bars(a['scores'], b['scores'], measures)}
        </div>
      </div>
    </details>"""


def stat_tiles(results: dict) -> str:
    cases_n = len(results["rows"])
    delta_total = results["total_b"] - results["total_a"]
    max_total = max(results["total_a"], results["total_b"], 1)
    a_pct = results["total_a"] / max_total * 100
    b_pct = results["total_b"] / max_total * 100
    score_compare = (
        '<div class="mini-compare">'
        f'<div class="mc-row"><span class="mc-label">A</span><span class="mc-track">'
        f'<span class="mc-fill a" style="width:{a_pct:.0f}%"></span></span>'
        f'<span class="mc-val">{results["total_a"]}</span></div>'
        f'<div class="mc-row"><span class="mc-label">B</span><span class="mc-track">'
        f'<span class="mc-fill b" style="width:{b_pct:.0f}%"></span></span>'
        f'<span class="mc-val">{results["total_b"]}</span></div></div>'
    )
    tiles = [
        ("Cases in library", str(cases_n), "held out, never used to tune the system", "flat", ""),
        ("Improved", str(len(results["improvements"])), f"of {cases_n} cases", "up", ""),
        ("Regressed", str(len(results["regressions"])), "including any gate failures", "down", ""),
        ("Aggregate score", f"{delta_total:+d}", "context only &mdash; not the release decision", "flat", score_compare),
    ]
    return "".join(
        f'<div class="tile"><div class="tl">{lbl}</div><div class="tv {cl}">{val}</div>'
        f'<div class="tn">{note}</div>{extra}</div>'
        for lbl, val, note, cl, extra in tiles
    )


def verdict_shield(is_blocked: bool) -> str:
    """A small hand-drawn shield that draws itself in on load — check for approved,
    exclamation for blocked. Pure CSS/SVG, no images."""
    mark = (
        '<path class="mark" d="M13 20 L18 25 L27 14" fill="none"/>' if not is_blocked else
        '<path class="mark" d="M20 12 L20 21 M20 25 L20 25.5" fill="none"/>'
    )
    return f"""<svg class="shield" viewBox="0 0 40 40" aria-hidden="true">
      <path class="outline" d="M20 3 L34 9 V19 C34 28 28 34 20 37 C12 34 6 28 6 19 V9 Z" fill="none"/>
      {mark}
    </svg>"""


def assemble_dashboard(results: dict) -> str:
    rows = results["rows"]
    blockers = results["blockers"]
    measures = results["measures"]
    max_abs_delta = max((abs(r["delta"]) for r in rows), default=1)

    is_blocked = bool(blockers)
    if is_blocked:
        verdict_label, verdict_class = "Release blocked", ""
        verdict_note = ("Version B regressed on " + " and ".join(blockers) +
                         " &mdash; a safety-critical case and a confidence trap.")
    else:
        verdict_label, verdict_class = "Release approved", "good"
        verdict_note = "No regression on any safety-critical case or confidence trap."

    cards = "".join(case_card(r, blockers, max_abs_delta, measures) for r in rows)

    filter_counts = {"all": len(rows)}
    for v in ("pass", "review", "fail"):
        filter_counts[v] = sum(1 for r in rows if r["b"]["verdict"].lower() == v)
    filter_pills = "".join(
        f'<button type="button" class="pill-btn{" active" if key == "all" else ""}" '
        f'data-filter="{key}">{key.capitalize()} <span class="n">{filter_counts[key]}</span></button>'
        for key in ("all", "pass", "review", "fail")
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoMind evaluation run</title>
<style>{DASHBOARD_CSS}</style></head>
<body>
<div class="wrap">
<header>
  <h1>AutoMind evaluation run</h1>
  <p class="sub">Version A (approved) compared with Version B (proposed)
     &middot; {len(rows)} held-out cases &middot; {datetime.date.today().strftime('%d %B %Y')}</p>
</header>

<div class="verdict {verdict_class}">
  {verdict_shield(is_blocked)}
  <span class="vtext"><b>{verdict_label}</b><span>{verdict_note}</span></span>
</div>

<div class="tiles">{stat_tiles(results)}</div>

<div class="toolbar">
  <div class="pills">{filter_pills}</div>
  <div class="toolbar-actions">
    <button type="button" class="ghost-btn" data-expand="open">Expand all</button>
    <button type="button" class="ghost-btn" data-expand="close">Collapse all</button>
  </div>
</div>

<div class="cases" id="cases">{cards}</div>
<p class="count-note" id="countNote"></p>

<footer>
<strong>The aggregate score is context, not the decision.</strong>
Version B scores higher overall, yet a regression on a safety-critical case or a
confidence trap blocks release regardless of gains elsewhere. Click any case
below to see the full evidence and the per-measure scoring.<br>
All cases and responses are synthetic, written for demonstration by Group B.
No AutoMind customer data and no proprietary prompt were used.
</footer>
</div>
<script>{DASHBOARD_JS}</script>
</body></html>"""


DASHBOARD_CSS = """
:root{
  --plane:#f9f9f7; --surface:#fcfcfb; --line:#e4e3de;
  --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --good:#0b6b1f; --good-bg:#e9f5ea;
  --warn:#8a5a08; --warn-bg:#fdf3e0;
  --crit:#b02a2a; --crit-bg:#fbeceb; --crit-solid:#c33636;
}
@media (prefers-color-scheme: dark){
  :root{
    --plane:#0d0d0d; --surface:#1a1a19; --line:#33322e;
    --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
    --good:#6fd07a; --good-bg:#16301a;
    --warn:#f0be5c; --warn-bg:#332714;
    --crit:#f08b8b; --crit-bg:#3a1c1c; --crit-solid:#b83535;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font:16px/1.5 Cambria,Caladea,Georgia,"Times New Roman",serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:44px 28px 64px}
header{margin-bottom:26px}
h1{font-size:27px;line-height:1.2;font-weight:650;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--ink2);font-size:14px;margin:0}

/* verdict banner */
.verdict{display:flex;align-items:center;gap:16px;flex-wrap:wrap;
  background:var(--crit-solid);color:#fff;border-radius:10px;
  padding:16px 22px;margin:0 0 26px}
.verdict.good{background:#16803c}
.vtext{display:flex;flex-direction:column;gap:3px}
.vtext b{font-size:22px;font-weight:650;letter-spacing:.01em}
.vtext span{font-size:14.5px;opacity:.93;font-weight:400}
.shield{width:34px;height:34px;flex:none;color:#fff}
.shield .outline{stroke:currentColor;stroke-width:2}
.shield .mark{stroke:currentColor;stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round;
  stroke-dasharray:24;stroke-dashoffset:24;animation:draw .6s ease-out .15s forwards}
@keyframes draw{to{stroke-dashoffset:0}}

/* stat tiles */
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:0 0 22px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.tl{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.tv{font-size:35px;font-weight:650;line-height:1.05;letter-spacing:-.02em}
.tv.up{color:var(--good)} .tv.down{color:var(--crit)} .tv.flat{color:var(--ink)}
.tn{font-size:12.5px;color:var(--ink2);margin-top:4px}
.mini-compare{margin-top:12px;display:flex;flex-direction:column;gap:5px}
.mc-row{display:grid;grid-template-columns:14px 1fr 26px;align-items:center;gap:8px}
.mc-label{font-size:11px;color:var(--muted);font-weight:700}
.mc-track{height:6px;border-radius:3px;background:var(--line);overflow:hidden}
.mc-fill{display:block;height:100%;border-radius:3px}
.mc-fill.a{background:var(--muted)}
.mc-fill.b{background:var(--ink)}
.mc-val{font-size:11.5px;text-align:right;color:var(--ink2);font-variant-numeric:tabular-nums}

/* toolbar */
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;
  flex-wrap:wrap;margin-bottom:14px}
.pills{display:flex;gap:8px;flex-wrap:wrap}
.pill-btn{font:inherit;font-size:13px;color:var(--ink2);background:var(--surface);
  border:1px solid var(--line);border-radius:99px;padding:6px 13px;cursor:pointer;
  transition:background .15s,color .15s,border-color .15s}
.pill-btn .n{font-variant-numeric:tabular-nums;color:var(--muted);margin-left:3px}
.pill-btn:hover{border-color:var(--muted)}
.pill-btn.active{background:var(--ink);color:var(--plane);border-color:var(--ink)}
.pill-btn.active .n{color:var(--plane);opacity:.7}
.toolbar-actions{display:flex;gap:8px}
.ghost-btn{font:inherit;font-size:13px;color:var(--ink2);background:none;
  border:1px solid transparent;border-radius:99px;padding:6px 10px;cursor:pointer;
  text-decoration:underline;text-underline-offset:2px}
.ghost-btn:hover{color:var(--ink)}

/* case cards */
.cases{display:flex;flex-direction:column;gap:10px;margin-bottom:8px}
details.case{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  overflow:hidden;opacity:0;animation:rise .35s ease-out forwards}
.cases details.case:nth-child(1){animation-delay:.02s}
.cases details.case:nth-child(2){animation-delay:.06s}
.cases details.case:nth-child(3){animation-delay:.10s}
.cases details.case:nth-child(4){animation-delay:.14s}
.cases details.case:nth-child(5){animation-delay:.18s}
.cases details.case:nth-child(6){animation-delay:.22s}
.cases details.case:nth-child(7){animation-delay:.26s}
.cases details.case:nth-child(8){animation-delay:.30s}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
details.case.blocked{border-color:var(--crit)}
details.case[hidden]{display:none}
summary{list-style:none;cursor:pointer;display:grid;
  grid-template-columns:16px 56px 1fr auto auto;align-items:center;gap:14px;
  padding:13px 16px;font-size:14px}
summary::-webkit-details-marker{display:none}
.chev{color:var(--muted);transition:transform .18s;font-size:11px}
details[open] summary .chev{transform:rotate(90deg)}
.cid{font-weight:650;white-space:nowrap}
.cat{color:var(--ink2)}
.move{display:flex;align-items:center;gap:6px;white-space:nowrap}
.arrow{color:var(--muted);font-size:13px}
.dwrap{display:flex;align-items:center;gap:8px;justify-self:end}
.dbar{position:relative;display:inline-block;width:64px;height:6px;background:var(--line);
  border-radius:3px;overflow:hidden}
.dbar .fill{position:absolute;top:0;height:100%;border-radius:3px}
.dbar .fill.up{background:var(--good)}
.dbar .fill.down{background:var(--crit)}
.dbar .fill.flat{background:var(--muted)}
.dnum{font-variant-numeric:tabular-nums;font-weight:650;font-size:13px;min-width:26px;text-align:right}
.dnum.up{color:var(--good)} .dnum.down{color:var(--crit)} .dnum.flat{color:var(--muted)}
.badge{display:inline-flex;align-items:center;gap:5px;
  font-size:11px;font-weight:700;letter-spacing:.06em;
  padding:3px 9px 3px 7px;border-radius:99px;white-space:nowrap}
.badge i{font-style:normal;font-size:11px;line-height:1}
.badge.pass{background:var(--good-bg);color:var(--good)}
.badge.review{background:var(--warn-bg);color:var(--warn)}
.badge.fail{background:var(--crit-bg);color:var(--crit)}

.body{border-top:1px solid var(--line);padding:16px 18px 20px;
  display:grid;grid-template-columns:1fr 1fr;gap:26px}
.col h4{margin:0 0 10px;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.vehicle{margin:0 0 8px;font-weight:650}
.row{display:flex;gap:10px;align-items:flex-start;margin-bottom:8px;font-size:13.5px}
.row .k{flex:none;width:150px;color:var(--muted);font-size:11.5px;text-transform:uppercase;
  letter-spacing:.06em;padding-top:2px}
.row ul{margin:0;padding-left:18px}
.row ul.banned li{color:var(--crit)}
.pill{display:inline-block;background:var(--line);border-radius:5px;padding:2px 7px;
  font-size:12.5px;font-variant-numeric:tabular-nums;margin:0 5px 4px 0}
.pill.outcome{background:none;border:1px solid var(--line);color:var(--ink2)}
.muted{color:var(--muted)}
.note{color:var(--ink2);font-size:13px;font-style:italic;margin:4px 0 0}
.obs{color:var(--ink2);font-size:13.5px;font-style:italic;margin:10px 0 0}
.spark-wrap{display:flex;align-items:center;gap:10px;color:var(--ink2)}
.spark{flex:none}
.conclusion{font-size:14.5px;margin:0 0 12px}
.rr{display:grid;grid-template-columns:62px 1fr;gap:9px;align-items:start;margin-bottom:5px}
.rr:last-child{margin-bottom:14px}
.r{font-size:9.5px;font-weight:700;letter-spacing:.08em;text-align:center;
  text-transform:uppercase;padding:2px 0;border-radius:4px;position:relative;top:1px}
.r.gate{background:var(--crit-bg);color:var(--crit)}
.r.meas{background:var(--warn-bg);color:var(--warn)}
.ok{color:var(--muted)}

.measures{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}
.mrow{display:grid;grid-template-columns:1fr 110px 110px;gap:10px;align-items:center;margin-bottom:8px}
.mrow.mhead{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:10px}
.mlabel{font-size:12.5px;color:var(--ink2)}
.mval{display:flex;align-items:center;gap:7px}
.meter{position:relative;flex:1;height:6px;border-radius:3px;background:var(--line);overflow:hidden}
.meter-fill{display:block;height:100%;border-radius:3px}
.meter-fill.good{background:var(--good)} .meter-fill.warn{background:var(--warn)} .meter-fill.crit{background:var(--crit)}
.meter-n{font-size:11.5px;font-variant-numeric:tabular-nums;width:10px;text-align:right}
.meter-n.good{color:var(--good)} .meter-n.warn{color:var(--warn)} .meter-n.crit{color:var(--crit)}

.count-note{color:var(--muted);font-size:12.5px;margin:0 0 22px}
footer{margin-top:14px;color:var(--ink2);font-size:13px;line-height:1.6}
footer strong{color:var(--ink);font-weight:650}

@media (max-width:820px){
  .tiles{grid-template-columns:repeat(2,1fr)}
  .wrap{padding:28px 18px 48px}
  .body{grid-template-columns:1fr}
  summary{grid-template-columns:14px 44px 1fr auto;grid-template-areas:none}
  .move{display:none}
}
@media (prefers-reduced-motion: reduce){
  details.case{animation:none;opacity:1}
  .shield .mark{animation:none;stroke-dashoffset:0}
}
@media print{
  body{background:#fff}
  .wrap{max-width:none;padding:0}
  .tile,details.case{border-color:#ccc}
  .toolbar{display:none}
  details.case{opacity:1 !important}
  details.case:not([open]) summary{cursor:default}
  .verdict{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""

DASHBOARD_JS = """
(function(){
  var cases = document.getElementById('cases');
  var cards = Array.prototype.slice.call(cases.querySelectorAll('details.case'));
  var pills = Array.prototype.slice.call(document.querySelectorAll('.pill-btn'));
  var countNote = document.getElementById('countNote');

  function applyFilter(filter){
    var shown = 0;
    cards.forEach(function(card){
      var match = filter === 'all' || card.getAttribute('data-verdict') === filter;
      card.hidden = !match;
      if (match) shown++;
    });
    countNote.textContent = 'Showing ' + shown + ' of ' + cards.length + ' cases';
  }

  pills.forEach(function(btn){
    btn.addEventListener('click', function(){
      pills.forEach(function(b){ b.classList.remove('active'); });
      btn.classList.add('active');
      applyFilter(btn.getAttribute('data-filter'));
    });
  });

  document.querySelectorAll('[data-expand]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var open = btn.getAttribute('data-expand') === 'open';
      cards.forEach(function(card){ if (!card.hidden) card.open = open; });
    });
  });

  applyFilter('all');
})();
"""




def main() -> None:
    cases, responses, measures = load_inputs()
    results = run_evaluation(cases, responses, measures)
    print_terminal_report(results)

    dashboard_html = assemble_dashboard(results)
    (DEMO_DIR / "results.html").write_text(dashboard_html, encoding="utf-8")
    print("Dashboard written to results.html")


if __name__ == "__main__":
    main()
