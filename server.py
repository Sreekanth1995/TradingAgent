import re
import json
import logging
import threading
import time
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from super_order_engine import SuperOrderEngine
from conditional_order_engine import ConditionalOrderEngine
from broker_dhan import DhanClient
from collections import deque
from datetime import datetime
import pytz
from instrument_resolver import resolve_index_spot, resolve_call_itm, resolve_put_itm

# Load Environment Variables
load_dotenv()

# Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SECRET = os.getenv("WEBHOOK_SECRET", "60pgS") # Default from user example

# Logging Setup
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Activity Logs (In-memory fallback + Redis persistence)
activity_logs = deque(maxlen=50)

def _add_activity_log(msg, prefix=""):
    """
    Appends a log entry to the in-memory deque and persists it to Redis if available.
    """
    timestamp = datetime.now().strftime('%H:%M:%S')
    full_msg = f"[{timestamp}] {prefix}{msg}"
    
    # Update memory fallback
    activity_logs.appendleft(full_msg)
    
    # Persist to Redis via engines if possible
    try:
        r = None
        if super_order_engine and super_order_engine.use_redis:
            r = super_order_engine.r
        elif conditional_engine and conditional_engine.use_redis:
            r = conditional_engine.r
            
        if r:
            r.lpush("activity_logs", full_msg)
            r.ltrim("activity_logs", 0, 49) # Keep last 50
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
        broker = MockDhanClient()
        logger.info("🛠️  Running in MOCK API MODE - Using broker_mock.py")
    else:
        from broker_dhan import DhanClient
        broker = DhanClient()
        logger.info("🔗 Running in LIVE API MODE - Using broker_dhan.py")
        
    super_order_engine = SuperOrderEngine(broker)
    conditional_engine = ConditionalOrderEngine(broker)
    
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

# In-memory stores (persisted to JSON files for restart survival)
_LEVELS_FILE = "levels.json"
_CONTEXT_FILE = "ai_context.txt"
_HISTORY_FILE = "trade_history.json"

def _load_history():
    try:
        if os.path.exists(_HISTORY_FILE):
             with open(_HISTORY_FILE) as f:
                 return json.load(f)
        return []
    except Exception as e:
        logger.error(f"Error loading history: {e}")
        return []

def _save_history(data):
    try:
        with open(_HISTORY_FILE, 'w') as f:
            json.dump(data[-50:], f) # Keep last 50 trades
    except Exception as e:
        logger.error(f"Error saving history: {e}")

