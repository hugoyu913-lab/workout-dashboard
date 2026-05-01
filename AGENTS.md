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

## No-API Review Loop

For medium or large code changes:
- Save Claude review prompt to ai_loop/review_prompt.txt.
- Wait for user to paste Claude feedback into ai_loop/claude_feedback.txt.
- Read claude_feedback.txt before fixing.
- Apply only Must Fix items.
- Do not use API calls or paid credits.
- Do not commit until user approves.

Do not commit:
- .claude/settings.local.json
- caveman/
- credentials.json
- token.json
- any local/private config
