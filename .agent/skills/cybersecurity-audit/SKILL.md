---
name: cybersecurity-audit
description: >-
  Automated cybersecurity audit and server hardening skill for hosted algorithmic trading applications.
  Scans for API secret leaks, open network ports, weak file permissions, unmasked logs, missing HTTPS,
  and algorithmic order risk caps.
---

# Cybersecurity Audit Skill for Hosted Trading Systems

Use this skill to perform automated security audits and server hardening on hosted algorithmic trading systems (`TradingAgent` and `OptionsTrading`).

---

## Audit Workflow

Run the automated cybersecurity auditor script:
```bash
python3 .agent/skills/cybersecurity-audit/scripts/audit_cybersecurity.py
```

### 1. Secret & Token Leak Audit
- **Codebase Scan**: Checks `.py`, `.json`, `.yml`, `.sh` files for hardcoded Dhan API secrets, JWT access tokens, PINs, or TOTP seeds.
- **Git History & Tracked Files**: Verifies `.env` is NOT tracked in Git and is included in `.gitignore`.
- **Log Sanitation**: Verifies log files (`ui_server.log`, `cron_fast.log`, `dhan_login.log`) do not contain unmasked raw API tokens.

### 2. Network & VPS Hardening Audit
- **SSH Hardening**: Verifies SSH password login is disabled (`PasswordAuthentication no`) and root login is restricted.
- **Firewall & Port Binding**: Verifies internal services (e.g. Redis `6379`, DBs) are bound strictly to `127.0.0.1` and UFW firewall blocks unneeded incoming ports.
- **HTTPS & SSL**: Verifies HTTPS encryption is enabled via Nginx + Certbot reverse proxy.

### 3. Algorithmic Risk Limit & Circuit Breaker Audit
- **Order Size Cap**: Verifies `MAX_LOTS_PER_ORDER` (e.g. 15 lots) is enforced in `server.py` to prevent software glitches from placing oversized orders.
- **Duplicate Order Debouncing**: Verifies `5s` debounce window on webhook triggers.
- **EOD Order Cleanup**: Verifies 15:20 IST EOD alert flush to cancel un-triggered GTT orders.

---

## Remediation Runbook

When the audit script identifies vulnerabilities, apply the following fixes:

### Fix 1: Restrict File Permissions on `.env`
```bash
chmod 600 .env
```

### Fix 2: Mask Tokens in Logging Output
Ensure `broker_dhan.py` and `server.py` mask tokens before printing:
```python
masked_token = token[:6] + "..." + token[-4:] if token else "None"
```

### Fix 3: Enforce SSH Key Authentication Only on VPS
```bash
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```
