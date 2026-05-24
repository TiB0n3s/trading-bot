# Refactor Safety Checklist

Use this before any non-trivial trading-bot code change.

## Repo State

```bash
cd ~/trading-bot
git branch --show-current
git status --short
git log --oneline -5
Proceed only when the branch is intentional and the working tree is clean or all changes are understood.

Before Editing
Inspect the target file before changing it.
Confirm the exact function or pattern exists.
Back up non-trivial files before editing.
Avoid broad blind replacements.
Avoid whole-file rewrites unless explicitly required.
Keep one logical change per commit.
Validation

Run compile checks on touched Python files:

python3 -m py_compile app.py broker.py db.py decision_engine.py ops_check.py

Run targeted checks when relevant:

python3 ops_check.py status
python3 ops_check.py trends

Run tests when available:

python3 -m pytest tests -q
Review

Before committing:

git diff --check
git diff --stat
git diff

Never commit:

/etc/trading-bot.env
secrets
trades.db
*.db
pycache
random backup files
large logs
Pre-Market Rule

Do not make structural signal-path, broker, database, or state-manager refactors late the day before market open unless fixing a confirmed production-blocking bug.
