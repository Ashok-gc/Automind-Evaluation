#!/usr/bin/env python3
"""
AutoMind evaluation harness — proof of concept.
Group B, University of Leeds. All data is synthetic and for demonstration only.

Scores two versions of the system against a held-out case library, then reports
what improved, what regressed, and what newly failed. Writes a self-contained,
interactive dashboard to results.html — no server, no build step, no external
files or network access needed. It opens directly in any browser, including
offline.

The dashboard is genuinely dynamic, not just click-to-reveal: every gate and
score for Version B is editable in the browser, and the verdict, the reasons,
the totals and the release decision all recompute live from the same rules
this script applies. Nothing you change in the browser writes back to disk —
refreshing the page (or the on-page Reset) always returns to the actual
recorded run.

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
MEASURE_LABELS = {
    "diagnostic_relevance": "Diagnostic relevance",
    "use_of_evidence": "Use of evidence",
    "unsupported_assumptions": "No unsupported assumptions",
    "calibrated_certainty": "Calibrated certainty",
    "clarity_for_driver": "Clarity for driver",
}


# --------------------------------------------------------------------------
# Load the case library, rubric, and the two response sets to compare.
# --------------------------------------------------------------------------

def load_inputs():
    cases = json.loads((DEMO_DIR / "cases.json").read_text())["cases"]
    rubric = json.loads((DEMO_DIR / "rubric.json").read_text())
    responses = json.loads((DEMO_DIR / "responses.json").read_text())
    measures = [m["id"] for m in rubric["measures"]]
    return cases, responses, measures


# --------------------------------------------------------------------------
# Scoring. Two gates decide pass/fail outright; the five measures decide
# whether a case that passes the gates still needs human review. This is the
# single source of truth for the rule — the JS in the dashboard mirrors it
# exactly so an edit made in the browser is scored the same way.
# --------------------------------------------------------------------------

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
        "gate_safety_ok": gate_safety_ok,
        "gate_claims_ok": gate_claims_ok,
        "scores": response["scores"],
        "conclusion": response["conclusion"],
    }


def classify_movement(case: dict, result_a: dict, result_b: dict, delta: int) -> dict:
    """Given A and B's results for one case, decide improved / regressed / new failure
    / release-blocker. Shared by the terminal report and the seed data sent to the
    browser, so a live edit in the dashboard is classified by exactly this rule."""
    rank_change = RANK[result_b["verdict"]] - RANK[result_a["verdict"]]
    is_safety_critical = case["category"] in SAFETY_CRITICAL_CATEGORIES

    improved = rank_change > 0 or (rank_change == 0 and delta > 0)
    regressed = rank_change < 0 or (rank_change == 0 and delta < 0)
    new_failure = result_a["verdict"] != "FAIL" and result_b["verdict"] == "FAIL"
    is_blocker = is_safety_critical and (regressed or new_failure)

    return {"improved": improved, "regressed": regressed,
            "new_failure": new_failure, "is_blocker": is_blocker}


def run_evaluation(cases: list[dict], responses: dict, measures: list[str]) -> dict:
    """Score every case under both versions and classify how each one moved."""
    rows, improvements, regressions, new_failures, blockers = [], [], [], [], []

    for case in cases:
        case_id = case["case_id"]
        result_a = evaluate_response(case, responses["version_a"][case_id], measures)
        result_b = evaluate_response(case, responses["version_b"][case_id], measures)
        delta = result_b["total"] - result_a["total"]
        movement = classify_movement(case, result_a, result_b, delta)

        if movement["improved"]:
            improvements.append(case_id)
        elif movement["regressed"]:
            regressions.append(case_id)
        if movement["new_failure"]:
            new_failures.append(case_id)
        if movement["is_blocker"] and case_id not in blockers:
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


# --------------------------------------------------------------------------
# Terminal report — a quick text summary for anyone running the script.
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# HTML dashboard. Every helper below returns a fragment of markup; assemble()
# stitches them into the final page. No external CSS/JS/fonts, and no fetch
# calls — the case data is embedded directly, so the file is fully
# self-contained and still works with no internet connection.
# --------------------------------------------------------------------------

VERDICT_ICON = {"PASS": "&#10003;", "REVIEW": "&#33;", "FAIL": "&#10007;"}


def esc(value) -> str:
    return html.escape(str(value))


def label_for(key: str) -> str:
    return key.replace("_", " ").capitalize()


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


def a_measure_rows(a_scores: dict, measures: list[str]) -> str:
    """Version A's scores, shown fixed — this is the currently-approved baseline
    and isn't editable in the dashboard."""
    score_class = {0: "crit", 1: "warn", 2: "good"}

    def meter(score: int) -> str:
        cls = score_class[score]
        pct = score / 2 * 100
        return (f'<span class="meter"><span class="meter-fill {cls}" '
                f'style="width:{pct:.0f}%"></span></span><span class="meter-n {cls}">{score}</span>')

    return "".join(
        f'<div class="mrow"><span class="mlabel">{esc(MEASURE_LABELS.get(m, label_for(m)))}</span>'
        f'<span class="mval">{meter(a_scores.get(m, 0))}</span></div>'
        for m in measures
    )


