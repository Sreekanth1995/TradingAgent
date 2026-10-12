"""Dhan Authentication and Token Lifecycle Service."""

import os
import logging
import requests
from typing import Optional, Tuple, Dict, Any, Callable
from dhanhq import dhanhq
from broker.common import DHAN_AVAILABLE

logger = logging.getLogger("broker.auth")


class DhanAuthService:
    def __init__(
        self,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
        api_id: Optional[str] = None,
        api_secret: Optional[str] = None,
        redis_client=None,
        dry_run: bool = False,
        on_client_reinit: Optional[Callable[[Optional[dhanhq], str], None]] = None,
    ):
        self.client_id = client_id or os.getenv("DHAN_CLIENT_ID")
        self.access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN")
        self.api_id = api_id or os.getenv("DHAN_API_ID")
        self.api_secret = api_secret or os.getenv("DHAN_API_SECRET")
        self.r = redis_client
        self.dry_run = dry_run
        self.on_client_reinit = on_client_reinit
        self.dhan: Optional[dhanhq] = None

        if self.r:
            try:
                cached_token = self.r.get("dhan_access_token")
                if cached_token:
                    self.access_token = cached_token
                    logger.info("✅ Access Token loaded from Redis.")
            except Exception as e:
                logger.warning(f"Failed to load token from Redis: {e}")
        else:
            logger.warning("Redis client not provided to DhanAuthService. Persistence disabled.")

        self._init_dhan_instance()

    def _init_dhan_instance(self) -> None:
        if self.client_id and self.access_token and DHAN_AVAILABLE:
            if not self.dry_run:
                try:
                    self.dhan = dhanhq(self.client_id, self.access_token)
                except Exception as e:
                    logger.error(f"Failed to instantiate dhanhq: {e}")
                    self.dhan = None
        else:
            self.dhan = None

        if self.on_client_reinit:
            self.on_client_reinit(self.dhan, self.access_token)

    def save_access_token(self, token: str) -> None:
        """Persists the access token to Redis and reinitializes the broker client."""
        self.access_token = token
        if self.r:
            try:
                self.r.set("dhan_access_token", token)
                logger.info("✅ Access Token saved to Redis.")
            except Exception as e:
                logger.error(f"Failed to save token to Redis: {e}")

        self._init_dhan_instance()

    def refresh_client(self, new_token: str) -> bool:
        """Updates the access token and re-initializes the Dhan client."""
        self.access_token = new_token
        if self.r:
            try:
                self.r.set("dhan_access_token", new_token)
                logger.info("New Access Token persisted to Redis.")
            except Exception as e:
                logger.error(f"Failed to persist token to Redis: {e}")

        self._init_dhan_instance()
        return bool(self.dhan or self.dry_run)

    def sync_token_from_redis(self) -> bool:
        """Checks Redis for a newer token and refreshes the client if found."""
        if not self.r:
            return False
        try:
            latest_token = self.r.get("dhan_access_token")
            if latest_token and latest_token != self.access_token:
                logger.info("🔄 Newer token found in Redis. Syncing...")
                return self.refresh_client(latest_token)
        except Exception as e:
            logger.error(f"Failed to sync token from Redis: {e}")
        return False

    def get_consent_url(self) -> Optional[str]:
        """Generates the Dhan consent URL for browser-based login."""
        if not self.api_id or not self.api_secret or not self.client_id:
            logger.error("DHAN_API_ID or DHAN_API_SECRET missing in .env")
            return None
        url = f"https://auth.dhan.co/app/generate-consent?client_id={self.client_id}"
        headers = {
            'app_id': self.api_id,
            'app_secret': self.api_secret,
            'Content-Type': 'application/json'
        }
        try:
            resp = requests.post(url, headers=headers, timeout=(5, 10))
            if resp.status_code == 200:
                data = resp.json()
                consent_id = data.get("consentAppId")
                if consent_id:
                    return f"https://auth.dhan.co/login/consentApp-login?consentAppId={consent_id}"
            logger.error(f"Failed to generate consent: {resp.status_code} - {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Error generating consent URL: {e}")
            return None

    def consume_consent(self, token_id: str) -> Tuple[bool, str]:
        """Exchanges tokenId for a 24-hour access token."""
        if not self.api_id or not self.api_secret:
            return False, "API credentials missing"

        url = f"https://auth.dhan.co/app/consumeApp-consent?tokenId={token_id}"
        headers = {
            'app_id': self.api_id,
            'app_secret': self.api_secret
        }
        try:
            resp = requests.post(url, headers=headers, timeout=(5, 10))
            if resp.status_code == 200:
                data = resp.json()
                access_token = data.get("accessToken")
                if access_token:
                    self.refresh_client(access_token)
                    return True, "Authentication Successful"
            logger.error(f"Failed to consume consent: {resp.status_code} - {resp.text}")
            return False, f"Auth failed: {resp.status_code}"
        except Exception as e:
            logger.error(f"Error consuming consent: {e}")
            return False, str(e)

    def renew_token(self) -> Tuple[bool, str]:
        """Extends validity of an active Dhan access token by 24 hours."""
        if not self.access_token or not self.client_id:
            logger.error("renew_token: Missing access_token or client_id")
            return False, "Missing access_token or client_id"

        url = "https://api.dhan.co/v2/RenewToken"
        headers = {
            'access-token': self.access_token,
            'dhanClientId': str(self.client_id),
            'Content-Type': 'application/json'
        }
        try:
            resp = requests.post(url, headers=headers, timeout=(5, 10))
            if resp.status_code == 200:
                data = resp.json()
                new_token = (data.get("token") or data.get("accessToken") or
                             (data.get("data") or {}).get("token"))
                target_token = new_token if new_token else self.access_token
                self.refresh_client(target_token)
                logger.info("✅ Successfully renewed Dhan access token via RenewToken API")
                return True, "Token Renewed Successfully"

            logger.error(f"Failed to renew token: {resp.status_code} - {resp.text}")
            return False, f"Renew failed: {resp.status_code} - {resp.text}"
        except Exception as e:
            logger.error(f"Error renewing token: {e}")
            return False, str(e)
