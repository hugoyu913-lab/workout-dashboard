# Codex ↔ Claude Review Loop

Goal:
Codex makes targeted code changes.
Claude reviews for bugs, UX issues, architecture problems, and hidden regressions.
Codex applies fixes only after review.

## Loop Rules

1. Codex edits first.
2. Codex runs verification:
   python -m py_compile app.py src/coach.py src/sheets_client.py src/pages/dashboard.py
3. Codex outputs:
   - changed files
   - diff summary
   - verification result
   - review prompt for Claude
4. User pastes review prompt into Claude.
5. Claude reviews only the diff, not the whole repo.
6. User pastes Claude feedback back into Codex.
7. Codex fixes only confirmed issues.
8. Codex reruns verification.
9. Codex shows final diff summary.
10. User approves commit.

## Codex Output Template

After any code change, Codex must output:

Changed files:
-

Verification:
-

Claude review prompt:

```text
You are reviewing changes in workout-dashboard.

Goal:
[brief task goal]

Changed files:
[paste changed files]

Diff summary:
[paste git diff --stat]

Full diff:
[paste git diff]

Review for:
- bugs
- broken imports
- Streamlit UI regressions
- Google Sheets column alignment issues
- checkin parsing issues
- hidden logic regressions
- overcomplicated code

Do not rewrite everything.
Return only:
1. Must fix
2. Should fix
3. Safe to commit?
