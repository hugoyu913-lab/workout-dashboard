# Workout Analytics Dashboard

Streamlit dashboard backed by a Google Sheets workout log. Reads every worksheet, parses the block-style session format, and reports volume, estimated 1RM, PRs, frequency, muscle-group trends, fatigue risk, strength retention, session quality, cut guardrails, and next-workout recommendations — all locally, no AI API calls.

The optional `Checkins` Google Sheet tab adds bodyweight trend (7-day rolling average), cut-pace classification, recovery signal tracking, and feeds the Cut Guardrails composite risk banner.

The first page is **Coach**, a daily cutting-phase action plan. It combines Checkins recovery data, steps, nutrition, weekly muscle frequency, anchor-lift strength retention, cut pace, and the Monday-anchored custom split rotation into a deterministic Today's Priority card, readiness score, daily target checklist, workout focus, exercise targets, weekly progress tracker, and warning/action cards.

The **Grades** page explains individual session grades. Select any logged workout date to see the grade, category score breakdown, what went well, what needs work, a cut-phase adjustment for next time, previous-session comparisons, and a per-exercise drilldown with status vs. the exercise's previous occurrence.

---

## Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Place your service-account key at `config/credentials.json` (or the legacy `credentials.json`), then share the spreadsheet with the service-account email using Viewer access.

Override the spreadsheet ID with the sidebar input or:

```bash
export WORKOUT_SPREADSHEET_ID="your-spreadsheet-id"   # macOS/Linux
$env:WORKOUT_SPREADSHEET_ID="your-spreadsheet-id"     # PowerShell
```

---

## Deploy to Streamlit Cloud

### 1 — Push this repo to GitHub

```bash
git push origin main
```

### 2 — Create the app on streamlit.io

1. Go to **https://share.streamlit.io** and sign in.
2. Click **New app**.
3. Select your GitHub repo, branch `main`, and set **Main file path** to `app.py`.
4. Click **Deploy**.

### 3 — Add your Google credentials as a secret

In the Streamlit Cloud dashboard, open your app → **⋮ (three dots) → Settings → Secrets**.

Paste the following, replacing each value with the fields from your `credentials.json`:

```toml
[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "the-key-id-field"
private_key = "-----BEGIN PRIVATE KEY-----\nPASTE_YOUR_PRIVATE_KEY_HERE\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "the-numeric-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account%40your-project.iam.gserviceaccount.com"
```

> **Private key formatting:** the `private_key` value must keep the `\n` escape sequences on a single line — do **not** paste literal newlines inside the TOML string. Copy the `private_key` field exactly as it appears in the JSON file (it already contains `\n`).

Click **Save**. Streamlit Cloud will restart the app automatically.

---

## Google Sheets Setup

1. Enable the **Google Sheets API** in your Google Cloud project.
2. Create a **Service Account**, then generate a JSON key.
3. **Share** your spreadsheet with the service-account `client_email` (Viewer access is enough).

Default spreadsheet ID (change in the sidebar or via env var):

```
1-45dvx4NOmyAOg8fDBL4_525NMXhCuEcSk_eaf9v9AI
```

---

## Auth Lookup Order

The app resolves credentials in this priority:

1. `st.secrets["gcp_service_account"]` — used in production on Streamlit Cloud.
2. `config/credentials.json` — local development.
3. `credentials.json` (repo root) — legacy local fallback.

---

## Checkins Tab (optional)

Add a Google Sheet tab named exactly **`Checkins`** with these columns:

```
Date | Bodyweight | Calories | Protein | Carbs | Fat | Steps | SleepHours | Energy | Soreness | Stress | Deload | Notes
```

- Numeric: `Bodyweight`, `Calories`, `Protein`, `Carbs`, `Fat`, `Steps`, `SleepHours`, `Energy`, `Soreness`, `Stress`.
- `Date` can be any parseable date, `Deload` accepts `TRUE`/`FALSE`, and `Notes` is preserved as text.
- `Deload = TRUE` suppresses fatigue and regression warnings for that entire week.

If the tab is absent, the dashboard shows placeholder cards and continues normally. Add the Checkins tab to unlock daily readiness, lifestyle targets, recovery summaries, nutrition guardrails, and cut pace tracking.

To create or update the tab headers without overwriting existing rows:

```bash
python scripts/setup_checkins.py
```

The Coach page uses daily targets from `config/profile.py`: 10,000 steps, 2,200 calories, 180g protein, 180g carbs, 60g fat, and 8h sleep. The Bodyweight & Recovery section also charts 30-day steps, sleep, and macro adherence from Checkins.

---

## Coach Split Rotation

Coach follows the custom hybrid split in `config/profile.py`:

```
Mon: Chest + Back
Tue: Shoulders + Arms
Wed: Legs
Thu: Chest + Arms
Fri: Back + Shoulders
Sat: Legs
```

The rotation starts every Monday and only advances when the expected split is completed. Skipped days do not advance the rotation, so the next training day keeps the missed split as the expected workout. Today's Priority and Today's Game Plan prioritize that expected split unless readiness is below 30 or a severe fatigue/regression warning calls for recovery.

The Today's Priority card also shows an action tag (`Train`, `Train Smart`, `Recovery`, or `Log Checkins`) and a confidence level. Confidence is highest when today's Checkins row has sleep, energy, soreness, and stress filled and the split rotation is known; missing or partial checkins lower confidence.

---

## Workout Sheet Format

Each session starts with a block-header row where columns 2 and 3 are `Weight` and `Reps`:

```
Upper A 4/21  |  Weight  |  Reps
Bench Press   |  185     |  6
              |  185     |  6
              |  185     |  5
Row           |  135     |  8
```

The cleaner produces:

```
Date, Workout, Exercise, MuscleGroup, Category, Set, Weight, Reps, Volume, SourceSheet
```

Exercise names are standardised from `config/exercise_map.csv`. Unknown exercises fall back to a built-in map or become `other`.
