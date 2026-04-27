import os
import re
import json
import logging
import threading
import time
import queue
import traceback
from flask import Flask, request, jsonify, render_template, Response
from dotenv import load_dotenv
from super_order_engine import SuperOrderEngine
from conditional_order_engine import ConditionalOrderEngine
from broker_dhan import DhanClient
from collections import deque
from datetime import datetime
import pytz
from instrument_resolver import resolve_index_spot, resolve_call_itm, resolve_put_itm
import trade_feed

# Load Environment Variables
load_dotenv()

# Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SECRET = os.getenv("WEBHOOK_SECRET", "60pgS") # Default from user example
AI_IN_THE_LOOP = os.getenv("AI_IN_THE_LOOP", "true").lower() == "true"

# SSE Infrastructure for AI Bridge (Multi-client support)
sse_clients = []
sse_lock = threading.Lock()
last_signal_storage = {"data": None}

# Signal Deduplication Memory (Key: {underlying}_{transaction_type}, Value: datetime)
signal_memory = {}
signal_memory_lock = threading.Lock()

# Logging Setup
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# In-memory error log buffer — captures WARNING/ERROR/CRITICAL across all loggers
_error_log_buffer = deque(maxlen=200)

class _ErrorBufferHandler(logging.Handler):
    def emit(self, record):
        try:
            _error_log_buffer.append({
                "time": self.formatter.formatTime(record) if self.formatter else record.asctime,
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            })
        except Exception:
            pass

_err_handler = _ErrorBufferHandler(level=logging.WARNING)
_err_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s'))
logging.getLogger().addHandler(_err_handler)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# activity_logs (In-memory fallback + Redis persistence)
activity_logs = deque(maxlen=50)

# Initialize Shared Redis Client
redis_client = None
try:
    import redis
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        redis_client = redis.from_url(redis_url, decode_responses=True)
    else:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    redis_client.ping()
    logger.info("✅ Shared Redis Client Initialized")
except Exception as e:
    logger.warning(f"Shared Redis not available: {e}. Falling back to memory.")

def _add_activity_log(msg, prefix=""):
    """
    Appends a log entry to the in-memory deque and persists it to Redis if available.
    Uses pipelining for efficient batch operations.
    """
    timestamp = datetime.now().strftime('%H:%M:%S')
    full_msg = f"[{timestamp}] {prefix}{msg}"
    
    # Update memory fallback
    activity_logs.appendleft(full_msg)
    
    # Persist to Redis via shared client
    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.lpush("activity_logs", full_msg)
            pipe.ltrim("activity_logs", 0, 49)
            pipe.execute()
        except Exception as e:
            logger.error(f"Failed to persist activity log to Redis: {e}")

# Initialize Components with graceful error handling
broker = None
super_order_engine = None
conditional_engine = None
init_error = None

USE_MOCK = os.getenv("USE_MOCK_API", "false").lower() == "true"

try:
    if USE_MOCK:
        from broker_mock import MockDhanClient
        broker = MockDhanClient(redis_client=redis_client)
        logger.info("🛠️  Running in MOCK API MODE - Using broker_mock.py")
    else:
        from broker_dhan import DhanClient
        broker = DhanClient(redis_client=redis_client)
        logger.info("🔗 Running in LIVE API MODE - Using broker_dhan.py")
        
    super_order_engine = SuperOrderEngine(broker, redis_client=redis_client, activity_logs=activity_logs)
    conditional_engine = ConditionalOrderEngine(broker, redis_client=redis_client, activity_log_fn=_add_activity_log)
    
    # --- Start Background Protection Monitor ---
    def _protection_monitor_loop():
        """Background thread to monitor conditional index levels."""
        logger.info("🛡️  Starting Background Protection Monitor...")
        while True:
            try:
                if conditional_engine:
                    conditional_engine.monitor_positions()
            except Exception as e:
                logger.error(f"Monitor Loop Error: {e}")
            time.sleep(2) # Frequency of index level polling

    monitor_thread = threading.Thread(target=_protection_monitor_loop, daemon=True)
    monitor_thread.start()

    logger.info("✅ System Initialized Successfully")
except Exception as e:
    init_error = str(e)
    logger.error(f"⚠️ Initialization Failed: {e}")
    logger.warning("App will start in degraded mode. Please check environment variables.")

# Trade Feed DB
trade_feed.init_db()

def _handle_live_order_update(order_id: str, status: str, avg_price):
    """Callback from Dhan Live Order Update WebSocket."""
    try:
        # 1. Check if this is an exit order fill — update exit price/profit on feed
        exit_meta = _get_exit_order_meta(order_id)
        if exit_meta and status in ('TRADED', 'FILLED') and avg_price:
            price = float(avg_price)
            feed_id = exit_meta.get('feed_id')
            entry_price = float(exit_meta.get('entry_price') or 0)
            qty = int(exit_meta.get('qty') or 1)
            profit = round((price - entry_price) * qty, 2) if entry_price else None
            if feed_id:
                trade_feed.update_trade(feed_id, exit_price=price, profit=profit, status='CLOSED', comment='Manual exit')
                logger.info(f"📡 Exit fill: order {order_id} → exit_price={price} profit={profit}")
            _clear_exit_order_meta(order_id)
            return

        # 2. Entry order updates
        if not super_order_engine:
            return
        underlying = super_order_engine.find_underlying_by_order_id(order_id)
        if not underlying:
            return
        state = super_order_engine._get_state(underlying)
        feed_id = state.get('trade_feed_id')
        logger.info(f"📡 Live Order Update: {order_id} {status} avg={avg_price} → {underlying}")
        if status in ('TRADED', 'FILLED', 'PART_TRADED') and avg_price:
            price = float(avg_price)
            super_order_engine.update_entry_price(underlying, price)
            if feed_id:
                trade_feed.update_trade(feed_id, entry_price=price, status='ACTIVE')
        elif status in ('CANCELLED', 'REJECTED'):
            if feed_id:
                trade_feed.update_trade(feed_id, status='FAILED', comment=f'Order {status}')
            super_order_engine._clear_state(underlying)
    except Exception as e:
        logger.error(f"Live order update handler error: {e}")

# Start Live Order Update WebSocket listener
if broker and not getattr(broker, 'dry_run', True):
    try:
        broker.start_order_update_listener(_handle_live_order_update)
    except Exception as e:
        logger.warning(f"Could not start order update listener: {e}")

# Pending trade-feed id per underlying (bridges signal → order placement)
_pending_trades: dict = {}

def _set_pending_trade(underlying: str, trade_id: int):
    if redis_client:
        redis_client.set(f"pending_trade:{underlying}", trade_id, ex=300)
    else:
        _pending_trades[underlying] = trade_id

def _get_pending_trade(underlying: str):
    if redis_client:
        v = redis_client.get(f"pending_trade:{underlying}")
        return int(v) if v else None
    return _pending_trades.get(underlying)

# Exit order meta — maps exit order_id → {feed_id, entry_price, qty}
# so the WS listener can update exit_price/profit when the SELL fill arrives.
_exit_order_meta: dict = {}

def _set_exit_order_meta(order_id: str, meta: dict):
    if redis_client:
        redis_client.set(f"exit_meta:{order_id}", json.dumps(meta), ex=300)
    else:
        _exit_order_meta[order_id] = meta