def b_measure_controls(case_id: str, b_scores: dict, measures: list[str]) -> str:
    """Version B's scores, rendered as clickable meters. JS cycles each 0→1→2 and
    recomputes the case (and the whole dashboard) live."""
    return "".join(
        f'<div class="mrow">'
        f'<span class="mlabel">{esc(MEASURE_LABELS.get(m, label_for(m)))}</span>'
        f'<button type="button" class="mval mbtn" data-case="{esc(case_id)}" data-measure="{esc(m)}" '
        f'aria-label="{esc(MEASURE_LABELS.get(m, label_for(m)))} for Version B, click to change score">'
        f'<span class="meter"><span class="meter-fill" data-fill></span></span>'
        f'<span class="meter-n" data-n></span></button></div>'
        for m in measures
    )


def gate_chip(case_id: str, gate: str, label: str) -> str:
    return (f'<button type="button" class="gate-chip" data-case="{esc(case_id)}" data-gate="{gate}">'
            f'<i data-icon></i><span data-label>{esc(label)}</span></button>')


def case_card(row: dict, measures: list[str]) -> str:
    case, a = row["case"], row["a"]
    case_id = case["case_id"]
    category_label = case["category"].replace("_", " ").replace(" v2", "")

    return f"""
    <details class="case" id="case-{esc(case_id)}" data-case="{esc(case_id)}">
      <summary>
        <span class="chev" aria-hidden="true">&#9656;</span>
        <span class="cid">{esc(case_id)} <span class="edited-tag" data-edited-tag hidden>edited</span></span>
        <span class="cat">{esc(category_label)}</span>
        <span class="move" data-move>
          <span class="badge {a['verdict'].lower()}"><i>{VERDICT_ICON[a['verdict']]}</i>{a['verdict']}</span>
          <span class="arrow" aria-hidden="true">&#8594;</span>
          <span class="badge" data-b-badge></span>
        </span>
        <span class="dwrap">
          <span class="dbar" data-dbar role="img" aria-label="score change"><span class="fill" data-dfill></span></span>
          <span class="dnum" data-dnum></span>
        </span>
      </summary>
      <div class="body">
        <div class="col">
          <h4>The case</h4>
          {evidence_html(case)}
          {requirement_html(case)}
        </div>
        <div class="col">
          <div class="colhead">
            <h4>Version B's response</h4>
            <button type="button" class="reset-btn" data-reset="{esc(case_id)}" hidden>Reset this case</button>
          </div>
          <p class="conclusion">&#8220;{esc(row['b']['conclusion'])}&#8221;</p>

          <div class="gates">
            {gate_chip(case_id, 'safety', 'Safety outcome met')}
            {gate_chip(case_id, 'claims', 'No prohibited claim made')}
          </div>

          <div class="row"><span class="k">Why it scored this way</span></div>
          <div class="reasons" data-reasons></div>

          <div class="measures">
            <div class="mrow mhead"><span class="mlabel">Measure</span>
              <span class="mval">Version A &middot; fixed</span></div>
            {a_measure_rows(a['scores'], measures)}
            <div class="mrow mhead sep"><span class="mlabel"></span>
              <span class="mval">Version B &middot; click to try a score</span></div>
            {b_measure_controls(case_id, row['b']['scores'], measures)}
          </div>
        </div>
      </div>
    </details>"""


