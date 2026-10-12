"""Dhan Market Data and Margin Calculation Service."""

import time
import logging
import requests
from typing import Optional, Dict, Any, List
from constants import index_name_for
from broker.common import ExchangeSegment

logger = logging.getLogger("broker.market_data")


class DhanMarketDataService:
    def __init__(self, auth_service, instrument_service=None, cache_ttl: float = 2.0):
        self.auth = auth_service
        self.instrument = instrument_service
        self._ltp_cache: Dict[Any, Any] = {}
        self._ltp_cache_ttl = cache_ttl

    def round_to_tick(self, price: float, tick: float = 0.05) -> float:
        """Rounds price to the nearest tick size."""
        if not price:
            return 0.0
        return round(round(float(price) / tick) * tick, 2)

    def get_index_spot_fallback(self, symbol: str) -> Optional[float]:
        """Fetches live index spot price from Yahoo Finance."""
        yahoo_map = {
            "NIFTY": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
        }
        ticker = yahoo_map.get(symbol.upper())
        if not ticker:
            logger.warning(f"No Yahoo ticker mapping for {symbol}")
            return None

        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TradingAgent/1.0)"},
                timeout=8
            )
            if resp.status_code == 200:
                data = resp.json()
                price = data['chart']['result'][0]['meta'].get('regularMarketPrice')
                if price and float(price) > 0:
                    logger.info(f"Yahoo Fallback: {symbol} ({ticker}) spot = {price}")
                    return float(price)
            logger.warning(f"Yahoo Fallback: Empty response for {ticker} ({resp.status_code})")
            return None
        except Exception as e:
            logger.error(f"Yahoo Fallback failed for {symbol}: {e}")
            return None

    def get_ltp(self, security_id: str, exchange_segment: str = ExchangeSegment.NSE_FNO) -> Optional[float]:
        """Fetches Last Traded Price (LTP) with caching and fallbacks."""
        cache_key = (str(security_id), exchange_segment)
        cached = self._ltp_cache.get(cache_key)
        if cached:
            price, ts = cached
            if time.time() - ts < self._ltp_cache_ttl:
                return price

        if exchange_segment == "IDX_I":
            sym = index_name_for(security_id)
            if sym:
                if self.auth.access_token and self.auth.client_id and not self.auth.dry_run:
                    try:
                        url = "https://api.dhan.co/v2/marketfeed/ltp"
                        headers = {
                            'Content-Type': 'application/json',
                            'access-token': self.auth.access_token,
                            'client-id': str(self.auth.client_id)
                        }
                        payload = {exchange_segment: [int(security_id)]}
                        resp = requests.post(url, headers=headers, json=payload, timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            seg_data = data.get('data', {}).get(exchange_segment, {})
                            inst_data = seg_data.get(str(security_id), {})
                            price = inst_data.get('last_price')
                            if price and float(price) > 0:
                                self._ltp_cache[cache_key] = (float(price), time.time())
                                return float(price)
                    except Exception as e:
                        logger.warning(f"Dhan index LTP failed: {e}")

                price = self.get_index_spot_fallback(sym)
                if price:
                    self._ltp_cache[cache_key] = (price, time.time())
                    return price
            logger.error(f"Index LTP unavailable for ID {security_id}")
            return None

        if self.auth.dry_run:
            return 100.0

        if not self.auth.access_token or not self.auth.client_id:
            return None

        url = "https://api.dhan.co/v2/marketfeed/ltp"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token,
            'client-id': str(self.auth.client_id)
        }
        payload = {exchange_segment: [int(security_id)]}

        def _parse_ltp_resp(data):
            if data.get('status') in ('failed', 'failure'):
                error_data = data.get('data', {})
                logger.error(f"get_ltp: API returned failure in 200 body: {error_data}")
                return None, True
            seg_data = (data.get('data') or {}).get(exchange_segment, {})
            inst_data = seg_data.get(str(security_id), {})
            price = inst_data.get('last_price')
            if price is None:
                logger.warning(f"get_ltp: sec_id={security_id} absent in response. Segment keys: {list(seg_data.keys())[:10]}")
            return price, False

        def _try_direct(hdrs):
            try:
                r = requests.post(url, headers=hdrs, json=payload, timeout=5)
                if r.status_code == 200:
                    price, is_err = _parse_ltp_resp(r.json())
                    return price, is_err
                elif r.status_code == 401:
                    logger.warning("get_ltp: 401 from direct API")
                    return None, True
                else:
                    logger.error(f"get_ltp: HTTP {r.status_code} — {r.text[:200]}")
                    return None, False
            except Exception as e:
                logger.error(f"get_ltp direct exception: {e}")
                return None, False

        def _cache_and_return(p):
            self._ltp_cache[cache_key] = (float(p), time.time())
            return float(p)

        price, is_auth_err = _try_direct(headers)
        if price is not None:
            return _cache_and_return(price)

        if is_auth_err:
            logger.warning("get_ltp: auth error — attempting token sync from Redis")
            if self.auth.sync_token_from_redis():
                headers['access-token'] = self.auth.access_token
                price, _ = _try_direct(headers)
                if price is not None:
                    return _cache_and_return(price)

        if self.auth.dhan:
            try:
                qresp = self.auth.dhan.quote_data({exchange_segment: [int(security_id)]})
                if qresp.get('status') == 'success':
                    seg = (qresp.get('data') or {}).get(exchange_segment, {})
                    inst = seg.get(str(security_id), {})
                    price = inst.get('last_price') or inst.get('lastTradedPrice')
                    if price:
                        logger.info(f"get_ltp: SDK quote_data fallback → {security_id}={price}")
                        return _cache_and_return(price)
                logger.error(f"get_ltp: SDK fallback also failed: {qresp}")
            except Exception as e:
                logger.error(f"get_ltp SDK fallback exception: {e}")

        return None

    def get_fund_limits(self) -> Dict[str, Any]:
        """Retrieves available fund limits from Dhan."""
        if self.auth.dry_run:
            return {"status": "success", "data": {"availabelBalance": 50000.00}}

        if self.auth.dhan:
            try:
                resp = self.auth.dhan.get_fund_limits()
                if resp.get('status') == 'success':
                    return resp
                elif resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                    logger.warning("Get Fund Limits: 401 Unauthorized. Syncing token...")
                    if self.auth.sync_token_from_redis():
                        return self.auth.dhan.get_fund_limits()
                else:
                    logger.error(f"Failed to fetch fund limits: {resp}")
                    return {"status": "error", "message": resp.get('remarks')}
            except Exception as e:
                logger.error(f"Exception fetching fund limits: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Broker not initialized"}

    def margin_calculator(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates margin required for a specific order."""
        if self.auth.dry_run:
            qty = int(order_data.get('quantity', 1))
            return {"status": "success", "data": {"totalMargin": qty * 5000.0}}

        if self.auth.dhan:
            try:
                if 'productType' not in order_data:
                    order_data['productType'] = 'INTRADAY'

                def _call_margin():
                    return self.auth.dhan.margin_calculator(
                        security_id=order_data.get('security_id'),
                        exchange_segment=order_data.get('exchange_segment'),
                        transaction_type=order_data.get('transaction_type'),
                        quantity=order_data.get('quantity'),
                        product_type=order_data.get('product_type', 'INTRADAY'),
                        price=order_data.get('price', 0)
                    )

                resp = _call_margin()
                if resp.get('status') == 'success':
                    return resp
                elif resp.get('errorCode') == 'DH-901' or 'Unauthorized' in str(resp):
                    logger.warning("Margin Calculator: 401 Unauthorized. Syncing token...")
                    if self.auth.sync_token_from_redis():
                        return _call_margin()

                return {"status": "error", "message": resp.get('remarks') or resp.get('errorMessage')}
            except Exception as e:
                logger.error(f"Exception in margin calculator: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Broker not initialized"}

    def get_multi_margin_calculator(self, orders_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculates margin for multiple orders using Dhan v2 multi endpoint."""
        if self.auth.dry_run:
            total = sum(int(o.get('quantity', 1)) * 4500.0 for o in orders_list)
            return {"status": "success", "data": {"totalMargin": total}}

        if not self.auth.access_token:
            return {"status": "error", "message": "Missing info"}

        url = "https://api.dhan.co/v2/margincalculator/multi"
        headers = {
            'Content-Type': 'application/json',
            'access-token': self.auth.access_token
        }
        payload = []
        for o in orders_list:
            item = o.copy()
            item['dhanClientId'] = self.auth.client_id
            if 'productType' not in item:
                item['productType'] = 'INTRADAY'
            payload.append(item)

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=(5, 10))
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                logger.warning("Multi Margin: 401 Unauthorized. Syncing...")
                if self.auth.sync_token_from_redis():
                    headers['access-token'] = self.auth.access_token
                    resp = requests.post(url, headers=headers, json=payload, timeout=(5, 10))
                    if resp.status_code == 200:
                        return resp.json()
                return {"status": "error", "message": "Auth failed"}
            else:
                return {"status": "error", "message": resp.text}
        except Exception as e:
            logger.error(f"Multi Margin Exception: {e}")
            return {"status": "error", "message": str(e)}

    def calculate_lots_by_margin(self, security_id: str, transaction_type: str = 'BUY', ltp: float = 0) -> int:
        """Computes the maximum number of lots tradeable given available margin."""
        try:
            fund_resp = self.get_fund_limits()
            if fund_resp.get('status') != 'success':
                logger.warning(f"Fund limits unavailable ({fund_resp}); defaulting to 1 lot.")
                return 1

            fund_data = fund_resp.get('data', {})
            available = float(
                fund_data.get('availabelBalance') or
                fund_data.get('availableBalance') or 0
            )
            if available <= 0:
                logger.warning(f"Available margin is {available}; defaulting to 1 lot.")
                return 1

            lot_size = 1
            if self.instrument and hasattr(self.instrument, 'lot_map'):
                lot_size = self.instrument.lot_map.get(str(security_id), 1)

            if not ltp or float(ltp) <= 0:
                logger.warning(f"calculate_lots_by_margin: LTP is {ltp} for {security_id} — fetching live.")
                ltp = self.get_ltp(security_id) or 0
            if float(ltp) <= 0:
                logger.warning(f"calculate_lots_by_margin: LTP still 0 for {security_id}; defaulting to 1 lot.")
                return 1

            margin_resp = self.margin_calculator({
                'security_id': security_id,
                'exchange_segment': ExchangeSegment.NSE_FNO,
                'transaction_type': transaction_type,
                'quantity': lot_size,
                'product_type': 'INTRADAY',
                'price': float(ltp),
            })

            if margin_resp.get('status') != 'success':
                logger.warning(f"Margin calc failed ({margin_resp}); defaulting to 1 lot.")
                return 1

            margin_per_lot = float(margin_resp.get('data', {}).get('totalMargin', 0))
            if margin_per_lot <= 0:
                logger.warning(f"Margin per lot = {margin_per_lot} for {security_id}; defaulting to 1 lot.")
                return 1

            max_lots = int(available / margin_per_lot)
            lots = max(1, max_lots)
            logger.info(
                f"Margin-based qty [{security_id}]: available={available:.0f}, "
                f"per_lot={margin_per_lot:.0f}, lots={lots}"
            )
            return lots

        except Exception as e:
            logger.error(f"calculate_lots_by_margin error: {e}")
            return 1
