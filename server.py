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

            # 4. Process with Ranking Engine (Index-Based)
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
                        "range_position": state.get('range_position', 'INSIDE'),
                        "idx_target_level": state.get('idx_target_level'),
                        "idx_sl_level": state.get('idx_sl_level'),
                        "conditional_target_price": state.get('conditional_target_price'),
                        "conditional_sl_price": state.get('conditional_sl_price')
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
                        "idx_target_level": state.get('idx_target_level'),
                        "idx_sl_level": state.get('idx_sl_level'),
                        "conditional_target_price": state.get('conditional_target_price'),
                        "conditional_sl_price": state.get('conditional_sl_price')
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
            engine._cancel_active_conditional_orders(underlying, state)
            engine._clear_state(underlying)
            state = engine._get_state(underlying) # refresh the variable for UI response

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
            "sector_details": active_pos_details, # For in-card P&L
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

        # Execute Order
        res = engine.handle_signal(signal_type, leg_data)
        
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
                engine.store_pending_protection(order_id, pending_meta)
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
            
        # Acceptance Criteria 6: Extract userNote (SL ID) from payload
        user_note = data.get('userNote') or (data.get('data') or {}).get('userNote')
        alert_id = str(data.get('alertId') or (data.get('data') or {}).get('alertId'))
        order_status = data.get('orderStatus')
        order_id = data.get('orderId')
        
        # --- Handle Order Fill (TRADED) status ---
        if order_status == "TRADED" and order_id:
            logger.info(f"Order {order_id} TRADED. Checking for pending protection triggers.")
            pending = engine.get_pending_protection(order_id)
            if pending:
                logger.info(f"Triggering GTT placement for filled order {order_id} ({pending['underlying']})")
                gtt_res = _set_conditional_index_orders_internal(
                    underlying=pending['underlying'],
                    target_level=pending['target_level'],
                    sl_level=pending['sl_level'],
                    quantity=pending['quantity']
                )
                logger.info(f"Fill-Triggered GTT Result: {gtt_res}")
            return jsonify({"status": "success", "source": "order_fill"}), 200

        if not alert_id or alert_id == "None":
            return jsonify({"status": "ignored", "message": "No alertId found"}), 200

        logger.info(f"Dhan Postback received. alertId: {alert_id}, userNote: {user_note}")
        
        # If user_note contains a SL ID, use it directly for stateless modification
        if user_note and user_note.startswith("GTT_"): # Assuming our IDs look like this or digits
             sl_alert_id = user_note
             logger.info(f"Stateless SL Modification triggered via userNote: {sl_alert_id}")
             # We need to find which underlying this belongs to for quantity/security_id
             # Fallback to state search for metadata, but use user_note ID
        
        # Identify the position this alert belongs to
        indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
        target_found = False
        
        for underlying in indices:
            state = engine._get_state(underlying)
            # Match either alertId in state OR check if userNote matches the stored SL ID
            is_target_hit = (state.get('idx_target_alert_id') == alert_id)
            
            if is_target_hit:
                logger.info(f"Target Alert Hit for {underlying}! Triggering SL modification.")
                # Acceptance Criteria 6: Use SL ID from user_note if available
                sl_alert_id = user_note if (user_note and len(user_note) > 5) else state.get('idx_sl_alert_id')
                
                if sl_alert_id:
                    idx_id = broker.get_index_id(underlying)
                    current_idx_ltp = broker.get_ltp(idx_id, exchange_segment="IDX_I")
                    
                    if current_idx_ltp:
                        # Acceptance Criteria 6: Update SL with Target Price (Market force)
                        res = broker.modify_conditional_order(
                            alert_id=sl_alert_id,
                            quantity=state.get('quantity', 1) * broker.lot_map.get(str(state.get('security_id')), 1),
                            comparing_value=current_idx_ltp
                        )
                        logger.info(f"SL Modification result for {underlying} using ID {sl_alert_id}: {res}")
                
                state['idx_target_alert_id'] = None
                engine._set_state(underlying, state)
                target_found = True
                break
        
        if not target_found:
             logger.debug(f"AlertId {alert_id} not mapped to any active target.")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"Dhan Postback Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/conditional-index-order', methods=['POST'])
