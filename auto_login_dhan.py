#!/usr/bin/env python3
"""
Automated Morning 09:00 AM Dhan Login & Token Refresh Script.

Executes daily at 09:00 AM IST:
1. Primary Path: Calls native `RenewToken` API to extend current active token by 24h.
2. Fallback Path: If token expired, executes OAuth consent + 2FA TOTP login via pyotp.

Usage:
    python3 auto_login_dhan.py
"""

import os
import sys
import json
import logging
import requests

try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("auto_login_dhan")

TA_SERVER_URL = os.getenv("TRADING_AGENT_URL", "http://127.0.0.1:80")
SECRET = os.getenv("SECRET", "AGY_SEC_2026_x7k9")

def attempt_renew_token():
    """Attempt primary 09:00 AM renewal via RenewToken API."""
    logger.info("⚡ Attempting 09:00 AM Token Renewal via RenewToken API...")
    url = f"{TA_SERVER_URL}/auth/renew"
    try:
        resp = requests.post(url, json={"secret": SECRET}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                logger.info(f"✅ Token Renewal Succeeded: {data.get('message')}")
                return True
        logger.warning(f"RenewToken API response: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Failed to reach /auth/renew: {e}")
    return False

def check_health():
    """Verify system health post-renewal."""
    try:
        resp = requests.get(f"{TA_SERVER_URL}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"Health status: {data}")
            return data.get("broker_initialized", False) and data.get("status") == "healthy"
    except Exception as e:
        logger.error(f"Health check failed: {e}")
    return False

def main():
    logger.info("=== Starting 09:00 AM Automated Morning Dhan Login Execution ===")
    
    # 1. Primary path: Native RenewToken API
    if attempt_renew_token() and check_health():
        logger.info("🎉 09:00 AM Morning Token Renewal Complete! TradingAgent is HEALTHY.")
        sys.exit(0)
        
    logger.info("⚠️ Native RenewToken API failed or token expired. Attempting TOTP Fallback...")
    
    totp_secret = os.getenv("DHAN_TOTP_SECRET")
    if not totp_secret:
        logger.error("DHAN_TOTP_SECRET missing in environment. Cannot generate TOTP for fallback.")
        sys.exit(1)
        
    if not PYOTP_AVAILABLE:
        logger.error("pyotp package not installed. Run: pip install pyotp")
        sys.exit(1)
        
    totp_code = pyotp.TOTP(totp_secret).now()
    logger.info(f"Generated live TOTP 2FA code: {totp_code}")
    
    # 2. Get consent URL from server
    try:
        resp = requests.post(f"{TA_SERVER_URL}/auth/login-url", json={"secret": SECRET}, timeout=10)
        data = resp.json()
        consent_url = data.get("url")
        if not consent_url:
            logger.error("Failed to generate consent URL from TradingAgent server")
            sys.exit(1)
            
        logger.info(f"Consent URL generated: {consent_url}")
        logger.info("Submitting headless TOTP login...")
        
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(consent_url)
                
                client_id = os.getenv("DHAN_CLIENT_ID")
                pin = os.getenv("DHAN_PIN")
                
                if page.locator("input[name='mobileNumber'], input[name='clientId']").is_visible(timeout=5000):
                    page.fill("input[name='mobileNumber'], input[name='clientId']", client_id or "")
                    page.click("button[type='submit']")
                    page.wait_for_timeout(2000)
                    
                if page.locator("input[name='otp'], input[name='totp']").is_visible(timeout=5000):
                    page.fill("input[name='otp'], input[name='totp']", totp_code)
                    page.click("button[type='submit']")
                    page.wait_for_timeout(2000)
                    
                if page.locator("input[name='pin']").is_visible(timeout=5000):
                    page.fill("input[name='pin']", pin or "")
                    page.click("button[type='submit']")
                    page.wait_for_timeout(3000)
                    
                logger.info(f"Auth redirect URL: {page.url}")
                browser.close()
        except Exception as e:
            logger.warning(f"Playwright automation warning: {e}. Checking if callback landed...")

        if check_health():
            logger.info("🎉 Fallback Morning Dhan Login Complete! TradingAgent is HEALTHY.")
            sys.exit(0)
        else:
            logger.error("❌ Morning login process failed to initialize broker. Manual check required.")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Auto-login fallback error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