def _add_to_history(trade):
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
    Health check endpoint for Railway and monitoring.
    """
    status = {
        "status": "healthy" if broker and super_order_engine else "degraded",
        "broker_initialized": broker is not None,
        "engine_initialized": super_order_engine is not None,
        "error": init_error
    }
    return jsonify(status), 200



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
        logger.info(f"DEBUG - Received Payload: {data}")
        
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
            
            msg = f"Received Signal: {transaction_type} for {underlying} on {timeframe}m timeframe"
            logger.info(msg)
            _add_activity_log(msg, "📡 ")

            # 4. Process with Ranking Engine (Index-Based)
            mode = leg.get('mode', data.get('mode', 'regular')).lower()
            
            # Resolve ITM context for engines
            spot_index = resolve_index_spot(broker, underlying, leg)
            itm_ce = resolve_call_itm(broker, underlying, spot_index)
            itm_pe = resolve_put_itm(broker, underlying, spot_index)
            
            # Identify specific target instrument based on signal
            target_side = 'CALL' if transaction_type in ['B', 'BUY', 'LONG'] else 'PUT' if transaction_type in ['S', 'SELL', 'SHORT'] else None
            specific_itm = itm_ce if target_side == 'CALL' else itm_pe if target_side == 'PUT' else itm_ce # Fallback to CE for exits/crosses
            
            if not itm_ce or not itm_pe:
                action = {"underlying": underlying, "action": "FAILED_CONTEXT_RESOLUTION", "reason": "Failed to resolve CE/PE ITM contracts"}
            else:
                leg_data = {
                    "underlying": underlying,
                    "target_side": target_side,
                    "itm_ce": itm_ce,
                    "itm_pe": itm_pe,
                    "spot_index": spot_index,
                    "quantity": leg.get('quantity', 1)
                }
                action = super_order_engine.process_signal(underlying, specific_itm, transaction_type, mode, leg_data)

                # Inject resolved context into leg data
                leg['itm_ce'] = itm_ce
                leg['itm_pe'] = itm_pe
                leg['spot_index'] = spot_index
            
            results.append(action)
            
            # Check for Logic Failures
            if action.get('action', '').startswith("FAILED"):
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
    Emergency Exit: Close all positions and reset ranks manually.
    """
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        super_order_engine.manual_exit_all()
        return jsonify({"status": "success", "message": "All positions closed and ranks reset successfully."}), 200
    except Exception as e:
        logger.error(f"Manual Exit Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def _get_active_positions():
    """
    Aggregates active positions across NIFTY, BANKNIFTY, and FINNIFTY.
    Fetches live LTP for PnL calculation.
    """
    if not broker or (not super_order_engine and not conditional_engine):
        return []
    
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
    active_positions = []
    
    for underlying in indices:
        try:
            state = super_order_engine._get_state(underlying) if super_order_engine else {}
            cond_state = conditional_engine._get_state(underlying) if conditional_engine else {}
            
            # Merge state conditionally
            active_state = {}
            if state and state.get('side', 'NONE') != 'NONE':
                active_state = state.copy()
            if cond_state and cond_state.get('side', 'NONE') != 'NONE':
                active_state.update(cond_state)

            if active_state and active_state.get('side', 'NONE') != 'NONE':
                # Fetch LTP for the specific contract if symbol is present
                symbol = active_state.get('symbol')
                security_id = active_state.get('security_id')
                entry_price = float(active_state.get('entry_price', 0))
                qty = int(active_state.get('quantity', 0))
                
                # Fetch Live LTP
                ltp = broker.get_ltp(security_id) if security_id else None
                
                # Calculate PnL only if LTP was successfully fetched
                if ltp is not None:
                    ltp = float(ltp)
                    pnl_abs = (ltp - entry_price) * qty
                    pnl_pct = ((ltp / entry_price) - 1) * 100 if entry_price > 0 else 0.0
                    
                    active_positions.append({
                        "underlying": underlying,
                        "symbol": symbol,
                        "side": active_state.get('side'),
                        "quantity": qty,
                        "entry_price": entry_price,
                        "ltp": ltp,
                        "pnl_abs": round(pnl_abs, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "strike": active_state.get('strike'),
                        "option_type": active_state.get('option_type'),
                        "range_position": active_state.get('range_position', 'INSIDE'),
                        "idx_target_level": cond_state.get('idx_target_level') or state.get('idx_target_level'),
                        "idx_sl_level": cond_state.get('idx_sl_level') or state.get('idx_sl_level'),
                        "tgt_price": state.get('tgt_price') or state.get('conditional_target_price') or cond_state.get('tgt_price'),
                        "sl_price": state.get('sl_price') or state.get('conditional_sl_price') or cond_state.get('sl_price')
                    })
                else:
                    # Fallback if LTP is missing: use last cached state if available 
                    # but for now we just skip the PnL update to avoid showing 0.
                    logger.warning(f"LTP unavailable for {symbol}, skipping PnL update.")
                    active_positions.append({
                        "underlying": underlying,
                        "symbol": symbol,
                        "side": active_state.get('side'),
                        "quantity": qty,
                        "entry_price": entry_price,
                        "ltp": 0.0, # Visual indicator of stale price
                        "pnl_abs": 0.0,
                        "pnl_pct": 0.0,
                        "strike": active_state.get('strike'),
                        "option_type": active_state.get('option_type'),
                        "range_position": active_state.get('range_position', 'INSIDE'),
                        "idx_target_level": cond_state.get('idx_target_level') or state.get('idx_target_level'),
                        "idx_sl_level": cond_state.get('idx_sl_level') or state.get('idx_sl_level'),
                        "tgt_price": state.get('tgt_price') or state.get('conditional_target_price') or cond_state.get('tgt_price'),
                        "sl_price": state.get('sl_price') or state.get('conditional_sl_price') or cond_state.get('sl_price')
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
        # Backward compatibility for single underlying requests
        underlying = data.get('underlying', 'NIFTY')
        state = super_order_engine._get_state(underlying)
        
        # New: Aggregate active positions for dashboard
        active_positions = _get_active_positions()

        # Sector Mapping: Pair positions with UI cards
        # We check if either engine state matches the position's side
        current_pnl = 0
        active_pos_details = None
        
        # Merge engine sides to find what the system THINKS is active
        cond_state = conditional_engine._get_state(underlying) if conditional_engine else {}
        system_active_side = state.get('side', 'NONE')
        if system_active_side == 'NONE' and cond_state.get('side', 'NONE') != 'NONE':
            system_active_side = cond_state.get('side')

        for pos in active_positions:
            if pos.get('underlying') == underlying:
                # If it matches our active side, it's the primary sector detail
                if pos.get('side') == system_active_side:
                    active_pos_details = pos
                    current_pnl = pos.get('pnl_abs', 0)
                    break
                # Fallback: if we only have one position for this index, show it even if side mismatch
                elif not active_pos_details:
                    active_pos_details = pos

        # NEW: Background Interlock Reconciliation
        # If state claims a position is active, but it vanished from active_positions (meaning Broker executed a Native exiting leg like SL/Target),
        # we must immediately rip down Conditional Index bounds to prevent naked short interlocking.
        if state.get('side') in ['CALL', 'PUT'] and not active_pos_details:
            logger.warning(f"Reconciliation: Broker shows no active position for {underlying}, but state says {state.get('side')}. Cleaning up...")
            super_order_engine._cancel_active_conditional_orders(underlying, state)
            super_order_engine._clear_state(underlying)
            state = super_order_engine._get_state(underlying) # refresh the variable for UI response

        # New: Global Range Status for major indices
        range_tracker = {}
        for idx in ["NIFTY", "BANKNIFTY"]:
            idx_state = super_order_engine._get_state(idx)
            range_tracker[idx] = idx_state.get('range_position', 'INSIDE')

        # NEW: Capture any newly completed trades from mock broker
        if hasattr(broker, 'get_completed_trades'):
            recent_trades = broker.get_completed_trades()
            for trade in recent_trades:
                _add_to_history(trade)

        return jsonify({
            "status": "success", 
            "state": state,
            "active_positions": active_positions,
            "sector_details": active_pos_details, # For in-card P&L
            "range_tracker": range_tracker
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
    
    underlying = data.get('underlying', 'NIFTY')
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
        # 1. Resolve Context Logic (Move intelligence to Server)
        spot_index = resolve_index_spot(broker, underlying, data)
        
        index_ids = {"NIFTY": "13", "BANKNIFTY": "25", "FINNIFTY": "27"}
        idx_sec_id = index_ids.get(underlying.upper())
        
        # Prepare leg_data with resolved context
        side = 'CALL' if signal_type == 'B' else 'PUT'
        itm = resolve_call_itm(broker, underlying, spot_index) if side == 'CALL' else resolve_put_itm(broker, underlying, spot_index)
        
        if not itm or not idx_sec_id:
            return jsonify({"status": "error", "message": "Failed to resolve ITM contract or Index ID"}), 400

        leg_data = {
            "underlying": underlying,
            "itm": itm,
            "idx_sec_id": idx_sec_id,
            "quantity": int(data.get('quantity', 1)),
            "spot_index": spot_index,
            "sl_index": data.get('sl_index'),
            "target_index": data.get('target_index')
        }
        
        # Mandatory Validation for Manual Entries (AC 6)
        if spot_index <= 0:
            return jsonify({"status": "error", "message": "Could not determine current index spot price. Cannot validate SL/Target."}), 400

        if signal_type == 'B':
            if not leg_data.get('sl_index') or not leg_data.get('target_index'):
                return jsonify({"status": "error", "message": "Manual CALL requires Index Stop Loss and Target levels"}), 400

            try:
                sl_idx_val = float(leg_data['sl_index'])
                tgt_idx_val = float(leg_data['target_index'])
            except (TypeError, ValueError) as e:
                return jsonify({"status": "error", "message": f"Invalid SL/Target index value: {e}"}), 400

            if sl_idx_val >= spot_index:
                 return jsonify({"status": "error", "message": f"Stop Loss Index ({sl_idx_val}) must be less than current Index price ({spot_index})"}), 400
        elif signal_type == 'S':
            if not leg_data.get('sl_index') or not leg_data.get('target_index'):
                return jsonify({"status": "error", "message": "Manual PUT requires Index Stop Loss and Target levels"}), 400

            try:
                sl_idx_val = float(leg_data['sl_index'])
                tgt_idx_val = float(leg_data['target_index'])
            except (TypeError, ValueError) as e:
                return jsonify({"status": "error", "message": f"Invalid SL/Target index value: {e}"}), 400

            if sl_idx_val <= spot_index:
                 return jsonify({"status": "error", "message": f"Stop Loss Index ({sl_idx_val}) must be greater than current Index price ({spot_index})"}), 400

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
        logger.error(f"Conditional Order Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
    Places a Premium-based Super Order (Bracket).
    """
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    underlying = data.get('underlying', 'NIFTY').upper()
    option = data.get('option')
    signal_dir = data.get('side', 'CALL').upper() if not option else ''
    target = data.get('target_price')
    sl = data.get('sl_price')
    quantity = data.get('quantity', 1)

    if not target or not sl:
         return jsonify({"status": "error", "message": "Premium Target and SL are required for Super Orders"}), 400

    try:
        # 1. Resolve Signal Context (Move intelligence to Server)
        spot_index = resolve_index_spot(broker, underlying, data)
        itm_ce = resolve_call_itm(broker, underlying, spot_index)
        itm_pe = resolve_put_itm(broker, underlying, spot_index)
        
        if not itm_ce or not itm_pe:
            return jsonify({"status": "error", "message": "Failed to resolve ITM contract or Index ID"}), 400

        # Identify side using exact logic moved from engine
        target_side = 'CALL' if signal_dir == 'B' else 'PUT'
        itm = itm_ce if target_side == 'CALL' else itm_pe
        
        # Resolve ITM Option and place Super Order via super_order_engine logic
        leg_data = {
            "underlying": underlying,
            "target_side": target_side,
            "itm_ce": itm_ce,
            "itm_pe": itm_pe,
            "spot_index": spot_index,
            "quantity": int(quantity),
            "sl_price": float(sl),
            "target_price": float(target),
            "force_super": True
        }
        if option:
            leg_data["option_symbol"] = option
            
        # Execute Signal
        result = super_order_engine.process_signal(underlying, itm, signal_dir, 'regular', leg_data)
        return jsonify({"status": "success", "result": result}), 200
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
        if not state or not state.get('is_super_order'):
            return jsonify({"status": "error", "message": "No active Super Order found for underlying"}), 400
            
        entry_id = state.get('entry_id')
        if not entry_id:
            return jsonify({"status": "error", "message": "No entry ID found in state"}), 400
            
        # Update Target
        target_res = {"success": True}
        if target:
            # We assume modify_super_target_leg accepts parent order id which internally modifies target leg
            broker.modify_super_target_leg(entry_id, float(target))
            target_res["modified"] = True
            
        # Update SL
        sl_res = {"success": True}
        if sl:
            broker.modify_super_sl_leg(entry_id, float(sl), 1.0)
            sl_res["modified"] = True
            
        return jsonify({"status": "success", "target_update": target_res, "sl_update": sl_res}), 200
    except Exception as e:
        logger.error(f"Update Super Order Error: {e}")
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
