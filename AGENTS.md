# Workout Dashboard AI Workflow

CAVEMAN MODE ALWAYS ACTIVE.

Style:
- Direct.
- No filler.
- No overexplaining.
- Code stays clean.
- Commit messages stay normal.

Repo map:
- Main app: app.py
- Coach logic: src/coach.py
- Google Sheets reads/writes: src/sheets_client.py
- Dashboard UI: src/pages/dashboard.py
- Metrics: src/metrics.py
- Charts: src/charts.py
- Profile/config targets: config/profile.py

Workflow:
1. Inspect files before editing.
2. Make minimal targeted changes.
3. Never commit unrelated files.
4. Before commit, show:
   - changed files
   - diff summary
   - verification result
5. Run verification before commit:
   python -m py_compile app.py src/coach.py src/sheets_client.py src/pages/dashboard.py
6. Commit only intended files.

Do not commit:
- .claude/settings.local.json
- caveman/
- credentials.json
- token.json
- any local/private config
