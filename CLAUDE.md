# CLAUDE.md

## How to talk to me

Talk like explaining to caveman. Short words. Simple sentences.
No jargon. If must use technical word, explain it after.
Put all summaries in a table. Always.
When done with task, say "UGH. DONE." at end.

---

## What app does

Workout dashboard. Reads workout logs from Google Sheets. Shows charts, grades, and coaching advice.
Three pages: Coach, Dashboard, Grades.

Coach page = smart advice. Tells you what to train today, how recovered you are, if you are eating enough.
Dashboard page = charts for volume, weight trends, muscle group breakdown.
Grades page = grades each workout session based on sets, reps, weight.

User logs workouts in Google Sheets (one tab per muscle split). User logs daily checkins (weight, calories, protein, sleep, energy, soreness, stress) in a tab called "checkins".

---

## Folder structure

```
workout-dashboard/
├── app.py                  ← main entry point, routes to pages
├── config/
│   └── profile.py          ← YOUR personal constants (targets, split, anchor lifts)
├── src/
│   ├── sheets_client.py    ← reads/writes Google Sheets
│   ├── cleaner.py          ← cleans raw workout data
│   ├── metrics.py          ← computes checkin metrics and session grades
│   ├── coach.py            ← all Coach page logic and rendering
│   ├── fatigue.py          ← detects overtraining risk
│   ├── guardrails.py       ← safety checks (deload triggers, overload limits)
│   ├── insights.py         ← generates text insights
│   ├── recommendations.py  ← exercise swap suggestions
│   ├── retention.py        ← strength retention tracking
│   ├── charts.py           ← reusable chart helpers
│   └── pages/
│       ├── dashboard.py    ← Dashboard page rendering
│       └── grades.py       ← Grades page rendering
├── .streamlit/
│   └── config.toml         ← theme and server settings
└── requirements.txt        ← pinned dependencies
```

---

## Key files

| File | What it does |
|------|-------------|
| `app.py` | Starts the app. Loads data from Google Sheets. Routes to Coach / Dashboard / Grades. |
| `config/profile.py` | Your personal numbers: calorie target, protein target, training split, anchor lifts, cut rate targets. Change these to match your goals. |
| `src/sheets_client.py` | Connects to Google Sheets. Reads workout tabs. Reads and writes the checkins tab. |
| `src/coach.py` | The big one. Computes readiness, game plan, warnings, weekly review. Renders the whole Coach page including the checkin form. |
| `src/metrics.py` | Turns raw checkin rows into numbers (avg sleep, energy, protein). Grades workout sessions. |
| `src/fatigue.py` | Looks at recent sessions and decides if fatigue risk is low / medium / high. |
| `src/cleaner.py` | Fixes dates, removes bad rows, standardises exercise names. |
| `src/pages/dashboard.py` | Renders volume charts, weight trend, muscle group frequency. |
| `src/pages/grades.py` | Renders session grade cards and history. |

---

## Profile constants (change these to match your goals)

File: `config/profile.py`

| Constant | What it controls |
|----------|-----------------|
| `TARGET_REPS_MIN / MAX` | Rep range you train in (default 6–8) |
| `TARGET_SETS` | Target sets per exercise (default 2) |
| `TARGET_RIR` | Reps in reserve target (default 1) |
| `TRAINING_DAYS_PER_WEEK` | How many sessions per week (default 5.5) |
| `PHASE` | Current goal: `"cut"`, `"bulk"`, or `"maintain"` |
| `TRAINING_SPLIT` | Which muscle groups each day of the week |
| `ANCHOR_LIFTS` | Key lifts tracked for strength retention |
| `DAILY_*_TARGET` | Daily targets for steps, calories, protein, carbs, fat, sleep |
| `CUT_RATE_MIN / MAX` | Acceptable weekly weight loss range (as fraction of bodyweight) |

---

## How to run locally

```bash
streamlit run app.py
```

App opens at http://localhost:8501.

Need `credentials.json` in the project root (Google service account key file).
Or set `[gcp_service_account]` in `.streamlit/secrets.toml`.

The Google service account must have editor access to the spreadsheet.

---

## How to verify changes before committing

```bash
# Check Python syntax — no errors means safe to commit
python -m py_compile app.py src/coach.py src/sheets_client.py

# Check all src files at once
(Get-ChildItem src -Filter *.py).FullName | ForEach-Object { python -m py_compile $_ }
```

Then commit:

```bash
git add <files>
git commit -m "short description"
git push
```
