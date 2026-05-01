# Free Codex ↔ Review Loop

No API credits required.

## Workflow

1. Codex makes code changes.
2. Codex writes a review prompt into:
   ai_loop/review_prompt.txt
3. User copies review_prompt.txt into Claude web/app, ChatGPT, or a manual reviewer workflow.
4. User pastes review feedback into:
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

## Reviewer Fallback

If Claude web/app is unavailable, out of tokens, or the user says Claude cannot review:
- Use ChatGPT/manual reviewer feedback instead.
- User may paste ChatGPT review into ai_loop/claude_feedback.txt.
- Treat it the same as Claude feedback.
- Apply only Must Fix items.
- Do not block progress if review is unavailable for LOW or simple MEDIUM risk changes.
- For HIGH risk changes, require either Claude, ChatGPT, or explicit user approval to skip review.

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
- write review prompt to ai_loop/review_prompt.txt
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
- require review feedback before commit
- apply only Must Fix items
- rerun verification after fixes

Default:
If unsure, treat as MEDIUM RISK.
