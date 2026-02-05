# TradingAgent Pre-Commit Checklist

Before pushing code to production, **always run**:

```bash
./pre-commit-check.sh
```

## What it checks:

1. **Python Syntax**: Compiles all Python files to catch syntax errors
2. **Import Validation**: Ensures all modules can be imported without errors
3. **Unit Tests**: Runs `verify_strategy.py` to validate strategy logic

## Manual Alternative:

If you prefer to run checks manually:

```bash
# 1. Syntax check
python3 -m py_compile broker_dhan.py ranking_engine.py server.py

# 2. Import check
python3 -c "import broker_dhan; import ranking_engine; import server"

# 3. Run tests
python3 verify_strategy.py
```

## Git Hook (Optional):

To automatically run checks before every commit, create `.git/hooks/pre-commit`:

```bash
#!/bin/bash
./pre-commit-check.sh
```

Then make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

This will **block commits** if validation fails.