def _get_exit_order_meta(order_id: str):
    if redis_client:
        v = redis_client.get(f"exit_meta:{order_id}")
        return json.loads(v) if v else None
    return _exit_order_meta.get(order_id)

def _clear_exit_order_meta(order_id: str):
    if redis_client:
        redis_client.delete(f"exit_meta:{order_id}")
    else:
        _exit_order_meta.pop(order_id, None)

# In-memory stores (persisted to JSON files for restart survival)
_LEVELS_FILE = "levels.json"
_CONTEXT_FILE = "ai_context.txt"
_HISTORY_FILE = "trade_history.json"

_HISTORY_KEY = "trade_history"

def _load_history():
    if redis_client:
        try:
            raw = redis_client.lrange(_HISTORY_KEY, 0, 49)
            return [json.loads(r) for r in raw]
        except Exception as e:
            logger.error(f"Error loading history from Redis: {e}")
    # Fallback to JSON file
    try:
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading history from file: {e}")
    return []

def _save_history(data):
    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.delete(_HISTORY_KEY)
            for trade in data[-50:]:
                pipe.rpush(_HISTORY_KEY, json.dumps(trade))
            pipe.execute()
            return
        except Exception as e:
            logger.error(f"Error saving history to Redis: {e}")
    try:
        with open(_HISTORY_FILE, 'w') as f:
            json.dump(data[-50:], f)
    except Exception as e:
        logger.error(f"Error saving history to file: {e}")

def _add_to_history(trade):
    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.lpush(_HISTORY_KEY, json.dumps(trade))
            pipe.ltrim(_HISTORY_KEY, 0, 49)
            pipe.execute()
            return
        except Exception as e:
            logger.error(f"Error appending trade to Redis history: {e}")
    history = _load_history()
    history.append(trade)
    _save_history(history)

def _load_levels():
    """
    Loads levels from file, but clears them if it's after NSE market hours (15:30 IST)
    and the file has not been updated since market close.
    """
    try:
        if os.path.exists(_LEVELS_FILE):
            IST = pytz.timezone('Asia/Kolkata')
            now = datetime.now(IST)
            
            # Market close is 3:30 PM (15:30) IST
            market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
            
            # If it's currently PAST market close
            if now > market_close:
                mtime = datetime.fromtimestamp(os.path.getmtime(_LEVELS_FILE), IST)
                # If the file was last modified BEFORE today's market close, it's stale.
                if mtime < market_close:
                    content = {}
                    with open(_LEVELS_FILE) as f:
                         content = json.load(f)
                    
                    if content and content != {} and content != []:
                        logger.info("NSE Market Closed (15:30 IST). Clearing stale levels.")
                        _save_levels({})
                        return {}

        with open(_LEVELS_FILE) as f:
            return json.load(f)
    except Exception as e:
        return {}

def _save_levels(data):
    with open(_LEVELS_FILE, 'w') as f:
        json.dump(data, f)

def _load_context():
    try:
        with open(_CONTEXT_FILE) as f:
            return f.read()
    except Exception:
        return ""

def _save_context(text):
    with open(_CONTEXT_FILE, 'w') as f:
        f.write(text)


@app.route('/health')
def health():
    """
    Health check endpoint for monitoring.
    """
    try:
        status = {
            "status": "healthy" if broker and super_order_engine else "degraded",
            "broker_initialized": broker is not None,
            "engine_initialized": super_order_engine is not None,
            "error": init_error
        }
    except Exception as e:
        status = {"status": "error", "message": str(e)}
    return jsonify(status), 200

def _event_stream(q):
    """Generator for Server-Sent Events (SSE)."""
    while True:
        # Blocks until a signal arrives in the private client queue
        signal_data = q.get()
        yield f"event: signal\ndata: {json.dumps(signal_data)}\n\n"

