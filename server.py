import os
import re
import json
import logging
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from super_order_engine import SuperOrderEngine
from conditional_order_engine import ConditionalOrderEngine
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
            
            # Fetch feeling from state (which is populated by /feeling API)
            state = super_order_engine._get_state(underlying)
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

            # 4. Process with Ranking Engine (Index-Based)
            mode = leg.get('mode', data.get('mode', 'regular')).lower()
            final_signal = transaction_type # Direct external fallback

            action = super_order_engine.process_signal(underlying, final_signal, mode, leg)
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

@app.route('/feeling', methods=['POST'])
def update_feeling():
    """
    Endpoint to receive feeling logic (e.g. BUY/SELL market mood) on higher timeframes.
    This limits TradingView webhook usage by storing state instead of multi-conditional alerts.
    """
    if not super_order_engine:
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
                state = super_order_engine._get_state(symbol)
                state['feeling'] = feeling
                super_order_engine._set_state(symbol, state)
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
    if not super_order_engine or not broker:
        return []
    
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
    active_positions = []
    
    for underlying in indices:
        try:
            state = super_order_engine._get_state(underlying)
            cond_state = conditional_engine._get_state(underlying) if conditional_engine else {}
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
                        "range_position": state.get('range_position', 'INSIDE'),
                        "idx_target_level": cond_state.get('idx_target_level') or state.get('idx_target_level'),
                        "idx_sl_level": cond_state.get('idx_sl_level') or state.get('idx_sl_level'),
                        "tgt_price": state.get('tgt_price') or state.get('conditional_target_price'),
                        "sl_price": state.get('sl_price') or state.get('conditional_sl_price')
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
                        "range_position": state.get('range_position', 'INSIDE'),
                        "idx_target_level": cond_state.get('idx_target_level') or state.get('idx_target_level'),
                        "idx_sl_level": cond_state.get('idx_sl_level') or state.get('idx_sl_level'),
                        "tgt_price": state.get('tgt_price') or state.get('conditional_target_price'),
                        "sl_price": state.get('sl_price') or state.get('conditional_sl_price')
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
        # We check if active_side matches a position's side
        current_pnl = 0
        active_pos_details = None
        for pos in active_positions:
            if pos.get('underlying') == underlying and pos.get('side') == state.get('side'):
                active_pos_details = pos
                current_pnl = pos.get('pnl_abs', 0)
                break

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
        # Fetch Index LTP for manual entries if needed
        spot_price = 0.0
        idx_id = broker.get_index_id(underlying)
        if idx_id and signal_type in ['B', 'S']:
            spot_price = broker.get_ltp(idx_id, exchange_segment="IDX_I") or 0.0
            
        leg_data = {
            "underlying": underlying,
            "quantity": data.get('quantity', 1),
            "current_price": spot_price,
            "sl_price": data.get('sl_price'),
            "target_price": data.get('target_price'),
            "sl_index": data.get('sl_index'),
            "target_index": data.get('target_index')
        }
        
        # Mandatory Validation for Manual Entries (AC 6)
        if signal_type == 'B':
            if not leg_data.get('sl_index') or not leg_data.get('target_index'):
                return jsonify({"status": "error", "message": "Manual BUY requires Index Stop Loss and Target levels"}), 400
                
            if float(leg_data['sl_index']) >= spot_price:
                 return jsonify({"status": "error", "message": f"Stop Loss Index ({leg_data['sl_index']}) must be less than current Index price ({spot_price})"}), 400

        # Execute Order via Conditional Engine
        res = conditional_engine.handle_signal(signal_type, leg_data)
        
        # Acceptance Criteria: Defer GTT placement until order is TRADED (Fill-Triggered)
        if res.get('status') == 'success' and signal_type == 'B' and leg_data.get('sl_index') and leg_data.get('target_index'):
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
        logger.error(f"UI Signal Error: {e}")
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
                action = super_order_engine.process_signal(underlying, 'LEVEL_CROSS', leg_mode, leg)
                results.append(action)
        else:
            # Fallback for simple payload: {"secret": "...", "underlying": "NIFTY"}
            underlying = data.get('underlying') or data.get('ticker') or 'NIFTY'
            leg_data = data
            action = super_order_engine.process_signal(underlying, 'LEVEL_CROSS', mode, leg_data)
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
    if not broker or not super_order_engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        # Always activate scalping mode
        super_order_engine.activate_scalping_mode(5)
        
        results = []
        
        return jsonify({
            "status": "success", 
            "message": "Scalping Mode activated.", 
            "actions": results
        }), 200
    except Exception as e:
        logger.error(f"Volume Alert Processing Error: {e}")
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
    side = data.get('side', 'CALL').upper() if not option else ''
    target = data.get('target_price')
    sl = data.get('sl_price')
    quantity = data.get('quantity', 1)

    if not target or not sl:
         return jsonify({"status": "error", "message": "Premium Target and SL are required for Super Orders"}), 400

    try:
        # Resolve ITM Option and place Super Order via super_order_engine logic
        leg_data = {
            "underlying": underlying,
            "quantity": int(quantity),
            "sl_price": float(sl),
            "target_price": float(target),
            "force_super": True
        }
        if option:
            leg_data["option_symbol"] = option
            
        signal_dir = 'B' if 'CE' in option else 'S' if option else ('B' if side == 'CALL' else 'S')
        result = super_order_engine.process_signal(underlying, signal_dir, 'regular', leg_data)
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
