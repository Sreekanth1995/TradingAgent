"""Groww Authentication Service.

Handles headless TOTP-based authentication for Groww API v1 using official growwapi SDK:
- Auto-generates TOTP using pyotp
- Calls GrowwAPI.get_access_token(api_key, totp)
- Caches and syncs token via Redis key 'tokens:groww:access_token'
- Provides auth status checks and renewal
"""

import os
import logging
from typing import Optional, Dict, Any
import pyotp

logger = logging.getLogger("broker.groww.auth")


class GrowwAuthService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        totp_secret: Optional[str] = None,
        redis_client=None,
        dry_run: bool = False,
    ):
        self.api_key = api_key or os.getenv("GROWW_API_KEY", "")
        self.totp_secret = totp_secret or os.getenv("GROWW_TOTP_SECRET", "")
        self.redis_client = redis_client
        self.dry_run = dry_run or (os.getenv("DRY_RUN", "false").lower() == "true")
        self.access_token: Optional[str] = None
        self.ucc: str = os.getenv("GROWW_UCC", "GROWW_USER")

        # Try to sync from Redis on init
        self.sync_token_from_redis()

    def sync_token_from_redis(self) -> None:
        """Check Redis for existing access token."""
        if not self.redis_client:
            return
        try:
            stored = self.redis_client.get("tokens:groww:access_token")
            if stored:
                token_val = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
                if token_val:
                    self.access_token = token_val
                    logger.info("GrowwAuthService: Restored access token from Redis")
        except Exception as e:
            logger.warning(f"GrowwAuthService: Failed to read token from Redis: {e}")

    def save_access_token(self, token: str) -> None:
        """Save access token in memory and Redis."""
        self.access_token = token
        if self.redis_client:
            try:
                # 24 hour TTL (86400s)
                self.redis_client.set("tokens:groww:access_token", token, ex=86400)
                logger.info("GrowwAuthService: Saved access token to Redis with 24h TTL")
            except Exception as e:
                logger.error(f"GrowwAuthService: Failed to save token to Redis: {e}")

    def generate_access_token(self) -> Dict[str, Any]:
        """Generate access token headlessly via Groww API with pyotp TOTP."""
        if self.dry_run:
            simulated_token = f"simulated_groww_token_{os.urandom(8).hex()}"
            self.save_access_token(simulated_token)
            logger.info("GrowwAuthService: DRY_RUN mode, generated simulated token")
            return {"status": "success", "access_token": simulated_token, "dry_run": True}

        if not self.api_key or not self.totp_secret:
            err = "GROWW_API_KEY and GROWW_TOTP_SECRET must be configured"
            logger.error(f"GrowwAuthService: {err}")
            return {"status": "error", "message": err}

        try:
            totp = pyotp.TOTP(self.totp_secret).now()
            from growwapi import GrowwAPI
            token = GrowwAPI.get_access_token(api_key=self.api_key, totp=totp)
            if token:
                self.save_access_token(token)
                logger.info("GrowwAuthService: Successfully authenticated with Groww API")
                return {"status": "success", "access_token": token}
            else:
                return {"status": "error", "message": "Groww API returned empty token"}
        except Exception as e:
            logger.error(f"GrowwAuthService: Failed to authenticate with Groww API: {e}")
            return {"status": "error", "message": str(e)}

    def renew_token(self) -> Dict[str, Any]:
        """Renew current access token."""
        return self.generate_access_token()

    def get_auth_status(self) -> Dict[str, Any]:
        """Returns auth state and masked credentials for dashboard."""
        is_active = bool(self.access_token)
        masked_token = (
            f"{self.access_token[:4]}...{self.access_token[-4:]}"
            if self.access_token and len(self.access_token) > 8
            else None
        )
        return {
            "broker": "groww",
            "is_active": is_active,
            "ucc": self.ucc,
            "has_api_key": bool(self.api_key),
            "has_totp": bool(self.totp_secret),
            "masked_token": masked_token,
            "dry_run": self.dry_run,
        }