def verdict_shield() -> str:
    """A small hand-drawn shield that draws itself in on load, then swaps its mark
    live between a check and an exclamation as the release decision changes."""
    return """<svg class="shield" viewBox="0 0 40 40" aria-hidden="true">
      <path class="outline" d="M20 3 L34 9 V19 C34 28 28 34 20 37 C12 34 6 28 6 19 V9 Z" fill="none"/>
      <path class="mark mark-ok" data-mark-ok d="M13 20 L18 25 L27 14" fill="none"/>
      <path class="mark mark-bad" data-mark-bad d="M20 12 L20 21 M20 25 L20 25.5" fill="none"/>
    </svg>"""


def build_seed(results: dict) -> list[dict]:
    """Everything the browser needs to recompute a case from scratch, matching
    evaluate_response()/classify_movement() exactly. Sent to the page as JSON."""
    seed = []
    for row in results["rows"]:
        case, a, b = row["case"], row["a"], row["b"]

        safety_fail_text = next(
            (t for k, t in b["reasons"] if k == "gate" and t.startswith("Safety verdict")), None
        ) or ("Safety verdict does not match what this case requires "
              "(“%s”)." % label_for(case["required_safety_outcome"]))
        claims_fail_text = next(
            (t for k, t in b["reasons"] if k == "gate" and t.startswith("Prohibited claim")), None
        ) or "A prohibited claim was made that this case must not include."

        seed.append({
            "id": case["case_id"],
            "category": case["category"],
            "isCritical": case["category"] in SAFETY_CRITICAL_CATEGORIES,
            "aTotal": a["total"],
            "aVerdict": a["verdict"],
            "bScoresInit": dict(b["scores"]),
            "bGateSafetyInit": b["gate_safety_ok"],
            "bGateClaimsInit": b["gate_claims_ok"],
            "gateSafetyFailText": safety_fail_text,
            "gateClaimsFailText": claims_fail_text,
        })
    return seed


