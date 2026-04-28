# Project Summary

## What The App Does

This is a Streamlit workout analytics dashboard backed by a Google Sheets workout log. It reads every worksheet in a spreadsheet, parses a block-style workout log into a tidy dataframe, cleans and normalizes workout rows, then visualizes training volume, workout frequency, exercise PRs, estimated one-rep maxes, and muscle group volume.

Lifestyle, recovery, nutrition, and readiness data come from the Google Sheets `Checkins` tab.

## Current Folder And File Structure

```text
workout-dashboard/
  .claude/
    settings.local.json
  .streamlit/
    config.toml
  config/
    exercise_map.csv
    exercise_recommendations.csv
  scripts/
    setup_checkins.py
  src/
    __init__.py
    charts.py
    cleaner.py
    coach.py
    insights.py
    metrics.py
    sheets_client.py
  app.py
  credentials.json
  README.md
  requirements.txt
  test_auth.py
```

Generated Python cache folders (`__pycache__/`) are present locally and are ignored by git. The local Google service account key is currently at `credentials.json`; the app also supports `config/credentials.json`.

## Google Sheets Auth

Google Sheets access is implemented in `src/sheets_client.py` with `gspread` and `google.oauth2.service_account.Credentials`.

Auth lookup order:

1. Streamlit secrets under `[gcp_service_account]`.
2. Local `config/credentials.json`.
3. Local legacy fallback `credentials.json`.

The app requests the read-only Sheets scope:

```text
https://www.googleapis.com/auth/spreadsheets.readonly
```

The Google Sheet must be shared with the service account email, usually with Viewer access. If credentials are missing, the app raises a `GoogleSheetsError`. If the spreadsheet is not shared with the service account, `gspread` raises a spreadsheet access error that is converted into a dashboard-facing message.

`test_auth.py` is a standalone local auth check that currently reads `credentials.json`, authenticates with `gspread.service_account`, and tries to open the default sheet.

## Spreadsheet ID And Active Service Account

Default spreadsheet ID:

```text
1-45dvx4NOmyAOg8fDBL4_525NMXhCuEcSk_eaf9v9AI
```

The app uses that ID by default through `DEFAULT_SPREADSHEET_ID` in `src/sheets_client.py`. It can be overridden in the Streamlit sidebar or by setting:

```powershell
$env:WORKOUT_SPREADSHEET_ID="your-spreadsheet-id"
```

Active local service account email from `credentials.json`:

```text
workout-dashboard@workout-dashboard-494506.iam.gserviceaccount.com
```

Project ID from the same credentials file:

```text
workout-dashboard-494506
```

## How To Run The App

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run the Streamlit dashboard:

```powershell
streamlit run app.py
```

## Current Working Features

- Google Sheets client with Streamlit secrets support and local service-account JSON fallback.
- Coach page is the first navigation item. It provides a deterministic daily cutting checklist with a Today's Priority and confidence card, readiness scoring, today's lifestyle targets, a Monday-anchored split rotation tracker, muscle-group frequency cards, a recommended custom split or Recovery focus, progressive overload targets for 2-set 6-8 rep work, weekly progress bars, and warning/action cards.
- Workbook-wide worksheet loading through `gspread`.
- Parsing of the current block-header sheet format where each session starts with a row like `Workout Date | Weight | Reps`.
- Bare `m/d` date handling with inferred year rollovers.
- Workout log cleaning and normalization into:

```text
Date, Workout, Exercise, MuscleGroup, Category, Set, Weight, Reps, Volume, SourceSheet
```

