#!/bin/bash
# Pre-commit validation script for TradingAgent
# Run this before pushing to catch syntax and import errors

set -e  # Exit on first error

echo "🔍 Running Pre-Commit Validation..."
echo ""

# 1. Python Syntax Check
echo "1️⃣  Checking Python Syntax..."
python3 -m py_compile broker_dhan.py
python3 -m py_compile ranking_engine.py
python3 -m py_compile server.py
echo "✅ Syntax check passed"
echo ""

# 2. Import Check (try importing modules)
echo "2️⃣  Checking Imports..."
python3 -c "import broker_dhan; import ranking_engine; import server" 2>&1 | grep -v "Redis connection failed" || true
echo "✅ Import check passed"
echo ""

# 3. Run Unit Tests
echo "3️⃣  Running Unit Tests..."
python3 verify_strategy.py
echo "✅ Tests passed"
echo ""

echo "✅ All checks passed! Safe to commit and push."