def set_conditional_index_orders():
    """
    Creates Dhan Conditional Trigger orders (GTT) based on INDEX LEVELS.
    """
    if not broker or not engine:
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
        res = _set_conditional_index_orders_internal(underlying, target_level, sl_level, quantity)
        if res.get('status') == 'success':
            return jsonify(res), 200
        else:
            return jsonify(res), 500
    except Exception as e:
        logger.error(f"Error in conditional-index-order: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def _set_conditional_index_orders_internal(underlying, target_level, sl_level, quantity=None):
    """
    Internal helper to place SL and Target GTTs.
    Follows AC 5: Saves SL ID in Target's userNote.
    """
    try:
        state = engine._get_state(underlying)
        if state.get('side', 'NONE') == 'NONE':
            return {"status": "error", "message": "No open position to protect"}

        opt_sec_id = state.get('security_id')
        qty = int(quantity or state.get('quantity', 1))
        idx_sec_id = broker.get_index_id(underlying)
        
        if not idx_sec_id or not opt_sec_id:
            return {"status": "error", "message": "Could not resolve Index or Option security IDs"}

        lot_size = broker.lot_map.get(str(opt_sec_id), 1)
        actual_qty = qty * lot_size
        side = state.get('side') # CALL or PUT
        
        if side == 'CALL':
            tgt_op, sl_op = "CROSSING_UP", "CROSSING_DOWN"
        else:
            tgt_op, sl_op = "CROSSING_DOWN", "CROSSING_UP"

        # Cleanup existing GTTs
        for key in ('idx_target_alert_id', 'idx_sl_alert_id'):
            existing = state.get(key)
            if existing: broker.cancel_conditional_order(existing)

        # Acceptance Criteria 4 & 5: Place SL GTT FIRST to get its ID
        sl_res = broker.place_conditional_order(
            sec_id=opt_sec_id,
            exchange_seg="NSE_FNO",
            quantity=actual_qty,
            operator=sl_op,
            comparing_value=float(sl_level),
            transaction_type="SELL",
            product_type="MARGIN",
            trigger_sec_id=idx_sec_id
        )
        if not sl_res.get('success'):
            return {"status": "error", "message": f"SL GTT failed: {sl_res.get('error')}"}
        
        sl_alert_id = sl_res.get('alert_id')
        
        # Acceptance Criteria 5: Place Target Dummy GTT with SL ID in userNote
        tgt_res = broker.place_conditional_order(
            sec_id="11006", # LiquidBees
            exchange_seg="NSE_EQ",
            quantity=1,
            operator=tgt_op,
            comparing_value=float(target_level),
            transaction_type="BUY",
            product_type="CNC",
            trigger_sec_id=idx_sec_id,
            user_note=sl_alert_id # Statelss mapping
        )
        
        if not tgt_res.get('success'):
            # Rollback SL if target fails
            broker.cancel_conditional_order(sl_alert_id)
            return {"status": "error", "message": f"Target GTT failed: {tgt_res.get('error')}. SL leg cancelled."}

        state['idx_target_alert_id'] = tgt_res.get('alert_id')
        state['idx_sl_alert_id'] = sl_alert_id
        engine._set_state(underlying, state)

        return {
            "status": "success", 
            "message": "Index GTTs placed successfully",
            "sl_id": sl_alert_id,
            "target_id": tgt_res.get('alert_id')
        }
    except Exception as e:
        logger.error(f"Internal GTT Placement Error: {e}")
        return {"status": "error", "message": str(e)}



@app.route('/super-order', methods=['POST'])
def set_super_order():
    """
    Places a Premium-based Super Order (Bracket).
    """
    if not broker or not engine:
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
        # Resolve ITM Option and place Super Order via engine logic
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
        result = engine.process_signal(underlying, signal_dir, 'regular', leg_data)
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
    if not broker or not engine:
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
        state = engine._get_state(underlying)
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
        state['range_timestamp'] = datetime.now().isoformat()
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