- Numeric cleanup for weight, reps, set, and volume fields.
- Forward fill for dates, workouts, and exercises where set rows omit repeated values.
- Case-insensitive exercise alias standardization from `config/exercise_map.csv`.
- Muscle group and category classification from `config/exercise_map.csv`, with built-in muscle group fallback.
- Dashboard filters for date range, muscle group, exercise, and source sheet.
- KPI cards for total volume, workouts, logged sets, and exercise count.
- Charts for weekly volume, workout frequency, top exercises, estimated 1RM, muscle group volume, weekly muscle group heatmap, and PR timeline.
- Rule-based weekly insight panel tuned for high-intensity cutting: progression scores, progressing/stalled/declining exercise flags, muscle-group frequency gaps, fatigue/regression warnings, weekly training score, custom split balance, and suggested focus for the next week. This is local deterministic logic, not an API call.
- Strength Retention Score section that classifies recent repeated exercises as `Improved`, `Maintained`, or `Regressed` across the last 2-3 weeks and normalizes the result to a 0-100 score, with configured anchor lifts weighted more heavily.
- Fatigue Risk Detector that flags same-weight rep drops, repeated regressions in the same muscle group, and weeks above the normal 5-6 training sessions, then returns `Low`, `Moderate`, or `High` risk with reasons and a suggested action. Anchor lift regressions are treated as higher-priority fatigue signals.
- Suggested Exercises module backed by `config/exercise_recommendations.csv`; it recommends 2-3 high-priority movements per affected muscle group for frequency gaps, regressions, and recovery-sensitive substitutions.
- Next Workout Recommendation module that combines weekly insights, fatigue risk, strength retention, frequency gaps, and suggested exercises to choose a deterministic custom split or Recovery session.
- Optional `Checkins` Google Sheet tab support for bodyweight, calories, protein, carbs, fat, steps, sleep, energy, soreness, stress, deload flags, and notes. Checkins feeds 7-day bodyweight average, weekly weight-loss rate, nutrition guardrails, Coach readiness inputs, daily targets, lifestyle summaries, and recovery warnings.
- `scripts/setup_checkins.py` creates the `Checkins` worksheet if missing and appends any missing required headers without overwriting existing daily rows.
- Bodyweight & Recovery includes 30-day Checkins charts for steps vs 10k goal, sleep vs 8h target, and macro adherence for protein/carbs/fat.
- Muscle group frequency section that counts unique workout dates per muscle group in the active sidebar-filtered date range and displays both a table and bar chart.
- Daily workout detail section with a workout date selector, daily summary metrics, and an exact per-set table for `Exercise`, `Set`, `Weight`, `Reps`, `Volume`, `MuscleGroup`, `Category`, and `SourceSheet`.
- Workout comparison section that compares each selected-day exercise against its most recent previous occurrence and flags `Improved`, `Same`, or `Regressed`.
- Grades page has a selectable session feedback system: grade/score breakdown, what went well, what needs improvement, next-session adjustment, best/weakest lift, previous-session comparison, and per-exercise drilldown with status vs previous occurrence.
- Data tables for volume by exercise, PR tracker, and filtered raw rows.
- Dark Streamlit theme in `.streamlit/config.toml` plus custom CSS in `app.py`.

## Known Issues Or Limitations

- `README.md` previously documented only `config/credentials.json`, but the current local key is `credentials.json`. Both are supported by the app.
- `config/exercise_map.csv` now drives exercise standardization, muscle groups, and categories, but unmapped exercises still depend on the built-in fallback map or become `other`.
- The repository currently contains local data and credential files. `.gitignore` excludes credentials, secrets, virtual environments, and Python cache folders, but already-present local files should still be handled carefully.
- No automated test suite is present. `test_auth.py` is a manual connectivity check, not a pytest-style test.
- Bare `m/d` date year inference starts from the current year minus one and increments on large backward month/day jumps. This is practical for a continuous log but may be wrong for unusual sheet ordering or older historical imports.
- Estimated 1RM uses the Epley formula and depends on valid weight and rep entries.
- Muscle group coverage depends on exact normalized exercise names. Unknown exercises are grouped as `other`.

## Recommended Next Upgrades

1. Continue expanding `config/exercise_map.csv` as new aliases appear in the workout log.
2. Add a small pytest suite for sheet parsing, cleaning, metric calculations, Coach readiness, and grade feedback.
3. Add a startup health check that reports which auth source is active and whether the current spreadsheet is reachable.
4. Add a sample sanitized workbook or fixture data so the dashboard can be tested without private Google Sheets access.
5. Add data validation warnings for unknown exercises, missing dates, nonnumeric weights/reps, and unusually high volumes.
6. Add deployment notes for Streamlit Community Cloud or another host using `[gcp_service_account]` secrets.
7. Add export/download options for cleaned workout data and computed PR tables.
