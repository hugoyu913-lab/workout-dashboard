# Free Codex ↔ Claude Review Loop

No API credits required.

## Workflow

1. Codex makes code changes.
2. Codex writes a Claude review prompt into:
   ai_loop/review_prompt.txt
3. User copies review_prompt.txt into Claude web/app.
4. User pastes Claude feedback into:
   ai_loop/claude_feedback.txt
5. Codex reads claude_feedback.txt.
6. Codex applies only Must Fix items.
7. Codex reruns:
   python -m py_compile app.py src/coach.py src/sheets_client.py src/pages/dashboard.py
8. Codex shows final diff.
9. User approves commit.

## Rules

- No API usage.
- No paid credits.
- Do not auto-commit after review.
- Apply only Must Fix items unless user approves Should Fix.
- Keep commits scoped.
- Never commit private/local files.

## Auto-Trigger Review Loop

After making changes, classify risk:

LOW RISK:
- copy/text changes
- simple UI label changes
- comments/docs only
- one-line visual changes

Action:
- run verification if code changed
- no Claude loop required
- ask user before commit

MEDIUM RISK:
- changes to one logic file
- changes to Streamlit UI behavior
- changes to data display
- changes to checkin form fields
- small refactors

Action:
- auto-trigger no-API review loop
- write Claude prompt to ai_loop/review_prompt.txt
- do not commit until feedback is handled or user skips review

HIGH RISK:
- multi-file logic changes
- Google Sheets read/write changes
- metrics.py changes
- coach.py decision logic changes
- checkin parsing changes
- authentication/credentials changes
- anything that could corrupt sheet data

Action:
- auto-trigger no-API review loop
- require Claude feedback before commit
- apply only Must Fix items
- rerun verification after fixes

Default:
If unsure, treat as MEDIUM RISK.
