import os
import re
import json
import logging
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from ranking_engine import RankingEngine
from broker_dhan import DhanClient
from collections import deque
from datetime import datetime

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

# Live Activity Feed using deque (Thread-safe memory buffer)
activity_logs = deque(maxlen=50)

# Initialize Components with graceful error handling
broker = None
engine = None
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
        
    engine = RankingEngine(broker)
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
            import pytz
            from datetime import datetime
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
        "status": "healthy" if broker and engine else "degraded",
        "broker_initialized": broker is not None,
        "engine_initialized": engine is not None,
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
    if not broker or not engine:
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
            
            # Fetch feeling from state (which is populated by /feeling API)
            state = engine._get_state(underlying)
            feeling = state.get('feeling', '').upper()
            
            # Apply Feeling API Logic
            if feeling == 'BUY' and transaction_type == 'S':
                msg = f"Ignored 'S' signal for {underlying} on {timeframe}m due to state feeling '{feeling}'"
                logger.info(msg)
                activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 {msg}")
                results.append({"action": "IGNORED_DUE_TO_FEELING", "reason": f"State feeling is {feeling}, ignored S signal"})
                continue
            if feeling == 'SELL' and transaction_type == 'B':
                msg = f"Ignored 'B' signal for {underlying} on {timeframe}m due to state feeling '{feeling}'"
                logger.info(msg)
                activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 {msg}")
                results.append({"action": "IGNORED_DUE_TO_FEELING", "reason": f"State feeling is {feeling}, ignored B signal"})
                continue
                
            msg = f"Received Signal: {transaction_type} for {underlying} on {timeframe}m timeframe"
            logger.info(msg)
            activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] 📡 {msg}")

            # 3. Process with Ranking Engine (Index-Based)
            mode = leg.get('mode', data.get('mode', 'regular')).lower()
            final_signal = transaction_type # Direct external fallback

            action = engine.process_signal(underlying, final_signal, mode, leg)
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
    if not broker or not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        engine.manual_exit_all()
        return jsonify({"status": "success", "message": "All positions closed and ranks reset successfully."}), 200
    except Exception as e:
        logger.error(f"Manual Exit Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/feeling', methods=['POST'])
def update_feeling():
    """
    Endpoint to receive feeling logic (e.g. BUY/SELL market mood) on higher timeframes.
    This limits TradingView webhook usage by storing state instead of multi-conditional alerts.
    """
    if not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    try:
        data = request.get_json(force=True, silent=True)
        if not data or data.get('secret') != SECRET:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
        legs = data.get('order_legs', [])
        updated = []
        
        for leg in legs:
            symbol = leg.get('symbol') or leg.get('ticker') or leg.get('underlying')
            if not symbol:
                continue
            
            feeling = leg.get('feeling', '').strip().upper()
            if feeling in ['BUY', 'SELL']:
                state = engine._get_state(symbol)
                state['feeling'] = feeling
                engine._set_state(symbol, state)
                updated.append({"symbol": symbol, "feeling": feeling})
                msg = f"Updated Feeling State for {symbol}: {feeling}"
                logger.info(msg)
                activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] 🧠 {msg}")
                
        return jsonify({"status": "success", "updated": updated}), 200
    except Exception as e:
        logger.error(f"Update Feeling Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def _get_active_positions():
    """
    Aggregates active positions across NIFTY, BANKNIFTY, and FINNIFTY.
    Fetches live LTP for PnL calculation.
    """
    if not engine or not broker:
        return []
    
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
    active_positions = []
    
    for underlying in indices:
        try:
            state = engine._get_state(underlying)
            if state and state.get('side') != 'NONE':
                # Fetch LTP for the specific contract if symbol is present
                symbol = state.get('symbol')
                security_id = state.get('security_id')
                entry_price = float(state.get('entry_price', 0))
                qty = int(state.get('quantity', 0))
                
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
                        "side": state.get('side'),
                        "quantity": qty,
                        "entry_price": entry_price,
                        "ltp": ltp,
                        "pnl_abs": round(pnl_abs, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "strike": state.get('strike'),
                        "option_type": state.get('option_type'),
                        "range_position": state.get('range_position', 'INSIDE')
                    })
                else:
                    # Fallback if LTP is missing: use last cached state if available 
                    # but for now we just skip the PnL update to avoid showing 0.
                    logger.warning(f"LTP unavailable for {symbol}, skipping PnL update.")
                    active_positions.append({
                        "underlying": underlying,
                        "symbol": symbol,
                        "side": state.get('side'),
                        "quantity": qty,
                        "entry_price": entry_price,
                        "ltp": "---", # Visual indicator of stale price
                        "pnl_abs": "---",
                        "pnl_pct": "---",
                        "strike": state.get('strike'),
                        "option_type": state.get('option_type'),
                        "range_position": state.get('range_position', 'INSIDE')
                    })
        except Exception as e:
            logger.error(f"Error fetching position for {underlying}: {e}")
            
    return active_positions