@app.route('/dhan-webhook', methods=['POST'])
def dhan_webhook():
    """
    Receives Live Order Updates from Dhan Broker.
    Triggered when an order status changes (e.g., TRADED).
    """
    try:
        data = request.get_json(force=True, silent=True)
        # Authentication check
        if request.args.get('secret') != SECRET and data.get('secret') != SECRET:
             logger.warning("Unauthorized Dhan Webhook attempt")
             return jsonify({"status": "error", "message": "Unauthorized"}), 401
             
        if not data:
            return jsonify({"status": "error", "message": "No data"}), 400
            
        order_id = data.get('orderId')
        status = data.get('orderStatus')
        avg_price = data.get('averageTradedPrice', 0)

        logger.info(f"📡 Dhan Webhook: {order_id} - {status}")

        if super_order_engine and order_id:
            underlying = super_order_engine.find_underlying_by_order_id(order_id)
            if underlying:
                state = super_order_engine._get_state(underlying)
                feed_id = state.get('trade_feed_id')
                if status in ['TRADED', 'FILLED'] and avg_price:
                    super_order_engine.update_entry_price(underlying, float(avg_price))
                    if feed_id:
                        trade_feed.update_trade(feed_id, entry_price=float(avg_price), status='ACTIVE')
                    logger.info(f"Webhook: entry_price updated for {underlying} → {avg_price}")
                elif status in ['CANCELLED', 'REJECTED']:
                    if feed_id:
                        trade_feed.update_trade(feed_id, status='FAILED', comment=f'Order {status}')
                    super_order_engine._clear_state(underlying)
                    logger.info(f"Webhook: state cleared for {underlying} ({status})")

        return jsonify({"status": "received"}), 200
    except Exception as e:
        logger.error(f"Error processing Dhan Webhook: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/events')
def events():
    """SSE endpoint for AI to listen to real-time signals. Requires ?secret="""
    if request.args.get('secret') != SECRET:
        logger.warning("Unauthorized SSE Connection Attempt")
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    # Create a private queue for this client
    q = queue.Queue(maxsize=10)
    
    with sse_lock:
        sse_clients.append(q)
        logger.info(f"New SSE client connected. Active listeners: {len(sse_clients)}")
    
    def stream():
        try:
            for msg in _event_stream(q):
                yield msg
        finally:
            with sse_lock:
                if q in sse_clients:
                    sse_clients.remove(q)
                    logger.info(f"SSE client disconnected. Active listeners: {len(sse_clients)}")

    return Response(stream(), mimetype='text/event-stream')

@app.route('/last-signal')
def get_last_signal():
    """Returns the most recent enriched signal for AI pull/re-sync. Requires ?secret="""
    if request.args.get('secret') != SECRET:
        logger.warning("Unauthorized Last-Signal Pull Attempt")
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    return jsonify({"status": "success", "signal": last_signal_storage["data"]})



@app.route('/')
def dashboard():
    """
    Serves the Admin Dashboard UI.
    """
    return render_template('index.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint to receive TradingView Alerts.
    """
    # Check if components are initialized
    if not broker or not super_order_engine:
        logger.error("Webhook called but system not initialized")
        return jsonify({
            "status": "error", 
            "message": "System not initialized. Check /health endpoint for details."
        }), 503
    
    try:
        # Force JSON parsing even if Content-Type header is missing
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error", "message": "Invalid or missing JSON payload"}), 400
        
        # 1. Security Check
        if data.get('secret') != SECRET:
            logger.warning("Unauthorized Webhook Attempt")
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
            
        # 2. Extract Key Fields
        timeframe = data.get('timeframe')
        if not timeframe:
             return jsonify({"status": "error", "message": "Missing timeframe"}), 400

        legs = data.get('order_legs', [])
        if not legs:
             return jsonify({"status": "error", "message": "No order legs found"}), 400
             
        # Process each leg
        results = []
        failure_count = 0
        
        for leg in legs:
            # 2.1 Parse Ticker if available
            ticker = leg.get('ticker')
            if ticker:
                match = re.match(r'^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+(\.\d+)?)$', ticker)
                if match:
                    groups = match.groups()
                    leg['symbol'] = groups[0]
                    leg['option_type'] = "CE" if groups[4] == "C" else "PE"
                    leg['strike_price'] = groups[5]
            
            underlying = leg.get('symbol') or leg.get('underlying') or leg.get('ticker')
            if not underlying:
                 logger.error(f"Missing Underlying for leg: {leg}")
                 results.append({"error": "Missing Underlying", "leg": leg})
                 failure_count += 1
                 continue
            
            transaction_type = leg.get('transactionType')
            if not transaction_type:
                logger.error(f"Missing transactionType for leg: {leg}")
                results.append({"error": "Missing transactionType"})
                failure_count += 1
                continue

            quantity = int(leg.get('quantity', 1))
            if quantity <= 0:
                logger.error(f"Invalid quantity {quantity} for leg: {leg}")
                results.append({"error": "quantity must be > 0"})
                failure_count += 1
                continue

            # 3. Process with Ranking Engine (Index-Based)
            mode = leg.get('mode', data.get('mode', 'regular')).lower()
            is_buy = transaction_type in ['B', 'BUY', 'LONG']
            is_sell = transaction_type in ['S', 'SELL', 'SHORT']
            target_side = 'CALL' if is_buy else 'PUT' if is_sell else None

            # Pre-check state: exits don't need ITM resolution (0 API calls)
            current_state = super_order_engine._get_state(underlying)
            current_side = current_state.get('side', 'NONE')

            # Guard: if engine thinks a position is open, verify via broker.
            # Broker closes positions natively (SL/TP); engine state can go stale.
            if current_side != 'NONE' and broker:
                try:
                    live_positions = broker.get_positions() or []
                    underlying_upper = underlying.upper()
                    has_live = any(
                        p.get('netQty', 0) != 0 and underlying_upper in p.get('tradingSymbol', '')
                        for p in live_positions
                    )
                    if not has_live:
                        logger.info(f"Stale engine state for {underlying} ({current_side}) — no live position at broker. Clearing.")
                        _add_activity_log(f"Stale state cleared for {underlying} ({current_side}) — broker has no open position", "🧹 ")
                        super_order_engine._clear_state(underlying)
                        current_side = 'NONE'
                        current_state = {'side': 'NONE'}
                except Exception as e:
                    logger.warning(f"Position verification failed for {underlying}: {e}")

            is_exit = (is_sell and current_side == 'CALL') or (is_buy and current_side == 'PUT')

            # Guard: skip same-direction signal when position already open
            same_direction = (is_buy and current_side == 'CALL') or (is_sell and current_side == 'PUT')
            if same_direction:
                msg = f"SKIPPED: {transaction_type} signal for {underlying} — {current_side} position already open"
                logger.info(msg)
                _add_activity_log(msg, "⏭️ ")
                results.append({"status": "ignored", "action": "SAME_DIRECTION_SKIP", "message": msg})
                continue

            spot_index = 0
            specific_itm = None

            if not is_exit:
                spot_index = resolve_index_spot(broker, underlying, leg)

                # Guard: spot resolution failed (missing 'price' key or broker API error).
                # Dedup is intentionally checked AFTER this so a bad payload doesn't
                # consume the 60s dedup window and block a valid retry.
                if spot_index <= 0:
                    err_msg = f"Spot index resolution failed for {underlying} — missing 'price' in payload or broker LTP unavailable"
                    logger.error(err_msg)
                    trade_feed.insert_trade(
                        underlying=underlying,
                        signal='BUY' if is_buy else 'SELL',
                        status='FAILED',
                        comment='Missing price / spot resolution failed'
                    )
                    results.append({"error": err_msg, "underlying": underlying, "action": "FAILED_SPOT_RESOLUTION"})
                    failure_count += 1
                    continue

                specific_itm = resolve_call_itm(broker, underlying, spot_index) if is_buy else resolve_put_itm(broker, underlying, spot_index)
                if not specific_itm:
                    trade_feed.insert_trade(
                        underlying=underlying,
                        signal='BUY' if is_buy else 'SELL',
                        index_price=spot_index,
                        status='FAILED',
                        comment=f'Could not resolve {target_side} ITM contract'
                    )
                    results.append({"underlying": underlying, "action": "FAILED_CONTEXT_RESOLUTION", "reason": f"Failed to resolve {target_side} ITM contract"})
                    failure_count += 1
                    continue

            # 4. Deduplication Check — placed after spot validation so a bad payload
            #    (missing price) does not consume the dedup window and block valid retries.
            sig_key = f"dedup:{underlying}_{transaction_type}"
            is_duplicate = False
            if redis_client:
                # SET NX EX: only sets if key absent; returns None if already exists
                is_duplicate = not redis_client.set(sig_key, "1", nx=True, ex=60)
            else:
                now = datetime.now()
                with signal_memory_lock:
                    last_time = signal_memory.get(sig_key)
                    if last_time and (now - last_time).total_seconds() < 60:
                        is_duplicate = True
                    else:
                        signal_memory[sig_key] = now

            if is_duplicate:
                msg = f"DEDUPLICATED: Signal {transaction_type} for {underlying} ignored (< 60s ago)"
                logger.info(msg)
                _add_activity_log(msg, "⏭️ ")
                results.append({"status": "ignored", "action": "DEDUPLICATED", "message": msg})
                continue

            msg = f"Received Signal: {transaction_type} for {underlying} on {timeframe}m timeframe"
            logger.info(msg)
            _add_activity_log(msg, "📡 ")

            # Insert trade-feed record so the dashboard can track this signal
            feed_id = trade_feed.insert_trade(
                underlying=underlying,
                signal='BUY' if is_buy else 'SELL',
                index_price=spot_index if spot_index else None,
                option_symbol=specific_itm.get('symbol') if specific_itm else None,
                status='PENDING'
            )
            _set_pending_trade(underlying, feed_id)

            leg_data = {
                "underlying": underlying,
                "target_side": target_side,
                "itm": specific_itm,
                "option_symbol": specific_itm.get("symbol") if specific_itm else None,
                "tv_symbol": specific_itm.get("tv_symbol") if specific_itm else None,
                "spot_index": spot_index,
                "timeframe": timeframe,
                "quantity": quantity,
                "transaction_type": "BUY",
                "timestamp": datetime.now().isoformat(),
                "trade_feed_id": feed_id
            }

            if AI_IN_THE_LOOP:
                logger.info(f"AI-IN-THE-LOOP: Emitting signal event for {underlying}")
                last_signal_storage["data"] = leg_data

                stale = []
                with sse_lock:
                    for q in sse_clients:
                        try:
                            q.put_nowait(leg_data)
                        except queue.Full:
                            stale.append(q)
                    for q in stale:
                        sse_clients.remove(q)
                        logger.info(f"Removed stale SSE client. Active: {len(sse_clients)}")
                    current_listeners = len(sse_clients)

                action = {"status": "success", "action": "SIGNAL_EMITTED", "message": f"Signal broadcast to {current_listeners} listeners"}
            else:
                action = super_order_engine.process_signal(underlying, specific_itm, transaction_type, mode, leg_data)

            results.append(action)

            if action.get('action', '').startswith("FAILED") or action.get('success') is False:
                logger.error(f"Processing Failed for {underlying}: {action}")
                failure_count += 1

        if failure_count > 0:
            logger.error(f"Webhook completed with {failure_count} errors.")
            return jsonify({"status": "error", "actions": results, "message": "One or more orders failed."}), 500
            
        return jsonify({"status": "success", "actions": results}), 200

    except Exception as e:
        logger.error(f"Webhook Processing Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/manual-exit', methods=['POST'])
def manual_exit():
    """
    Kill switch: squares off all net-open positions and cancels every
    pending/open order via the broker, then wipes all local engine state.
    """
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    try:
        result = broker.kill_switch()

        # Wipe all engine state so the bot starts clean
        if redis_client:
            try:
                for pattern in ("state:*", "cond_state:*", "dedup:*"):
                    keys = redis_client.keys(pattern)
                    if keys:
                        redis_client.delete(*keys)
            except Exception as e:
                logger.error(f"Kill Switch: Redis state wipe failed: {e}")
        else:
            if super_order_engine:
                super_order_engine.memory_store.clear()
            if conditional_engine:
                conditional_engine.memory_store.clear()

        n_sq = len(result.get('squaredoff', []))
        n_cx = len(result.get('cancelled', []))
        n_err = len(result.get('errors', []))
        msg = f"Kill Switch: {n_sq} position(s) squared off, {n_cx} order(s) cancelled"
        if n_err:
            msg += f", {n_err} error(s)"
        _add_activity_log(msg, "🔴 ")
        logger.warning(f"KILL SWITCH ACTIVATED — {msg}")

        status_code = 200 if not result.get('errors') else 207
        return jsonify({"status": "success", "message": msg, "result": result}), status_code

    except Exception as e:
        logger.error(f"Kill Switch Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def _get_active_positions():
    """
    Returns active positions enriched with real fill prices from the broker.
    Cross-references engine state (for SL/TGT context) with broker positions (for real buyAvg).
    """
    if not broker or not super_order_engine:
        return []

    # Fetch real broker positions and index by securityId
    try:
        broker_positions = broker.get_positions() or []
    except Exception as e:
        logger.error(f"Failed to fetch broker positions: {e}")
        broker_positions = []

    pos_by_sec_id = {}
    for pos in broker_positions:
        sec_id = str(pos.get('securityId', ''))
        if sec_id and int(pos.get('netQty', 0)) != 0:
            pos_by_sec_id[sec_id] = pos

    active_positions = []
    for underlying in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
        try:
            state = super_order_engine._get_state(underlying)
            if state.get('side', 'NONE') == 'NONE':
                continue

            sec_id = str(state.get('security_id', ''))
            broker_pos = pos_by_sec_id.get(sec_id)

            if broker_pos:
                # Use real fill price from broker
                entry_price = float(broker_pos.get('buyAvg') or broker_pos.get('sellAvg') or 0)
                net_qty = abs(int(broker_pos.get('netQty', 0)))
                unrealized_pnl = float(broker_pos.get('unrealizedProfit', 0))
                # Back-fill entry_price into state if it was 0 (MARKET order not yet updated)
                if entry_price > 0 and float(state.get('entry_price', 0)) == 0:
                    state['entry_price'] = entry_price
                    super_order_engine._set_state(underlying, state)
            else:
                entry_price = float(state.get('entry_price', 0))
                net_qty = int(state.get('quantity', 0))
                unrealized_pnl = 0.0

            ltp_raw = broker.get_ltp(sec_id) if sec_id else None
            ltp = float(ltp_raw) if ltp_raw else 0.0

            if broker_pos:
                pnl_abs = round(unrealized_pnl, 2)
            elif ltp and entry_price:
                pnl_abs = round((ltp - entry_price) * net_qty, 2)
            else:
                pnl_abs = 0.0

            pnl_pct = round(((ltp / entry_price) - 1) * 100, 2) if entry_price > 0 and ltp > 0 else 0.0

            active_positions.append({
                "underlying": underlying,
                "symbol": state.get('symbol'),
                "side": state.get('side'),
                "quantity": net_qty,
                "entry_price": entry_price,
                "ltp": ltp,
                "pnl_abs": pnl_abs,
                "pnl_pct": pnl_pct,
                "sl_price": state.get('sl_price'),
                "tgt_price": state.get('tgt_price'),
            })
        except Exception as e:
            logger.error(f"Error fetching position for {underlying}: {e}")

    return active_positions

@app.route('/get-state', methods=['POST'])
def get_state():
    """
    Get current state (side and last_signal) for a given underlying.
    """
    if not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        underlying = data.get('underlying', 'NIFTY')
        state = super_order_engine._get_state(underlying)
        active_positions = _get_active_positions()

        # Find this underlying's position detail for the dashboard card
        sector_details = next((p for p in active_positions if p.get('underlying') == underlying), None)

        # Reconciliation: broker has no open position but state says active → SL/Target hit natively
        if state.get('side') in ['CALL', 'PUT'] and not sector_details:
            logger.warning(f"Reconciliation: state says {state.get('side')} for {underlying} but broker shows no open position. Clearing.")
            feed_id = state.get('trade_feed_id')
            if feed_id:
                trade_feed.update_trade(feed_id, status='CLOSED', comment='SL / Target hit natively')
            _add_to_history({
                "underlying": underlying,
                "symbol": state.get('symbol'),
                "side": state.get('side'),
                "entry_price": state.get('entry_price', 0),
                "exit_price": None,
                "pnl_abs": None,
                "pnl_pct": None,
                "exit_reason": "NATIVE_BO_HIT",
                "timestamp": datetime.now().isoformat()
            })
            super_order_engine._clear_state(underlying)
            state = super_order_engine._get_state(underlying)

        # Capture mock broker completed trades if running in test mode
        if hasattr(broker, 'get_completed_trades'):
            for trade in broker.get_completed_trades():
                _add_to_history(trade)

        return jsonify({
            "status": "success",
            "state": state,
            "active_positions": active_positions,
            "sector_details": sector_details,
        }), 200
    except Exception as e:
        logger.error(f"Get State Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get-ltp', methods=['POST'])
def get_ltp():
    """
    Get current Last Traded Price (LTP) for a specific instrument.
    Payload: { "secret": "...", "instrument": "NIFTY" | "BANKNIFTY" | "FINNIFTY" | "1234" }
    """
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    instrument = data.get('instrument', 'NIFTY').upper()
    try:
        # 1. Check if it's a known index symbol
        idx_id = broker.get_index_id(instrument)
        if idx_id:
            # Use Index segment for Dhan
            ltp = broker.get_ltp(idx_id, exchange_segment="IDX_I")
        else:
            # 2. Assume it's a security ID or exact symbol
            ltp = broker.get_ltp(instrument)
            
        if ltp is not None:
            return jsonify({"status": "success", "instrument": instrument, "ltp": float(ltp)}), 200
        else:
            return jsonify({"status": "error", "message": f"Could not fetch LTP for {instrument}"}), 404
    except Exception as e:
        logger.error(f"Get LTP Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/get-itm', methods=['POST'])
def get_itm():
    """
    Resolve the current ITM option contract for a given underlying and side.
    Payload: { "secret": "...", "underlying": "NIFTY", "side": "CE" | "PE", "spot_index": <optional float> }
    Returns: { security_id, symbol, strike, expiry, spot_index }
    """
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY').upper()
    side = data.get('side', 'CE').upper()

    try:
        spot_index = resolve_index_spot(broker, underlying, data)
        if spot_index <= 0:
            return jsonify({"status": "error", "message": f"Could not determine spot index for {underlying}"}), 400

        if side == 'CE':
            contract = resolve_call_itm(broker, underlying, spot_index)
        else:
            contract = resolve_put_itm(broker, underlying, spot_index)

        if not contract:
            return jsonify({"status": "error", "message": f"Failed to resolve {side} ITM contract for {underlying}"}), 400

        return jsonify({
            "status": "success",
            "underlying": underlying,
            "side": side,
            "spot_index": spot_index,
            **contract
        }), 200
    except Exception as e:
        logger.error(f"Get ITM Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get-margin', methods=['POST'])
def get_margin():
    """
    Returns available balance and per-lot margin for the current ITM option.
    Payload: { secret, underlying, side }
    """
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY').upper()
    side = data.get('side', 'PUT').upper()

    try:
        # 1. Available balance
        fund_resp = broker.get_fund_limits()
        fund_data = (fund_resp.get('data') or {})
        available = float(
            fund_data.get('availabelBalance') or
            fund_data.get('availableBalance') or 0
        )

        # 2. Resolve ITM contract
        spot_index = resolve_index_spot(broker, underlying, {})
        itm = resolve_call_itm(broker, underlying, spot_index) if side == 'CALL' else resolve_put_itm(broker, underlying, spot_index)
        if not itm:
            return jsonify({"status": "error", "message": f"Could not resolve ITM contract for {underlying} {side}"}), 400

        sec_id = itm['security_id']
        lot_size = broker.lot_map.get(str(sec_id), 1)

        # 3. Margin per lot via Dhan margin calculator
        ltp = broker.get_ltp(sec_id)
        if not ltp or float(ltp) <= 0:
            logger.error(f"get-margin: LTP fetch failed for sec_id={sec_id} ({itm.get('symbol')})")
            return jsonify({
                "status": "error",
                "message": f"LTP unavailable for {itm.get('symbol')} (sec_id={sec_id}). Cannot calculate margin.",
                "security_id": sec_id,
                "symbol": itm.get('symbol'),
                "available_balance": available,
            }), 400
        ltp = float(ltp)

        margin_resp = broker.margin_calculator({
            'security_id': sec_id,
            'exchange_segment': 'NSE_FNO',
            'transaction_type': 'BUY',
            'quantity': lot_size,
            'product_type': 'INTRADAY',
            'price': ltp,
        })
        logger.info(f"get-margin margin_resp: {margin_resp}")

        if margin_resp.get('status') != 'success':
            return jsonify({
                "status": "error",
                "message": f"Margin calculator API failed: {margin_resp.get('message') or margin_resp.get('remarks') or margin_resp}",
                "margin_raw": margin_resp,
                "security_id": sec_id,
                "symbol": itm.get('symbol'),
                "ltp": ltp,
                "available_balance": available,
            }), 400

        margin_per_lot = float((margin_resp.get('data') or {}).get('totalMarginRequired') or 0)
        if margin_per_lot <= 0:
            logger.error(f"get-margin: totalMarginRequired=0 despite success. margin_resp={margin_resp}")
            return jsonify({
                "status": "error",
                "message": "Margin calculator returned 0. Check security_id or LTP.",
                "margin_raw": margin_resp,
                "security_id": sec_id,
                "ltp": ltp,
                "available_balance": available,
            }), 400

        import math
        suggested_lots = max(1, math.floor(available * 0.8 / margin_per_lot))

        return jsonify({
            "status": "success",
            "underlying": underlying,
            "side": side,
            "symbol": itm['symbol'],
            "security_id": sec_id,
            "lot_size": lot_size,
            "ltp": ltp,
            "available_balance": available,
            "margin_per_lot": margin_per_lot,
            "suggested_lots": suggested_lots,
        }), 200
    except Exception as e:
        logger.error(f"Get Margin Error: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/fundlimit', methods=['POST', 'GET'])
def fund_limit():
    """
    Retrieve available fund limits (availableBalance).
    """
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
    
    # Support both GET and POST (for secret)
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True)
        if not data or data.get('secret') != SECRET:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
    else:
        sec = request.args.get('secret')
        if sec != SECRET:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

    try:
        res = broker.get_fund_limits()
        return jsonify(res), 200
    except Exception as e:
        logger.error(f"Fund Limit Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/margincalculator', methods=['POST'])
def margin_calculator():
    """
    Calculate margin for a single order.
    Payload: { secret, security_id, exchange_segment, transaction_type, quantity, product_type, price }
    """
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
    
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        # Extract order data (remove secret)
        order_data = data.copy()
        order_data.pop('secret', None)
        res = broker.margin_calculator(order_data)
        return jsonify(res), 200
    except Exception as e:
        logger.error(f"Margin Calc Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/margincalculator/multi', methods=['POST'])
def margin_calculator_multi():
    """
    Calculate margin for multiple orders.
    Payload: { secret, orders: [...] }
    """
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
    
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    orders = data.get('orders', [])
    try:
        res = broker.get_multi_margin_calculator(orders)
        return jsonify(res), 200
    except Exception as e:
        logger.error(f"Multi Margin Calc Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get-history', methods=['POST'])
def get_history():
    """
    Returns the persistent trade history.
    """
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        history = _load_history()
        # Return reversed to show newest first
        return jsonify({
            "status": "success",
            "history": list(reversed(history))
        }), 200
    except Exception as e:
        logger.error(f"Get History Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/activity-logs', methods=['POST', 'GET'])
def get_activity_logs():
    """
    Returns the most recent system activity logs (signals received, orders placed).
    """
    data = request.get_json(force=True, silent=True) or {}
    # We still allow fetching logs safely if secrets match, or skip if internal dashboard UI does it passively.
    # We will enforce secret check to match the existing UI logic.
    if data and data.get('secret') and data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    # Try fetching from Redis first
    try:
        r = None
        if super_order_engine and super_order_engine.use_redis:
            r = super_order_engine.r
        elif conditional_engine and conditional_engine.use_redis:
            r = conditional_engine.r
            
        if r:
            logs = r.lrange("activity_logs", 0, 49)
            if logs:
                return jsonify({"status": "success", "logs": logs}), 200
    except Exception as e:
        logger.error(f"Error fetching logs from Redis: {e}")

    # Fallback to in-memory deque
    return jsonify({"status": "success", "logs": list(activity_logs)}), 200


@app.route('/server-logs', methods=['POST', 'GET'])
def server_logs():
    """
    Returns recent WARNING/ERROR/CRITICAL log entries captured in memory.
    Useful for remote debugging when SSH is unavailable.
    """
    data = request.get_json(force=True, silent=True) or {}
    if data.get('secret') and data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    n = int(data.get('n', 100))
    logs = list(_error_log_buffer)[-n:]
    return jsonify({"status": "success", "count": len(logs), "logs": logs}), 200


@app.route('/conditional-order', methods=['POST'])
def conditional_order():
    """
    Programmatic/AI entry point for manual UI signals.
    """
    if not broker or not conditional_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    underlying = data.get('underlying', 'NIFTY').upper()
    action = data.get('action') # 'CALL', 'PUT', 'EXIT_CALL', 'EXIT_PUT'
    
    mapping = {
        'CALL': 'B',
        'PUT': 'S',
        'EXIT_CALL': 'LONG_EXIT',
        'EXIT_PUT': 'SHORT_EXIT'
    }
    
    signal_type = mapping.get(action)
    if not signal_type:
        return jsonify({"status": "error", "message": f"Invalid action: {action}"}), 400
        
    try:
        # 1. Resolve spot first — guard before any ITM resolution
        spot_index = resolve_index_spot(broker, underlying, data)
        if spot_index <= 0:
            return jsonify({"status": "error", "message": "Could not determine current index spot price. Cannot validate SL/Target."}), 400

        index_ids = {"NIFTY": "13", "BANKNIFTY": "25", "FINNIFTY": "27"}
        idx_sec_id = index_ids.get(underlying.upper())

        side = 'CALL' if signal_type == 'B' else 'PUT'
        itm = resolve_call_itm(broker, underlying, spot_index) if side == 'CALL' else resolve_put_itm(broker, underlying, spot_index)

        if not itm or not idx_sec_id:
            return jsonify({"status": "error", "message": "Failed to resolve ITM contract or Index ID"}), 400

        # Prefer explicit feed_id passed by Claude; fall back to Redis lookup
        feed_id = data.get('trade_feed_id') or _get_pending_trade(underlying)
        if not feed_id:
            logger.warning(f"/conditional-order: no trade_feed_id for {underlying} — feed record will be orphaned")

        leg_data = {
            "underlying": underlying,
            "itm": itm,
            "idx_sec_id": idx_sec_id,
            "quantity": int(data.get('quantity') or 1),
            "spot_index": spot_index,
            "sl_index": data.get('sl_index'),
            "target_index": data.get('target_index'),
            "trade_feed_id": feed_id,
        }

        if signal_type in ('B', 'S'):
            if not leg_data.get('sl_index') or not leg_data.get('target_index'):
                label = "CALL" if signal_type == 'B' else "PUT"
                return jsonify({"status": "error", "message": f"Manual {label} requires Index Stop Loss and Target levels"}), 400

            try:
                sl_idx_val = float(leg_data['sl_index'])
                tgt_idx_val = float(leg_data['target_index'])
            except (TypeError, ValueError) as e:
                return jsonify({"status": "error", "message": f"Invalid SL/Target index value: {e}"}), 400

            if signal_type == 'B':
                if sl_idx_val >= spot_index:
                    return jsonify({"status": "error", "message": f"CALL SL ({sl_idx_val}) must be below spot ({spot_index})"}), 400
                if tgt_idx_val <= spot_index:
                    return jsonify({"status": "error", "message": f"CALL Target ({tgt_idx_val}) must be above spot ({spot_index})"}), 400
            if signal_type == 'S':
                if sl_idx_val <= spot_index:
                    return jsonify({"status": "error", "message": f"PUT SL ({sl_idx_val}) must be above spot ({spot_index})"}), 400
                if tgt_idx_val >= spot_index:
                    return jsonify({"status": "error", "message": f"PUT Target ({tgt_idx_val}) must be below spot ({spot_index})"}), 400

        # Execute Order via Conditional Engine
        res = conditional_engine.handle_signal(signal_type, leg_data)
        
        # Acceptance Criteria: Defer GTT placement until order is TRADED (Fill-Triggered)
        if res.get('status') == 'success' and signal_type in ['B', 'S'] and leg_data.get('sl_index') and leg_data.get('target_index'):
            order_id = res.get('order_id')
            if order_id:
                logger.info(f"Deferring GTT placement for Order {order_id} until fill confirmation.")
                pending_meta = {
                    "underlying": underlying,
                    "target_level": leg_data['target_index'],
                    "sl_level": leg_data['sl_index'],
                    "quantity": leg_data['quantity']
                }
                conditional_engine.store_pending_protection(order_id, pending_meta)
                res['gtt_status'] = {"status": "pending", "message": "Queued for fill trigger"}
            
        return jsonify(res), 200
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Conditional Order Error: {e}\n{tb}")
        return jsonify({"status": "error", "message": str(e), "traceback": tb}), 500

@app.route('/level-hit', methods=['POST'])
def level_hit():
    """
    Dedicated endpoint for level crossings.
    Triggers the SL trailing logic (LEVEL_CROSS signal).
    """
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        results = []
        legs = data.get('order_legs', [])
        mode = data.get('mode', 'regular').lower()
        
        # If order_legs is provided, process each
        if legs:
            for leg in legs:
                underlying = leg.get('symbol') or leg.get('underlying') or leg.get('ticker') or 'NIFTY'
                leg_mode = leg.get('mode', mode).lower()
                
                # NEW: Resolve Context for LEVEL_CROSS (Reversals might need it)
                spot_index = resolve_index_spot(broker, underlying, leg)
                itm_ce = resolve_call_itm(broker, underlying, spot_index)
                itm_pe = resolve_put_itm(broker, underlying, spot_index)
                
                if itm_ce and itm_pe:
                    leg['itm_ce'] = itm_ce
                    leg['itm_pe'] = itm_pe
                    leg['spot_index'] = spot_index
                
                # For LEVEL_CROSS, we pass itm_ce as a generic starting point; engine identifies active side from holdings
                action = super_order_engine.process_signal(underlying, itm_ce, 'LEVEL_CROSS', leg_mode, leg)
                results.append(action)
        else:
            # Fallback for simple payload: {"secret": "...", "underlying": "NIFTY"}
            underlying = data.get('underlying') or data.get('ticker') or 'NIFTY'
            leg_data = data
            
            # Resolve Context
            spot_index = resolve_index_spot(broker, underlying, leg_data)
            itm_ce = resolve_call_itm(broker, underlying, spot_index)
            itm_pe = resolve_put_itm(broker, underlying, spot_index)
            
            if itm_ce and itm_pe:
                leg_data['itm_ce'] = itm_ce
                leg_data['itm_pe'] = itm_pe
                leg_data['spot_index'] = spot_index

            action = super_order_engine.process_signal(underlying, itm_ce, 'LEVEL_CROSS', mode, leg_data)
            results.append(action)
            
        return jsonify({"status": "success", "actions": results}), 200
    except Exception as e:
        logger.error(f"Level Hit Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500




@app.route('/dhan-postback', methods=['POST'])
def dhan_postback():
    """
    Catch-all endpoint for Dhan Postback notifications.
    Suggested URL: http://65.20.83.74/dhan-postback?secret=YOUR_WEBHOOK_SECRET
    """
    try:
        # Validate secret from URL query params
        income_secret = request.args.get('secret')
        if income_secret != SECRET:
            logger.warning(f"Unauthorized Postback attempt with secret: {income_secret}")
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
            
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400
            
        
        # Execute Dedicated Condition Order Engine parsing
        res = conditional_engine.handle_postback(data)
        if res.get('status') == 'success':
            return jsonify({"status": "success", "message": res.get('message', 'Processed')}), 200
        else:
            return jsonify(res), 200

    except Exception as e:
        logger.error(f"Dhan Postback Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/conditional-index-order', methods=['POST'])
def set_conditional_index_orders():
    """
    Creates Dhan Conditional Trigger orders (GTT) based on INDEX LEVELS.
    """
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY').upper()
    target_level = data.get('target_level')
    sl_level = data.get('sl_level')
    quantity = data.get('quantity') # Lots

    if not target_level or not sl_level:
        return jsonify({"status": "error", "message": "target_level and sl_level are required"}), 400

    try:
        # NEW: Ensure idx_sec_id is available even for manual protection
        index_ids = {"NIFTY": "13", "BANKNIFTY": "25", "FINNIFTY": "27"}
        idx_sec_id = index_ids.get(underlying.upper())
        
        # Inject into state if missing (rare legacy positions)
        state = conditional_engine._get_state(underlying)
        if not state.get('idx_sec_id') and idx_sec_id:
            logger.info(f"Injecting missing idx_sec_id {idx_sec_id} into state for {underlying}")
            state['idx_sec_id'] = idx_sec_id
            conditional_engine._set_state(underlying, state)

        res = conditional_engine.set_index_boundaries(underlying, target_level, sl_level, quantity)
        if res.get('status') == 'success':
            return jsonify(res), 200
        else:
            return jsonify(res), 500
    except Exception as e:
        logger.error(f"Error in conditional-index-order: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route('/super-order', methods=['POST'])
def set_super_order():
    """
    Places a Native Super Order (Bracket) with absolute target/SL prices.
    Intended for AI (Claude MCP) and direct API calls.
    """
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY').upper()
    side = data.get('side', 'CALL').upper()       # CALL or PUT
    target = data.get('target_price')
    sl = data.get('sl_price')

    if not target or not sl:
        return jsonify({"status": "error", "message": "target_price and sl_price are required"}), 400
    if side not in ('CALL', 'PUT'):
        return jsonify({"status": "error", "message": "side must be CALL or PUT"}), 400

    try:
        option_symbol = data.get('option')
        security_id = data.get('security_id')

        if option_symbol and security_id:
            # ITM already resolved in webhook — use directly, skip broker API call
            itm = {"symbol": option_symbol, "security_id": security_id}
        else:
            spot_index = resolve_index_spot(broker, underlying, data)
            itm = resolve_call_itm(broker, underlying, spot_index) if side == 'CALL' else resolve_put_itm(broker, underlying, spot_index)
            if not itm:
                return jsonify({"status": "error", "message": f"Failed to resolve {side} ITM contract for {underlying}"}), 400

        quantity = int(data.get('quantity') or 1)

        # Prefer explicit feed_id passed by Claude; fall back to Redis lookup
        feed_id = data.get('trade_feed_id') or _get_pending_trade(underlying)
        if not feed_id:
            logger.warning(f"/super-order: no trade_feed_id for {underlying} — feed record will be orphaned")

        result = super_order_engine.place_super_order(
            underlying=underlying,
            side=side,
            quantity=quantity,
            itm=itm,
            target_price=float(target),
            stop_loss_price=float(sl),
        )
        if result.get('success'):
            # Persist feed_id in engine state so dhan_webhook and exit can find it
            state = super_order_engine._get_state(underlying)
            state['trade_feed_id'] = feed_id
            super_order_engine._set_state(underlying, state)
            if feed_id:
                trade_feed.update_trade(feed_id, sl_price=float(sl), target_price=float(target), status='ACTIVE')
        else:
            if feed_id:
                trade_feed.update_trade(feed_id, status='FAILED', comment=result.get('error', 'Place order failed'))
        code = 200 if result.get('success') else 400
        return jsonify(result), code
    except Exception as e:
        logger.error(f"Super Order Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/update-super-order', methods=['POST'])
def update_super_order():
    """
    Updates the target and sl legs of an active Premium-based Super Order.
    Payload: { secret, underlying, target_price, sl_price }
    """
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    underlying = data.get('underlying', 'NIFTY').upper()
    target = data.get('target_price')
    sl = data.get('sl_price')

    if not target and not sl:
         return jsonify({"status": "error", "message": "At least one of target_price or sl_price is required"}), 400

    try:
        state = super_order_engine._get_state(underlying)
        entry_id = state.get('entry_id')
        if not entry_id or state.get('side', 'NONE') == 'NONE':
            return jsonify({"status": "error", "message": "No active Super Order found for underlying"}), 400

        target_res = {"success": True}
        if target:
            broker.modify_super_target_leg(entry_id, float(target))
            target_res["modified"] = True

        sl_res = {"success": True}
        if sl:
            broker.modify_super_sl_leg(entry_id, float(sl), 1.0)
            sl_res["modified"] = True

        return jsonify({"status": "success", "target_update": target_res, "sl_update": sl_res}), 200
    except Exception as e:
        logger.error(f"Update Super Order Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/cancel-super-order', methods=['POST'])
def cancel_super_order():
    """Cancels the pending (unfilled) entry leg of an active Super Order."""
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY').upper()
    try:
        # Read feed_id before engine clears state
        pre_state = super_order_engine._get_state(underlying)
        feed_id = pre_state.get('trade_feed_id')

        result = super_order_engine.cancel_super_order(underlying)
        if result.get('success') and feed_id:
            trade_feed.update_trade(feed_id, status='CLOSED', comment='Order cancelled')
        code = 200 if result.get('success') else 400
        return jsonify(result), code
    except Exception as e:
        logger.error(f"Cancel Super Order Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/exit-super-order', methods=['POST'])
def exit_super_order():
    """Exits (squares off) an active Super Order position at market price."""
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY').upper()
    try:
        pre_state = super_order_engine._get_state(underlying)
        feed_id = pre_state.get('trade_feed_id')
        entry_price = float(pre_state.get('entry_price') or 0)
        qty = int(pre_state.get('quantity') or 1)

        result = super_order_engine.exit_super_order(underlying)
        if result.get('success'):
            exit_order_id = str(result.get('exit', {}).get('order_id', ''))
            if feed_id and exit_order_id:
                # Store meta so WS listener can write the real fill price when TRADED fires
                _set_exit_order_meta(exit_order_id, {
                    'feed_id': feed_id,
                    'entry_price': entry_price,
                    'qty': qty,
                })
                logger.info(f"Exit order {exit_order_id} queued — awaiting WS fill for {underlying}")
            elif feed_id:
                # No order_id returned (dry-run / mock) — mark closed without price
                trade_feed.update_trade(feed_id, status='CLOSED', comment='Manual exit')

        if result.get('success') and pre_state.get('side') in ('CALL', 'PUT'):
            _add_to_history({
                "underlying": underlying,
                "symbol": pre_state.get('symbol'),
                "side": pre_state.get('side'),
                "entry_price": pre_state.get('entry_price', 0),
                "exit_price": None,
                "pnl_abs": None,
                "pnl_pct": None,
                "exit_reason": "MANUAL_EXIT",
                "timestamp": datetime.now().isoformat()
            })
        code = 200 if result.get('success') else 400
        return jsonify(result), code
    except Exception as e:
        logger.error(f"Exit Super Order Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/exit-conditional-order', methods=['POST'])
def exit_conditional_order():
    """Exits (squares off) an active Conditional Order position at market price."""
    if not broker or not conditional_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY').upper()
    try:
        state = conditional_engine._get_state(underlying)
        side = state.get('side', 'NONE')
        if side == 'NONE':
            return jsonify({"status": "error", "message": f"No active conditional position for {underlying}"}), 400
        exit_signal = 'LONG_EXIT' if side == 'CALL' else 'SHORT_EXIT'
        result = conditional_engine.handle_signal(exit_signal, {'underlying': underlying})
        code = 200 if result.get('status') == 'success' else 400
        return jsonify(result), code
    except Exception as e:
        logger.error(f"Exit Conditional Order Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/positions', methods=['POST'])
def get_broker_positions():
    """Returns all current open positions from Dhan."""
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    try:
        positions = broker.get_positions()
        return jsonify({"status": "success", "positions": positions}), 200
    except Exception as e:
        logger.error(f"Positions Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/orders', methods=['POST'])
def get_broker_orders():
    """Returns the full order book from Dhan."""
    if not broker:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    try:
        orders = broker.get_all_orders()
        return jsonify({"status": "success", "orders": orders}), 200
    except Exception as e:
        logger.error(f"Orders Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/skip-trade', methods=['POST'])
def skip_trade():
    """
    Called by Claude when it decides NOT to place an order for a received signal.
    Marks the pending feed record as closed with the given reason.
    Payload: { secret, underlying, reason }
    """
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY').upper()
    reason = data.get('reason', 'Skipped by AI')

    feed_id = _get_pending_trade(underlying)
    if feed_id:
        trade_feed.update_trade(feed_id, status='CLOSED', comment=reason)
        logger.info(f"Trade skipped for {underlying}: {reason}")
    else:
        logger.warning(f"/skip-trade: no pending feed record for {underlying}")

    return jsonify({"status": "success", "feed_id": feed_id, "reason": reason}), 200


@app.route('/trade-feed', methods=['POST'])
def get_trade_feed():
    """Returns the last 50 structured trade events for the dashboard feed table."""
    data = request.get_json(force=True, silent=True) or {}
    if data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        trades = trade_feed.get_recent_trades(50)
        return jsonify({"status": "success", "trades": trades}), 200
    except Exception as e:
        logger.error(f"Trade Feed Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/range-signal', methods=['POST'])
def range_signal():
    """
    Update the status of the price relative to the Range Tracker.
    Payload: { secret, underlying, status ('ABOVE'|'BELOW'|'INSIDE') }
    """
    if not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY')
    position = data.get('position', 'INSIDE').upper()

    try:
        state = super_order_engine._get_state(underlying)
        state['range_position'] = position
        state['range_timestamp'] = datetime.now().isoformat()
        super_order_engine._set_state(underlying, state)

        msg = f"Range Position for {underlying}: {position}"
        logger.info(msg)
        _add_activity_log(msg, "🧭 ")

        return jsonify({"status": "success", "range_position": position}), 200
    except Exception as e:
        logger.error(f"Range Signal Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/cancel-conditional-orders', methods=['POST'])
def cancel_conditional_orders():
    """
    Cancels active GTT conditional orders for a position.
    Payload: { secret, underlying }
    """
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY')
    try:
        state = super_order_engine._get_state(underlying)
        tgt_id = state.get('conditional_target_alert_id')
        sl_id = state.get('conditional_sl_alert_id')

        results = []
        for alert_id in filter(None, [tgt_id, sl_id]):
            r = broker.cancel_conditional_order(alert_id)
            results.append({"alert_id": alert_id, "cancelled": r.get("success")})

        # Clear from state
        for key in ('conditional_target_alert_id', 'conditional_sl_alert_id',
                    'conditional_target_price', 'conditional_sl_price'):
            state.pop(key, None)
        super_order_engine._set_state(underlying, state)

        msg = f"GTT orders cancelled for {underlying}"
        _add_activity_log(msg, "❌ ")

        return jsonify({"status": "success", "cancelled": results}), 200
    except Exception as e:
        logger.error(f"Cancel Conditional Orders Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/set-levels', methods=['POST'])
def set_levels():
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    levels = data.get('levels', {})
    _save_levels(levels)
    return jsonify({"status": "success", "message": "Levels saved"}), 200

@app.route('/get-levels', methods=['POST'])
def get_levels():
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    return jsonify({"status": "success", "levels": _load_levels()}), 200

@app.route('/set-context', methods=['POST'])
def set_context():
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    context_text = data.get('context', '')
    _save_context(context_text)
    return jsonify({"status": "success", "message": "Context saved"}), 200

@app.route('/get-context', methods=['POST'])
def get_context():
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    return jsonify({"status": "success", "context": _load_context()}), 200

@app.route('/update-token', methods=['POST'])
def update_token():
    """
    Endpoint to update Dhan Access Token dynamically.
    Expected Payload: {"secret": "...", "token": "..."}
    """
    # Check if broker is initialized
    if not broker:
        return jsonify({
            "status": "error", 
            "message": "Broker not initialized. Check /health endpoint."
        }), 503
    
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    new_token = data.get('token')
    if not new_token:
        return jsonify({"status": "error", "message": "Missing token"}), 400
    
    success = broker.refresh_client(new_token)
    if success:
        return jsonify({"status": "success", "message": "Dhan token updated and client re-initialized"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to update token"}), 500

@app.route('/auth/initiate', methods=['POST'])
def auth_initiate():
    """
    Step 1: Get Dhan Consent URL and return to frontend.
    """
    # Check if broker is initialized
    if not broker:
        return jsonify({
            "status": "error", 
            "message": "Broker not initialized. Check /health endpoint."
        }), 503
    
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    consent_url = broker.get_consent_url()
    if consent_url:
        return jsonify({"status": "success", "url": consent_url}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to generate consent URL"}), 500

@app.route('/auth/callback')
def auth_callback():
    """
    Step 3: Receive tokenId from Dhan redirect and finalize authentication.
    """
    # Check if broker is initialized
    if not broker:
        return "Broker not initialized. Please check server configuration.", 503
    
    token_id = request.args.get('tokenId')
    if not token_id:
        return "Authentication Error: Missing tokenId", 400
    
    success, message = broker.consume_consent(token_id)
    if success:
        return render_template('index.html', auth_status="success")
    else:
        return f"Authentication Failed: {message}", 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 80))
    app.run(host='0.0.0.0', port=port)
