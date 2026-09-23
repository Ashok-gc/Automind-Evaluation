# AutoMind evaluation harness — proof of concept

Group B, University of Leeds. Built to accompany the final consultancy report.

**All data here is synthetic.** The cases and the two sets of responses were written
by us for demonstration. No AutoMind customer data was used.

## Watch it

A short walkthrough of the dashboard — what it shows, why the release is blocked
despite Version B's higher average score, and what it actually takes to clear
both regressions: **https://youtu.be/-IKyIetqinE**

## What it does

It runs a held-out library of known diagnostic cases against two versions of a
system, then reports what improved, what regressed, and what newly failed.

## Run it

    python3 evaluate.py

No dependencies beyond the Python standard library. It prints a report to the
terminal and (re)writes `results.html`.

You don't need to run anything to look at the result: `results.html` is already
included and up to date. Just open it in a browser — it's a single file with no
external scripts, fonts, or network calls, so it works offline too.

## Using the dashboard

`results.html` is interactive, and the scoring is genuinely live — not just
click-to-reveal. Everything in it recomputes in the browser using the same
rules `evaluate.py` applies:

- **Filter** by verdict (All / Pass / Review / Fail) using the pills above the case list.
- **Click any case** to expand it — the full evidence (vehicle, fault codes or sensor
  trend, owner answers), what the case requires, Version B's actual response, why it
  scored the way it did, and a side-by-side score for every rubric measure.
- **Try a different score or gate.** Every measure and gate for Version B is
  clickable. Click a gate chip to flip it, or a measure meter to cycle its score
  (0 → 1 → 2), and watch the case's verdict, the reasons, the release banner and
  the four summary tiles all update immediately — this is the actual decision
  rule running, not a canned animation. "Reset this case" / "Reset all" puts it
  back to the real recorded run.
- **Expand all / Collapse all** if you want to read every case at once.

Nothing you change in the browser is saved anywhere — it's a sandbox for asking
"what if this had scored differently," not an edit to the underlying data.
Refreshing the page always returns to the actual result.

## Files

| File | What it is |
|---|---|
| `cases.json` | The case library. Eight cases across the six categories Matt identified, plus two we added for phase 2: benign drift and slow true positives. |
| `rubric.json` | Two gates and five measures, with the pass / review / fail conditions. |
| `responses.json` | Two synthetic versions of the system's answer to each case. Version B contains deliberate regressions. |
| `evaluate.py` | The harness. Scores both versions against the library and generates the dashboard below. |
| `results.html` | The interactive dashboard the harness produces — open this one directly. |

## What the demo run shows

Version B improves on five of the eight cases and its aggregate score goes **up**
by four points. It also breaks the brake-fault case, downgrading "do not drive" to
"book in when convenient", and it breaks the confidence trap by recommending a new
catalytic converter when the owner has just had exhaust work done.

A team watching the average would have shipped it.

That is the whole argument. Aggregate accuracy is the wrong number to watch. The
question is never whether a change is better on average, but what it broke.

Try it yourself in the dashboard: fixing a case's gates alone isn't enough to
clear it — the badge can flip to PASS while the case's total score is still
below what the approved version scored, and it will still count as a
regression. Only once a case's score is brought back up to at least parity does
it stop blocking release. Fix both C-005 and C-006 that way and the banner
flips to "Release approved."
