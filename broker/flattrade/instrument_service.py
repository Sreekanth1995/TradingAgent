"""FlatTrade Instrument Service.

Provides contract resolution for FlatTrade exchange='NFO' using standard exchange trading symbols.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
from constants import strike_step_for

logger = logging.getLogger("broker.flattrade.instrument")


class FlatTradeInstrumentService:
    def __init__(self, auth_service=None):
        self.auth_service = auth_service

    def format_trading_symbol(
        self,
        underlying: str,
        strike: float,
        side: str,
        expiry_date: Optional[str] = None
    ) -> str:
        """Construct standard NSE F&O trading symbol for FlatTrade (NFO)."""
        side_clean = "CE" if side.upper() in ("CE", "CALL", "C") else "PE"
        strike_int = int(round(strike))
        
        if expiry_date:
            try:
                if "-" in expiry_date and len(expiry_date.split("-")[0]) == 4:
                    dt = datetime.strptime(expiry_date, "%Y-%m-%d")
                else:
                    dt = datetime.strptime(expiry_date, "%d-%b-%Y")
                year_str = dt.strftime("%y")
                month_str = dt.strftime("%b").upper()
                return f"{underlying.upper()}{year_str}{month_str}{strike_int}{side_clean}"
            except Exception as e:
                logger.warning(f"Error parsing expiry_date {expiry_date}: {e}")

        curr_year = datetime.now().strftime("%y")
        curr_month = datetime.now().strftime("%b").upper()
        return f"{underlying.upper()}{curr_year}{curr_month}{strike_int}{side_clean}"

    def get_itm_contract(self, underlying: str, side: str, spot_price: float, expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Resolves ITM option contract for FlatTrade execution."""
        try:
            spot = float(spot_price)
            step = strike_step_for(underlying)
            atm_strike = round(spot / step) * step
            if side.upper() in ('CE', 'CALL'):
                strike = atm_strike - step
                opt_type = 'CE'
            else:
                strike = atm_strike + step
                opt_type = 'PE'

            trading_symbol = self.format_trading_symbol(underlying, strike, opt_type, expiry)
            
            return {
                "broker": "flattrade",
                "underlying": underlying,
                "strike": strike,
                "option_type": opt_type,
                "expiry": expiry,
                "trading_symbol": trading_symbol,
                "security_id": trading_symbol,
                "exchange": "NFO",
                "product_type": "I",
            }
        except Exception as e:
            logger.error(f"FlatTradeInstrumentService ITM selection error: {e}")
            return None
