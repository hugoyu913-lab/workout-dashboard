# Workout Analytics Dashboard

Streamlit dashboard for a Google Sheets workout log. It pulls every worksheet in the workbook, parses the current block-style workout format, cleans the rows, and reports volume, estimated 1RM, PRs, workout frequency, top exercises, and muscle group trends.

The dashboard includes a local rule-based weekly insight panel tuned for high-intensity cutting: exercise progression scores, progressing/stalled/declining status flags, muscle-group frequency gaps, fatigue/regression warnings, weekly training score, push/pull/legs balance, and next-week focus suggestions. It also shows muscle group frequency by counting unique workout dates per muscle group in the selected date range, plus a daily workout detail view for inspecting the exact exercises, sets, loads, reps, volume, muscle groups, categories, and source sheet for a selected date. It does not call an AI/API service.

The project also includes Apple Health export parsing. A local `data/export.xml` can be converted into daily CSVs under `data/health/` for correlation analysis with training data.

## Setup

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Enable the Google Sheets API in Google Cloud.
3. Create a service account and download its JSON key.
4. Place the key at `config/credentials.json` or `credentials.json`.
5. Share the spreadsheet with the service account email using Viewer access.

The default spreadsheet ID is:

```text
1-45dvx4NOmyAOg8fDBL4_525NMXhCuEcSk_eaf9v9AI
```

The active local service account email is:

```text
workout-dashboard@workout-dashboard-494506.iam.gserviceaccount.com
```

You can override the spreadsheet ID with the sidebar field or an environment variable:

```powershell
$env:WORKOUT_SPREADSHEET_ID="your-spreadsheet-id"
```

## Streamlit Secrets

For deployment, use Streamlit secrets instead of a local credentials file:

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

Do not commit `config/credentials.json`, `credentials.json`, `.streamlit/secrets.toml`, or private health exports.

## Run

```powershell
streamlit run app.py
```

Optional Apple Health preprocessing:

```powershell
python scripts\parse_health.py
```

This expects `data/export.xml` and writes daily metric CSVs into `data/health/`.

## Expected Workout Data

The Google Sheets parser expects each workout session to begin with a block header row where columns 2 and 3 are `Weight` and `Reps`. The first column should contain a workout name and date, such as `Upper C 4/21`.

The cleaner standardizes the final dataframe to:

```text
Date, Workout, Exercise, MuscleGroup, Category, Set, Weight, Reps, Volume, SourceSheet
```

It accepts common aliases such as `movement`, `lift`, `lbs`, `load`, `rep`, and `total volume`. Blank rows are ignored. If an exercise name appears once and following set rows omit it, the dashboard forward-fills the exercise so those rows are counted under the same movement.

Exercise names are standardized case-insensitively from `config/exercise_map.csv`, which supports:

```text
raw_name, standard_name, muscle_group, category
```

Older two-column maps with only `raw_name` and `standard_name` still work. Missing muscle groups fall back to the built-in map, and missing categories default to `strength`.

## Current Notes

- Google Sheets auth lookup order is Streamlit secrets, `config/credentials.json`, then `credentials.json`.
- `PROJECT_SUMMARY.md` contains the full project inventory, current features, known issues, and recommended upgrades.
- The current app code has an Apple Health integration mismatch: `app.py` imports `render_uploader`, but `src/apple_health.py` currently defines `render_sidebar_widget()`. Fix that before relying on the Correlations page.