@app.route('/get-state', methods=['POST'])
def get_state():
    """
    Get current state (side and last_signal) for a given underlying.
    """
    if not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        # Backward compatibility for single underlying requests
        underlying = data.get('underlying', 'NIFTY')
        state = engine._get_state(underlying)
        
        # New: Aggregate active positions for dashboard
        active_positions = _get_active_positions()
        
        # New: Global Range Status for major indices
        range_tracker = {}
        for idx in ["NIFTY", "BANKNIFTY"]:
            idx_state = engine._get_state(idx)
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
            "range_tracker": range_tracker
        }), 200
    except Exception as e:
        logger.error(f"Get State Error: {e}")
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
    Returns the most recent system activity logs (signals received, orders placed, feelings updated).
    """
    data = request.get_json(force=True, silent=True) or {}
    # We still allow fetching logs safely if secrets match, or skip if internal dashboard UI does it passively.
    # We will enforce secret check to match the existing UI logic.
    if data and data.get('secret') and data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    return jsonify({"status": "success", "logs": list(activity_logs)}), 200

@app.route('/ui-signal', methods=['POST'])
def ui_signal():
    """
    Programmatic/AI entry point for manual UI signals.
    """
    if not broker or not engine:
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
        # Fetch Index LTP for manual entries if needed
        spot_price = 0.0
        index_ids = {"NIFTY": "13", "BANKNIFTY": "25", "FINNIFTY": "27"}
        idx_id = index_ids.get(underlying.upper())
        if idx_id and signal_type in ['B', 'S']:
            spot_price = broker.get_ltp(idx_id, exchange_segment="IDX_I") or 0.0
            
        leg_data = {
            "underlying": underlying,
            "quantity": data.get('quantity', 1),
            "current_price": spot_price
        }
        
        # Trigger processing (Default to regular mode for manual override)
        result = engine.process_signal(underlying, signal_type, 'regular', leg_data)
        logger.info(f"UI Signal: {action} processed for {underlying} -> {result.get('action')}")
        
        return jsonify({"status": "success", "result": result}), 200
    except Exception as e:
        logger.error(f"UI Signal Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/level-hit', methods=['POST'])
def level_hit():
    """
    Dedicated endpoint for level crossings.
    Triggers the SL trailing logic (LEVEL_CROSS signal).
    """
    if not broker or not engine:
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
                action = engine.process_signal(underlying, 'LEVEL_CROSS', leg_mode, leg)
                results.append(action)
        else:
            # Fallback for simple payload: {"secret": "...", "underlying": "NIFTY"}
            underlying = data.get('underlying') or data.get('ticker') or 'NIFTY'
            leg_data = data
            action = engine.process_signal(underlying, 'LEVEL_CROSS', mode, leg_data)
            results.append(action)
            
        return jsonify({"status": "success", "actions": results}), 200
    except Exception as e:
        logger.error(f"Level Hit Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/volume-alert', methods=['POST'])
def volume_alert():
    """
    Endpoint triggered when NIFTY crosses daily volume.
    Activates Scalping Mode for 5 minutes and runs AI Analysis.
    """
    if not broker or not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        # Always activate scalping mode
        engine.activate_scalping_mode(5)
        
        results = []
        
        return jsonify({
            "status": "success", 
            "message": "Scalping Mode activated.", 
            "actions": results
        }), 200
    except Exception as e:
        logger.error(f"Volume Alert Processing Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/set-conditional-orders', methods=['POST'])
def set_conditional_orders():
    """
    Creates Dhan Conditional Trigger orders (GTT) for Target and SL on an open position.
    Payload: { secret, underlying, side ('CALL'|'PUT'), target_price, sl_price }
    """
    if not broker or not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY')
    side = data.get('side', '').upper()
    target_price = data.get('target_price')
    sl_price = data.get('sl_price')

    if side not in ['CALL', 'PUT']:
        return jsonify({"status": "error", "message": "side must be CALL or PUT"}), 400
    if not target_price or not sl_price:
        return jsonify({"status": "error", "message": "target_price and sl_price are required"}), 400
    if float(sl_price) >= float(target_price):
        return jsonify({"status": "error", "message": "sl_price must be less than target_price"}), 400

    try:
        state = engine._get_state(underlying)
        if state.get('side', 'NONE') == 'NONE':
            return jsonify({"status": "error", "message": "No open position — open a position first"}), 400

        sec_id = state.get('security_id')
        symbol = state.get('symbol', underlying)
        quantity = int(state.get('quantity', 1))

        if not sec_id:
            return jsonify({"status": "error", "message": "No security_id in state; position may not be broker-placed"}), 400

        # Convert lots → actual quantity using lot map
        lot_size = broker.lot_map.get(str(sec_id), 1)
        actual_qty = quantity * lot_size

        # Resolve product type: default to MARGIN as used in RankingEngine square-offs
        product_type = state.get('product_type', 'MARGIN')
        
        # Determine transaction side: Strategy is Long CE/PE, so Exit is always SELL
        # If we ever support Shorting, this would need to be BUY for PE/CE shorts.
        tx_type = "SELL"

        # Cancel any pre-existing conditional orders for this position
        for key in ('conditional_target_alert_id', 'conditional_sl_alert_id'):
            existing = state.get(key)
            if existing:
                broker.cancel_conditional_order(existing)

        # Target: SELL when LTP crosses UP above target_price
        tgt_result = broker.place_conditional_order(
            sec_id=sec_id,
            exchange_seg="NSE_FNO",
            quantity=actual_qty,
            operator="CROSSING_UP",
            comparing_value=float(target_price),
            transaction_type=tx_type,
            product_type=product_type
        )

        # SL: SELL when LTP crosses DOWN below sl_price
        sl_result = broker.place_conditional_order(
            sec_id=sec_id,
            exchange_seg="NSE_FNO",
            quantity=actual_qty,
            operator="CROSSING_DOWN",
            comparing_value=float(sl_price),
            transaction_type=tx_type,
            product_type=product_type
        )

        # Persist alert IDs in state
        state['conditional_target_alert_id'] = tgt_result.get('alert_id')
        state['conditional_sl_alert_id'] = sl_result.get('alert_id')
        state['conditional_target_price'] = float(target_price)
        state['conditional_sl_price'] = float(sl_price)
        engine._set_state(underlying, state)

        msg = f"GTT orders set for {symbol}: Target={target_price}, SL={sl_price}"
        logger.info(msg)
        activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 {msg}")

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "target_alert_id": tgt_result.get('alert_id'),
            "sl_alert_id": sl_result.get('alert_id'),
            "target_error": tgt_result.get('error'),
            "sl_error": sl_result.get('error')
        }), 200
    except Exception as e:
        logger.error(f"Set Conditional Orders Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/range-signal', methods=['POST'])
def range_signal():
    """
    Update the status of the price relative to the Range Tracker.
    Payload: { secret, underlying, status ('ABOVE'|'BELOW'|'INSIDE') }
    """
    if not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY')
    position = data.get('position', 'INSIDE').upper()

    try:
        state = engine._get_state(underlying)
        state['range_position'] = position
        engine._set_state(underlying, state)

        msg = f"Range Position for {underlying}: {position}"
        logger.info(msg)
        activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] 🧭 {msg}")

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
    if not broker or not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503

    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    underlying = data.get('underlying', 'NIFTY')
    try:
        state = engine._get_state(underlying)
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
        engine._set_state(underlying, state)

        msg = f"GTT orders cancelled for {underlying}"
        activity_logs.appendleft(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {msg}")

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
