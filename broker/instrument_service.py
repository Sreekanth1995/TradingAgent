"""Dhan Instrument and Scrip Master Resolution Service."""

import os
import csv
import logging
import threading
import requests
from typing import Dict, Any, Optional, Set, Callable
from constants import index_id_for

logger = logging.getLogger("broker.instrument")


class DhanInstrumentService:
    def __init__(
        self,
        csv_path: Optional[str] = None,
        load_scrip: bool = True,
        alarm_fn: Optional[Callable[[str, str], None]] = None,
        start_thread: bool = False,
    ):
        self._csv_path = csv_path
        self.alarm_fn = alarm_fn
        self.scrip_map: Dict[Any, str] = {}
        self.lot_map: Dict[str, int] = {}
        self.exact_symbol_map: Dict[str, Dict[str, Any]] = {}
        self.expiry_indices: Set[str] = set()
        self.scrip_loaded: bool = False
        self._scrip_ready = threading.Event()

        if start_thread and load_scrip:
            def load_scrip_background():
                try:
                    self._load_scrip_master()
                    self.scrip_loaded = True
                    logger.info("✅ Scrip Master loaded successfully in background")
                except Exception as e:
                    logger.error(f"Failed to load Scrip Master: {e}")
                finally:
                    self._scrip_ready.set()

            threading.Thread(target=load_scrip_background, daemon=True).start()
        elif not load_scrip:
            self._scrip_ready.set()

    @property
    def scrip_csv_path(self) -> str:
        if self._csv_path:
            return self._csv_path
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dhan_scrip_master.csv")

    def _alarm(self, msg: str, prefix: str = "🚨 ") -> None:
        if self.alarm_fn:
            try:
                self.alarm_fn(msg, prefix)
                return
            except Exception as e:
                logger.warning(f"Instrument alarm failed: {e}")
        logger.warning(f"{prefix}{msg}")

    def get_index_id(self, symbol: str) -> Optional[str]:
        """Returns standard Dhan Security ID for indices."""
        return index_id_for(symbol)

    def _load_scrip_master(self) -> None:
        """Downloads and parses the Dhan Scrip Master CSV."""
        csv_file = self.scrip_csv_path
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        MIN_VALID_SIZE = 20 * 1024 * 1024

        def _needs_download() -> bool:
            if not os.path.exists(csv_file):
                logger.info("Scrip master CSV does not exist. Initial download required.")
                return True
            if os.path.getsize(csv_file) < MIN_VALID_SIZE:
                logger.warning(f"Existing CSV too small ({os.path.getsize(csv_file)//1024} KB). Re-downloading.")
                return True

            import pytz
            from datetime import datetime, time, timedelta
            IST = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(IST)
            weekday = now_ist.weekday()
            current_time = now_ist.time()

            if 0 <= weekday <= 4 and time(9, 0) <= current_time <= time(15, 30):
                return False

            mtime_ist = datetime.fromtimestamp(os.path.getmtime(csv_file), tz=IST)
            days_since_friday = (weekday - 4) % 7
            if days_since_friday == 0 and current_time < time(15, 30):
                days_since_friday = 7

            last_friday_1530 = (now_ist - timedelta(days=days_since_friday)).replace(hour=15, minute=30, second=0, microsecond=0)
            if mtime_ist < last_friday_1530:
                logger.info("Scrip Master CSV last modified before last Friday 15:30 IST. Triggering download.")
                return True
            return False

        if _needs_download():
            logger.info(f"Downloading Scrip Master from {url}...")
            for attempt in range(1, 4):
                try:
                    tmp_file = csv_file + ".tmp"
                    r = requests.get(url, stream=True, timeout=(10, 180))
                    if r.status_code == 200:
                        bytes_written = 0
                        with open(tmp_file, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=65536):
                                f.write(chunk)
                                bytes_written += len(chunk)
                        if bytes_written >= MIN_VALID_SIZE:
                            os.replace(tmp_file, csv_file)
                            logger.info(f"Download complete ({bytes_written // 1024} KB).")
                            break
                        else:
                            logger.error(f"Attempt {attempt}: download too small ({bytes_written // 1024} KB).")
                            if os.path.exists(tmp_file):
                                os.remove(tmp_file)
                    else:
                        logger.error(f"Attempt {attempt}: HTTP {r.status_code}.")
                        break
                except Exception as e:
                    logger.error(f"Attempt {attempt}: Download error: {e}")
            else:
                logger.error("All download attempts failed. Falling back to stale file if available.")

        if not os.path.exists(csv_file):
            logger.error("Scrip Master CSV not found and download failed.")
            return

        logger.info(f"Parsing Scrip Master from {csv_file} ...")
        count = 0
        try:
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                if 'SEM_EXM_EXCH_ID' not in headers:
                    logger.error(f"Expected column 'SEM_EXM_EXCH_ID' not found. Got: {headers}.")
                    return
                for row in reader:
                    if row.get('SEM_EXM_EXCH_ID') == 'NSE' and row.get('SEM_INSTRUMENT_NAME') in ['OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK']:
                        sym = row.get('SM_SYMBOL_NAME', '').strip()
                        if not sym:
                            sym = row.get('SEM_TRADING_SYMBOL', '').split('-')[0]
                        sym = sym.strip()
                        strike = float(row.get('SEM_STRIKE_PRICE', 0))
                        opt_type = row.get('SEM_OPTION_TYPE')
                        expiry_raw = row.get('SEM_EXPIRY_DATE', '').split(" ")[0]
                        key = (sym, strike, opt_type, expiry_raw)
                        sec_id = row.get('SEM_SMST_SECURITY_ID', '').strip()
                        self.scrip_map[key] = sec_id
                        try:
                            self.lot_map[sec_id] = int(float(row.get('SEM_LOT_UNITS', 1)))
                        except Exception:
                            self.lot_map[sec_id] = 1

                        trading_sym = row.get('SEM_TRADING_SYMBOL', '').strip()
                        if trading_sym:
                            self.exact_symbol_map[trading_sym] = {
                                "security_id": sec_id,
                                "strike": strike,
                                "expiry": expiry_raw,
                                "symbol": trading_sym,
                                "opt_type": opt_type,
                                "underlying": sym
                            }
                        count += 1

            self.expiry_indices = set()
            import pytz
            from datetime import datetime
            IST = pytz.timezone('Asia/Kolkata')
            today_str = datetime.now(IST).strftime('%Y-%m-%d')
            for (sym, strike, opt_type, exp) in self.scrip_map.keys():
                if exp == today_str and sym in ['NIFTY', 'BANKNIFTY', 'FINNIFTY']:
                    self.expiry_indices.add(sym)

            logger.info(f"Loaded {count} instruments into Scrip Map.")
        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")

    def is_expiry_day(self, underlying: str) -> bool:
        """Checks if today is an expiry day for the given underlying index."""
        nearest = self.get_nearest_expiry(underlying)
        if not nearest:
            return False
        import pytz
        from datetime import datetime
        IST = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(IST).strftime('%Y-%m-%d')
        return nearest == today_str

    def get_nearest_expiry(self, symbol: str) -> Optional[str]:
        """Finds the closest expiry date for the given symbol in the scrip map."""
        expiries = set()
        for key in self.scrip_map.keys():
            if key[0] == symbol:
                expiries.add(key[3])

        if not expiries:
            return None

        from datetime import datetime
        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(IST).strftime('%Y-%m-%d')
        future_expiries = [e for e in expiries if e >= today_str]

        if not future_expiries:
            logger.warning(f"No future expiries found for {symbol} among {len(expiries)} total. Using earliest available.")
            return sorted(list(expiries))[0]

        return sorted(future_expiries)[0]

    def get_next_expiry(self, symbol: str) -> Optional[str]:
        """Returns the second-nearest future expiry for a symbol."""
        expiries = set()
        for key in self.scrip_map.keys():
            if key[0] == symbol:
                expiries.add(key[3])

        if not expiries:
            return None

        import pytz
        from datetime import datetime
        IST = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(IST).strftime('%Y-%m-%d')
        sorted_future = sorted(e for e in expiries if e >= today_str)

        if len(sorted_future) >= 2:
            return sorted_future[1]
        elif sorted_future:
            if sorted_future[0] == today_str:
                self._alarm(
                    f"get_next_expiry fallback rejected: Only today's expiry ({today_str}) "
                    f"is available for {symbol}. Refusing to trade today's expiry option."
                )
                return None
            logger.warning(f"Only one future expiry for {symbol}; using it as next expiry fallback.")
            return sorted_future[0]

        logger.warning(f"No future expiries found for {symbol}. Using latest available.")
        return sorted(expiries)[-1]

    def get_security_info_by_symbol(self, exact_symbol: str) -> Optional[Dict[str, Any]]:
        """Returns dictionary mapping for an exact option string."""
        return self.exact_symbol_map.get(exact_symbol.strip().upper())

    def get_security_id(self, symbol: str, strike: float, opt_type: str, expiry: Optional[str] = None) -> Optional[str]:
        """Look up Security ID from the loaded map."""
        try:
            s_price = float(strike)
        except Exception:
            s_price = 0.0

        key = (symbol, s_price, opt_type, expiry)
        sec_id = self.scrip_map.get(key)
        if sec_id:
            return sec_id

        msg = (
            f"SCRIP MISS for {symbol} {opt_type} strike={s_price} exp={expiry} — "
            f"scrip_map has {len(self.scrip_map)} entries but not this strike. "
            f"Refusing to fabricate a security_id. Check /reload-scrip and CSV freshness."
        )
        self._alarm(msg, prefix="🚨 ")
        return None

    def get_itm_contract(self, underlying: str, side: str, spot_price: float) -> Optional[Dict[str, Any]]:
        """Determines the best ITM strike and returns the contract record."""
        if not self.scrip_map:
            waited = self._scrip_ready.wait(timeout=30)
            if not self.scrip_map:
                logger.error("get_itm_contract: scrip_map is empty after wait. CSV may be missing.")
                return None
        try:
            spot = float(spot_price)
            atm_strike = round(spot / 50) * 50
            if side == 'CE':
                strike = atm_strike - 50
            else:
                strike = atm_strike + 50

            if self.is_expiry_day(underlying):
                expiry = self.get_next_expiry(underlying)
                logger.info(f"Expiry day for {underlying} — using next-week expiry: {expiry}")
            else:
                expiry = self.get_nearest_expiry(underlying)

            if not expiry:
                logger.error(f"No expiry found for {underlying}")
                return None

            sec_id = self.get_security_id(underlying, strike, side, expiry)
            if sec_id:
                logger.info(f"Selected ITM for {underlying} ({side}): {strike} Exp: {expiry} -> ID: {sec_id}")
                exp_dt = expiry.replace("-", "")
                tv_exp = exp_dt[2:]
                tv_cp = "C" if side == "CE" else "P"
                tv_symbol = f"NSE:{underlying}{tv_exp}{tv_cp}{int(strike)}"
                return {
                    "security_id": sec_id,
                    "strike": strike,
                    "expiry": expiry,
                    "symbol": f"{underlying}_{int(strike)}_{side}",
                    "tv_symbol": tv_symbol,
                }
            else:
                logger.error(f"Could not find exact ITM contract for {underlying} {strike} {side} {expiry}")
                return None
        except Exception as e:
            logger.error(f"Error in ITM Selection: {e}")
            return None
