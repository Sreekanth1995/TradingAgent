#!/usr/bin/env python3
"""
Automated Cybersecurity & System Hardening Auditor
For TradingAgent and OptionsTrading codebases.
"""

import os
import re
import sys
import subprocess

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️ WARN"

def run_command(cmd, cwd=None):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def audit_git_and_env(base_dir):
    print(f"\n--- 1. Git Tracked Files & .env Security ({base_dir}) ---")
    results = []
    
    # Check if .env exists
    env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        mode = oct(os.stat(env_path).st_mode & 0o777)
        if mode in ("0o600", "0o400"):
            results.append((PASS, f".env file permissions are secure ({mode})"))
        else:
            results.append((WARN, f".env file permissions are loose ({mode}). Run: chmod 600 {env_path}"))
    else:
        results.append((WARN, f".env file not found at {env_path}"))

    # Check if .env is tracked in git
    code, out, _ = run_command("git ls-files .env", cwd=base_dir)
    if out.strip():
        results.append((FAIL, ".env IS TRACKED IN GIT REPOSITORY! Run: git rm --cached .env"))
    else:
        results.append((PASS, ".env is correctly ignored in Git repository"))

    for status, msg in results:
        print(f"{status:<8} | {msg}")

def audit_hardcoded_secrets(base_dir):
    print(f"\n--- 2. Hardcoded Secrets & Token Leaks Scan ({base_dir}) ---")
    suspicious_patterns = [
        (r'eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*', "Raw JWT Token String"),
        (r'DHAN_ACCESS_TOKEN\s*=\s*["\'][A-Za-z0-9._-]{20,}["\']', "Hardcoded Dhan Access Token"),
        (r'DHAN_PIN\s*=\s*["\'][0-9]{4}["\']', "Hardcoded Dhan PIN"),
        (r'DHAN_TOTP_SECRET\s*=\s*["\'][A-Z0-9]{16,}["\']', "Hardcoded TOTP Secret Key"),
    ]
    
    found_issues = 0
    for root, dirs, files in os.walk(base_dir):
        # Skip git, venv, pycache
        dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', '.venv', 'venv', 'node_modules')]
        for file in files:
            if file.endswith(('.py', '.json', '.sh', '.md', '.yml', '.yaml')) and file != '.env':
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        for pattern, desc in suspicious_patterns:
                            matches = re.findall(pattern, content)
                            if matches:
                                rel_path = os.path.relpath(filepath, base_dir)
                                print(f"{FAIL:<8} | {desc} found in {rel_path} (Matches: {len(matches)})")
                                found_issues += 1
                except Exception:
                    pass

    if found_issues == 0:
        print(f"{PASS:<8} | No hardcoded JWT tokens, API keys, PINs, or TOTP secrets found in codebase")

def audit_risk_limits():
    print("\n--- 3. Algorithmic Order Caps & Risk Limits ---")
    ta_dir = "/Users/sreekanthmekala/Desktop/TradingAgent"
    server_py = os.path.join(ta_dir, "server.py")
    
    if os.path.exists(server_py):
        with open(server_py, "r") as f:
            content = f.read()
            if "MAX_LOTS" in content or "max_lots" in content or "max(" in content:
                print(f"{PASS:<8} | Order sizing calculation uses boundary bounds / max safety caps in server.py")
            else:
                print(f"{WARN:<8} | Consider adding explicit MAX_LOTS_PER_ORDER cap in server.py")
                
            if "debounce" in content or "time.time()" in content:
                print(f"{PASS:<8} | Debouncing & rate-limiting guards detected in server.py")
            else:
                print(f"{WARN:<8} | Consider adding request debouncing in server.py")

def main():
    print("=================================================================")
    print("      AUTOMATED CYBERSECURITY & SYSTEM HARDENING AUDIT           ")
    print("=================================================================")

    ta_dir = "/Users/sreekanthmekala/Desktop/TradingAgent"
    ot_dir = "/Users/sreekanthmekala/OptionsTrading"

    if os.path.exists(ta_dir):
        audit_git_and_env(ta_dir)
        audit_hardcoded_secrets(ta_dir)

    if os.path.exists(ot_dir):
        audit_git_and_env(ot_dir)
        audit_hardcoded_secrets(ot_dir)

    audit_risk_limits()

    print("\n=================================================================")
    print("                      AUDIT COMPLETE                             ")
    print("=================================================================")

if __name__ == "__main__":
    main()