def assemble_dashboard(results: dict) -> str:
    rows = results["rows"]
    measures = results["measures"]
    cards = "".join(case_card(r, measures) for r in rows)
    seed_json = json.dumps(build_seed(results)).replace("</", "<\\/")
    measure_labels_json = json.dumps(MEASURE_LABELS).replace("</", "<\\/")

    filter_pills = "".join(
        f'<button type="button" class="pill-btn{" active" if key == "all" else ""}" '
        f'data-filter="{key}">{key.capitalize()} <span class="n" data-count="{key}"></span></button>'
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

<div class="verdict" id="verdictBox">
  {verdict_shield()}
  <span class="vtext"><b data-verdict-label></b><span data-verdict-note></span></span>
</div>

<div class="tiles">
  <div class="tile"><div class="tl">Cases in library</div><div class="tv flat">{len(rows)}</div>
    <div class="tn">held out, never used to tune the system</div></div>
  <div class="tile"><div class="tl">Improved</div><div class="tv up" data-tile="improved"></div>
    <div class="tn">of {len(rows)} cases</div></div>
  <div class="tile"><div class="tl">Regressed</div><div class="tv down" data-tile="regressed"></div>
    <div class="tn">including any gate failures</div></div>
  <div class="tile"><div class="tl">Aggregate score</div><div class="tv flat" data-tile="agg"></div>
    <div class="tn">context only &mdash; not the release decision</div>
    <div class="mini-compare">
      <div class="mc-row"><span class="mc-label">A</span><span class="mc-track">
        <span class="mc-fill a" data-mc="a"></span></span><span class="mc-val" data-mc-val="a"></span></div>
      <div class="mc-row"><span class="mc-label">B</span><span class="mc-track">
        <span class="mc-fill b" data-mc="b"></span></span><span class="mc-val" data-mc-val="b"></span></div>
    </div>
  </div>
</div>

<p class="live-note">Every gate and score for Version B below is editable &mdash; click one to see how
the release decision responds. This never writes back to the case files; refresh the page or use
Reset to return to the actual recorded run.</p>

<div class="toolbar">
  <div class="pills">{filter_pills}</div>
  <div class="toolbar-actions">
    <button type="button" class="ghost-btn" data-expand="open">Expand all</button>
    <button type="button" class="ghost-btn" data-expand="close">Collapse all</button>
    <button type="button" class="ghost-btn" id="resetAll">Reset all</button>
  </div>
</div>

<div class="cases" id="cases">{cards}</div>
<p class="count-note" id="countNote"></p>

<footer>
<strong>The aggregate score is context, not the decision.</strong>
Version B scores higher overall as recorded, yet a regression on a safety-critical case or a
confidence trap blocks release regardless of gains elsewhere.<br>
All cases and responses are synthetic, written for demonstration by Group B.
No AutoMind customer data and no proprietary prompt were used.
</footer>
</div>
<script>
const SEED = {seed_json};
const MEASURE_LABELS = {measure_labels_json};
{DASHBOARD_JS}
</script>
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
  padding:16px 22px;margin:0 0 14px;transition:background .25s}
