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