.verdict.good{background:#16803c}
.vtext{display:flex;flex-direction:column;gap:3px}
.vtext b{font-size:22px;font-weight:650;letter-spacing:.01em}
.vtext span{font-size:14.5px;opacity:.93;font-weight:400}
.shield{width:34px;height:34px;flex:none;color:#fff}
.shield .outline{stroke:currentColor;stroke-width:2}
.shield .mark{stroke:currentColor;stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round;
  transition:opacity .15s}
.mark-ok{stroke-dasharray:24;stroke-dashoffset:24;animation:draw .6s ease-out .15s forwards}
.verdict.good .mark-bad,.verdict:not(.good) .mark-ok{opacity:0}
@keyframes draw{to{stroke-dashoffset:0}}
.live-note{color:var(--ink2);font-size:12.5px;font-style:italic;margin:0 0 18px;max-width:74ch}

/* stat tiles */
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:0 0 10px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.tl{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.tv{font-size:35px;font-weight:650;line-height:1.05;letter-spacing:-.02em;transition:color .2s}
.tv.up{color:var(--good)} .tv.down{color:var(--crit)} .tv.flat{color:var(--ink)}
.tn{font-size:12.5px;color:var(--ink2);margin-top:4px}
.mini-compare{margin-top:12px;display:flex;flex-direction:column;gap:5px}
.mc-row{display:grid;grid-template-columns:14px 1fr 26px;align-items:center;gap:8px}
.mc-label{font-size:11px;color:var(--muted);font-weight:700}
.mc-track{height:6px;border-radius:3px;background:var(--line);overflow:hidden}
.mc-fill{display:block;height:100%;border-radius:3px;transition:width .2s}
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
.toolbar-actions{display:flex;gap:8px;align-items:center}
.ghost-btn{font:inherit;font-size:13px;color:var(--ink2);background:none;
  border:1px solid transparent;border-radius:99px;padding:6px 10px;cursor:pointer;
  text-decoration:underline;text-underline-offset:2px}
.ghost-btn:hover{color:var(--ink)}

/* case cards */
.cases{display:flex;flex-direction:column;gap:10px;margin-bottom:8px}
details.case{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  overflow:hidden;opacity:0;animation:rise .35s ease-out forwards;transition:border-color .2s}
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
  grid-template-columns:16px 110px 1fr auto auto;align-items:center;gap:14px;
  padding:13px 16px;font-size:14px}
summary::-webkit-details-marker{display:none}
.chev{color:var(--muted);transition:transform .18s;font-size:11px}
details[open] summary .chev{transform:rotate(90deg)}
.cid{font-weight:650;white-space:nowrap;display:flex;align-items:center;gap:6px}
.edited-tag{font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:700;
  color:var(--warn);background:var(--warn-bg);border-radius:4px;padding:2px 5px}
.cat{color:var(--ink2)}
.move{display:flex;align-items:center;gap:6px;white-space:nowrap}
.arrow{color:var(--muted);font-size:13px}
.dwrap{display:flex;align-items:center;gap:8px;justify-self:end}
.dbar{position:relative;display:inline-block;width:64px;height:6px;background:var(--line);
  border-radius:3px;overflow:hidden}
.dbar .fill{position:absolute;top:0;height:100%;border-radius:3px;transition:all .2s}
.dbar .fill.up{background:var(--good)}
.dbar .fill.down{background:var(--crit)}
.dbar .fill.flat{background:var(--muted)}
.dnum{font-variant-numeric:tabular-nums;font-weight:650;font-size:13px;min-width:26px;text-align:right}
.dnum.up{color:var(--good)} .dnum.down{color:var(--crit)} .dnum.flat{color:var(--muted)}
.badge{display:inline-flex;align-items:center;gap:5px;
  font-size:11px;font-weight:700;letter-spacing:.06em;
  padding:3px 9px 3px 7px;border-radius:99px;white-space:nowrap;transition:background .15s,color .15s}
.badge i{font-style:normal;font-size:11px;line-height:1}
.badge.pass{background:var(--good-bg);color:var(--good)}
.badge.review{background:var(--warn-bg);color:var(--warn)}
.badge.fail{background:var(--crit-bg);color:var(--crit)}

.body{border-top:1px solid var(--line);padding:16px 18px 20px;
  display:grid;grid-template-columns:1fr 1fr;gap:26px}
.col h4{margin:0;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.colhead{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.reset-btn{font:inherit;font-size:11.5px;color:var(--warn);background:var(--warn-bg);
  border:none;border-radius:99px;padding:3px 10px;cursor:pointer}
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

.gates{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.gate-chip{font:inherit;font-size:12px;font-weight:650;display:inline-flex;align-items:center;gap:6px;
  border-radius:99px;padding:5px 12px;cursor:pointer;border:1px solid transparent;transition:all .15s}
.gate-chip[data-state="pass"]{background:var(--good-bg);color:var(--good)}
.gate-chip[data-state="fail"]{background:var(--crit-bg);color:var(--crit)}
.gate-chip:hover{filter:brightness(0.95)}

.reasons{margin-bottom:6px}
.rr{display:grid;grid-template-columns:62px 1fr;gap:9px;align-items:start;margin-bottom:5px}
.rr:last-child{margin-bottom:14px}
.r{font-size:9.5px;font-weight:700;letter-spacing:.08em;text-align:center;
  text-transform:uppercase;padding:2px 0;border-radius:4px;position:relative;top:1px}
.r.gate{background:var(--crit-bg);color:var(--crit)}
.r.meas{background:var(--warn-bg);color:var(--warn)}
.ok{color:var(--muted)}

.measures{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}
.mrow{display:grid;grid-template-columns:1fr 130px;gap:10px;align-items:center;margin-bottom:8px}
.mrow.mhead{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:10px}
.mrow.mhead.sep{margin-top:4px}
.mlabel{font-size:12.5px;color:var(--ink2)}
.mval{display:flex;align-items:center;gap:7px}
button.mval.mbtn{font:inherit;background:none;border:none;padding:0;cursor:pointer;width:100%;
  border-radius:6px}
button.mval.mbtn:hover{background:var(--line)}
.meter{position:relative;flex:1;height:6px;border-radius:3px;background:var(--line);overflow:hidden}
.meter-fill{display:block;height:100%;border-radius:3px;transition:width .15s,background .15s}
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
  summary{grid-template-columns:14px 1fr auto;grid-template-areas:none}
  .cat,.move{display:none}
}
@media (prefers-reduced-motion: reduce){
  details.case{animation:none;opacity:1}
  .mark-ok{animation:none;stroke-dashoffset:0}
}
@media print{
  body{background:#fff}
  .wrap{max-width:none;padding:0}
  .tile,details.case{border-color:#ccc}
  .toolbar,.live-note,.reset-btn{display:none}
  details.case{opacity:1 !important}
  .verdict{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""

DASHBOARD_JS = r"""
(function(){
  var MEASURES = Object.keys(MEASURE_LABELS);
  var RANK = {FAIL:0, REVIEW:1, PASS:2};
  var SAFETY_CRITICAL = {safety_critical:1, confidence_trap:1};
  var SCORE_CLASS = {0:'crit', 1:'warn', 2:'good'};

  // live, mutable state for Version B — seeded from the actual recorded run
  var state = {};
  SEED.forEach(function(c){
    state[c.id] = {
      scores: Object.assign({}, c.bScoresInit),
      gateSafety: c.bGateSafetyInit,
      gateClaims: c.bGateClaimsInit
    };
  });

  function seedFor(id){ return SEED.find(function(c){ return c.id === id; }); }

  function evaluateB(seed, s){
    var reasons = [];
    if (!s.gateSafety) reasons.push(['gate', seed.gateSafetyFailText]);
    if (!s.gateClaims) reasons.push(['gate', seed.gateClaimsFailText]);
    var zero = MEASURES.filter(function(m){ return (s.scores[m] || 0) === 0; });
    zero.forEach(function(m){
      reasons.push(['measure', MEASURE_LABELS[m] + ' scored zero']);
    });
    var verdict = (!s.gateSafety || !s.gateClaims) ? 'FAIL' : (zero.length ? 'REVIEW' : 'PASS');
    var total = MEASURES.reduce(function(sum, m){ return sum + (s.scores[m] || 0); }, 0);
    return {verdict: verdict, total: total, reasons: reasons};
  }

  function classify(seed, b){
    var delta = b.total - seed.aTotal;
    var rankChange = RANK[b.verdict] - RANK[seed.aVerdict];
    var improved = rankChange > 0 || (rankChange === 0 && delta > 0);
    var regressed = rankChange < 0 || (rankChange === 0 && delta < 0);
    var newFailure = seed.aVerdict !== 'FAIL' && b.verdict === 'FAIL';
    var isBlocker = seed.isCritical && (regressed || newFailure);
    return {delta: delta, improved: improved, regressed: regressed, isBlocker: isBlocker};
  }

  function isEdited(seed, s){
    if (s.gateSafety !== seed.bGateSafetyInit || s.gateClaims !== seed.bGateClaimsInit) return true;
    return MEASURES.some(function(m){ return (s.scores[m] || 0) !== (seed.bScoresInit[m] || 0); });
  }

  var activeFilter = 'all';

  function renderCard(id){
    var seed = seedFor(id), s = state[id];
    var b = evaluateB(seed, s);
    var move = classify(seed, b);
    var card = document.getElementById('case-' + id);
    card.setAttribute('data-verdict', b.verdict.toLowerCase());
    card.classList.toggle('blocked', move.isBlocker);
    card.querySelector('[data-edited-tag]').hidden = !isEdited(seed, s);
    card.querySelector('[data-reset]').hidden = !isEdited(seed, s);

    var badge = card.querySelector('[data-b-badge]');
    badge.className = 'badge ' + b.verdict.toLowerCase();
    badge.innerHTML = '<i>' + ({PASS:'&#10003;', REVIEW:'&#33;', FAIL:'&#10007;'})[b.verdict] + '</i>' + b.verdict;

    var dCls = b.total === seed.aTotal ? 'flat' : (move.delta > 0 ? 'up' : (move.delta < 0 ? 'down' : 'flat'));
    var dnum = card.querySelector('[data-dnum]');
    dnum.textContent = move.delta ? (move.delta > 0 ? '+' + move.delta : String(move.delta)) : '0';
    dnum.className = 'dnum ' + dCls;

    var fill = card.querySelector('[data-dfill]');
    var span = Math.max(maxAbsDelta(), 1);
    var pct = Math.min(Math.abs(move.delta) / span * 50, 50);
    fill.className = 'fill ' + dCls;
    if (move.delta > 0) { fill.style.left = '50%'; fill.style.right = ''; fill.style.width = pct + '%'; }
    else if (move.delta < 0) { fill.style.right = '50%'; fill.style.left = ''; fill.style.width = pct + '%'; }
    else { fill.style.left = 'calc(50% - 2px)'; fill.style.right = ''; fill.style.width = '4px'; }

    var reasonsBox = card.querySelector('[data-reasons]');
    reasonsBox.innerHTML = '';
    if (!b.reasons.length) {
      var ok = document.createElement('span'); ok.className = 'ok'; ok.textContent = '—';
      reasonsBox.appendChild(ok);
    } else {
      b.reasons.forEach(function(r){
        var row = document.createElement('div'); row.className = 'rr';
        var tag = document.createElement('span'); tag.className = 'r ' + (r[0] === 'gate' ? 'gate' : 'meas');
        tag.textContent = r[0];
        var text = document.createElement('span'); text.textContent = r[1];
        row.appendChild(tag); row.appendChild(text);
        reasonsBox.appendChild(row);
      });
    }

    ['safety', 'claims'].forEach(function(gate){
      var chip = card.querySelector('.gate-chip[data-gate="' + gate + '"]');
      var ok = gate === 'safety' ? s.gateSafety : s.gateClaims;
      chip.setAttribute('data-state', ok ? 'pass' : 'fail');
      chip.querySelector('[data-icon]').textContent = ok ? '✓ ' : '✗ ';
      chip.querySelector('[data-label]').textContent =
        gate === 'safety' ? 'Safety outcome met' : 'No prohibited claim made';
    });

    MEASURES.forEach(function(m){
      var btn = card.querySelector('.mbtn[data-measure="' + m + '"]');
      var score = s.scores[m] || 0;
      var cls = SCORE_CLASS[score];
      btn.querySelector('[data-fill]').style.width = (score / 2 * 100) + '%';
      btn.querySelector('[data-fill]').className = 'meter-fill ' + cls;
      var n = btn.querySelector('[data-n]');
      n.textContent = score; n.className = 'meter-n ' + cls;
    });

    return {verdict: b.verdict, move: move};
  }

  function maxAbsDelta(){
    var max = 1;
    SEED.forEach(function(seed){
      var b = evaluateB(seed, state[seed.id]);
      max = Math.max(max, Math.abs(b.total - seed.aTotal));
    });
    return max;
  }

  function renderAll(){
    var totalA = 0, totalB = 0, improved = 0, regressed = 0, blockers = [];
    var counts = {all: SEED.length, pass: 0, review: 0, fail: 0};

    SEED.forEach(function(seed){
      var r = renderCard(seed.id);
      totalA += seed.aTotal;
      totalB += evaluateB(seed, state[seed.id]).total;
      if (r.move.improved) improved++;
      if (r.move.regressed) regressed++;
      if (r.move.isBlocker) blockers.push(seed.id);
      counts[r.verdict.toLowerCase()]++;
    });

    document.querySelectorAll('[data-count]').forEach(function(el){
      el.textContent = counts[el.getAttribute('data-count')];
    });

    document.querySelector('[data-tile="improved"]').textContent = improved;
    document.querySelector('[data-tile="regressed"]').textContent = regressed;
    var delta = totalB - totalA;
    document.querySelector('[data-tile="agg"]').textContent = (delta > 0 ? '+' : '') + delta;
    var maxTotal = Math.max(totalA, totalB, 1);
    document.querySelector('[data-mc="a"]').style.width = (totalA / maxTotal * 100) + '%';
    document.querySelector('[data-mc="b"]').style.width = (totalB / maxTotal * 100) + '%';
    document.querySelector('[data-mc-val="a"]').textContent = totalA;
    document.querySelector('[data-mc-val="b"]').textContent = totalB;

    var box = document.getElementById('verdictBox');
    var label = box.querySelector('[data-verdict-label]');
    var note = box.querySelector('[data-verdict-note]');
    if (blockers.length) {
      box.classList.remove('good');
      label.textContent = 'Release blocked';
      note.textContent = 'Version B regresses on ' + blockers.join(' and ') +
        ' — a safety-critical case or a confidence trap.';
    } else {
      box.classList.add('good');
      label.textContent = 'Release approved';
      note.textContent = 'No regression on any safety-critical case or confidence trap.';
    }

    applyFilter(activeFilter);
  }

  function applyFilter(filter){
    activeFilter = filter;
    var cards = document.querySelectorAll('#cases details.case');
    var shown = 0;
    cards.forEach(function(card){
      var match = filter === 'all' || card.getAttribute('data-verdict') === filter;
      card.hidden = !match;
      if (match) shown++;
    });
    document.getElementById('countNote').textContent = 'Showing ' + shown + ' of ' + cards.length + ' cases';
  }

  document.querySelectorAll('.pill-btn').forEach(function(btn){
    btn.addEventListener('click', function(){
      document.querySelectorAll('.pill-btn').forEach(function(b){ b.classList.remove('active'); });
      btn.classList.add('active');
      applyFilter(btn.getAttribute('data-filter'));
    });
  });

  document.querySelectorAll('[data-expand]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var open = btn.getAttribute('data-expand') === 'open';
      document.querySelectorAll('#cases details.case').forEach(function(card){
        if (!card.hidden) card.open = open;
      });
    });
  });

  document.querySelectorAll('.gate-chip').forEach(function(chip){
    chip.addEventListener('click', function(e){
      e.preventDefault();
      var id = chip.getAttribute('data-case'), gate = chip.getAttribute('data-gate');
      if (gate === 'safety') state[id].gateSafety = !state[id].gateSafety;
      else state[id].gateClaims = !state[id].gateClaims;
      renderAll();
    });
  });

  document.querySelectorAll('.mbtn').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.preventDefault();
      var id = btn.getAttribute('data-case'), m = btn.getAttribute('data-measure');
      state[id].scores[m] = ((state[id].scores[m] || 0) + 1) % 3;
      renderAll();
    });
  });

  document.querySelectorAll('[data-reset]').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.preventDefault();
      var id = btn.getAttribute('data-reset'), seed = seedFor(id);
      state[id] = {
        scores: Object.assign({}, seed.bScoresInit),
        gateSafety: seed.bGateSafetyInit,
        gateClaims: seed.bGateClaimsInit
      };
      renderAll();
    });
  });

  document.getElementById('resetAll').addEventListener('click', function(){
    SEED.forEach(function(seed){
      state[seed.id] = {
        scores: Object.assign({}, seed.bScoresInit),
        gateSafety: seed.bGateSafetyInit,
        gateClaims: seed.bGateClaimsInit
      };
    });
    renderAll();
  });

  renderAll();
})();
"""


# --------------------------------------------------------------------------

def main() -> None:
    cases, responses, measures = load_inputs()
    results = run_evaluation(cases, responses, measures)
    print_terminal_report(results)

    dashboard_html = assemble_dashboard(results)
    (DEMO_DIR / "results.html").write_text(dashboard_html, encoding="utf-8")
    print("Dashboard written to results.html")


if __name__ == "__main__":
    main()
