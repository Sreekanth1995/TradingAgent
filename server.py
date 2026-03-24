import os
import re
import json
import logging
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from ranking_engine import RankingEngine
from broker_dhan import DhanClient
from openai_analyzer import OpenAIAnalyzer

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

# Initialize Components with graceful error handling
broker = None
engine = None
init_error = None

try:
    broker = DhanClient()
    engine = RankingEngine(broker)
    logger.info("✅ System Initialized Successfully")
except Exception as e:
    init_error = str(e)
    logger.error(f"⚠️ Initialization Failed: {e}")
    logger.warning("App will start in degraded mode. Please check environment variables.")

# OpenAI Analyzer (lazy init — works even without API key)
try:
    analyzer = OpenAIAnalyzer()
except Exception as e:
    analyzer = None
    logger.warning(f"OpenAI Analyzer unavailable: {e}")

# In-memory stores (persisted to JSON files for restart survival)
_LEVELS_FILE = "levels.json"
_CONTEXT_FILE = "ai_context.txt"
_AI_LOG = []  # last 20 AI decisions

def _load_levels():
    try:
        with open(_LEVELS_FILE) as f:
            return json.load(f)
    except Exception:
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
            logger.info(f"Received Signal: {transaction_type} for {underlying} on {timeframe}m timeframe")

            # 2.5 AI Analysis Gate
            if analyzer:
                full_signal_context = {
                    "active_leg": leg,
                    "underlying": underlying,
                    "timeframe": timeframe,
                    "full_webhook_payload": {k: v for k, v in data.items() if k != 'secret'}
                }
                ai_result = analyzer.analyze(
                    full_signal_context,
                    _load_levels(),
                    _load_context()
                )
                # Log AI decision
                _AI_LOG.append({
                    "underlying": underlying,
                    "direction": transaction_type,
                    "decision": ai_result["decision"],
                    "reason": ai_result["reason"],
                    "confidence": ai_result["confidence"]
                })
                if len(_AI_LOG) > 20:
                    _AI_LOG.pop(0)

                if ai_result["decision"] == "REJECT":
                    logger.warning(f"AI REJECTED signal for {underlying}: {ai_result['reason']}")
                    results.append({"action": "AI_REJECTED", "underlying": underlying, "reason": ai_result["reason"]})
                    continue
                logger.info(f"AI APPROVED signal for {underlying} (confidence={ai_result['confidence']}%)")
            
            # 3. Process with Ranking Engine (Index-Based)
            try:
                tf_val = int(timeframe)
            except ValueError:
                tf_val = timeframe # Pass as string (e.g. "TP0", "TP1")
            
            action = engine.process_signal(underlying, transaction_type, tf_val, leg)
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
    
    underlying = data.get('underlying', 'NIFTY')
    try:
        state = engine._get_state(underlying)
        return jsonify({"status": "success", "state": state}), 200
    except Exception as e:
        logger.error(f"Get State Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/toggle-side', methods=['POST'])
def toggle_side():
    """
    Manually toggle between CALL and PUT sides.
    """
    if not broker or not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    underlying = data.get('underlying', 'NIFTY')
    target_side = data.get('target_side') # 'CALL' or 'PUT'
    
    if target_side not in ['CALL', 'PUT']:
        return jsonify({"status": "error", "message": "Invalid target_side"}), 400
        
    try:
        # Convert side to signal_type for engine.process_signal
        # CALL -> 'B' (Buy/Long), PUT -> 'S' (Sell/Short)
        signal_type = 'B' if target_side == 'CALL' else 'S'
        
        # We need ticker price for opening position
        # For manual toggle, we use standard 5m timeframe logic but triggered manually.
        # We need to fetch LTP for current_price.
        
        # Resolve a dummy or real ticker for the underlying to get its price
        # Or just use the last known price if the engine tracks it (it doesn't yet).
        # RankingEngine._open_position needs leg_data with current_price.
        
        # Let's try to get LTP for the underlying if possible, or just pass a placeholder 
        # normally provided by TradingView.
        # Since we are manually triggering, we might need to fetch index LTP.
        # But wait, broker.get_itm_contract takes spot_price.
        
        # For simplicity in manual mode, let's assume NIFTY and try to get its price.
        # Or better, let the frontend send it? No, backend should handle it.
        
        # Let's just use a default or fetch if available.
        spot_price = 0.0
        # If we have a security ID for the index, we could fetch it.
        # But index IDs vary. 
        # Let's check broker_dhan for index LTP support.
        
        # Actually, RankingEngine.process_signal expects leg_data.
        # Minimal leg_data: {'quantity': 1}
        # _open_position will try to get_itm_contract(underlying, opt_type, spot)
        # We need 'current_price' in leg_data or it defaults to 0.
        
        # Let's fetch index LTP if we can.
        # Aliases for common indices to support manual trading labels
        index_ids = {
            "NIFTY": "13", 
            "NIFTY_50": "13",
            "NIFTY 50": "13",
            "BANKNIFTY": "25", 
            "FINNIFTY": "27"
        } 
        idx_id = index_ids.get(underlying.upper())
        if idx_id:
            # Note: For Index LTP, Dhan API v2 expects exchange_segment="IDX_I"
            spot_price = broker.get_ltp(idx_id, exchange_segment="IDX_I") or 0.0
            
        leg_data = {
            "underlying": underlying,
            "quantity": data.get('quantity', 1),
            "current_price": spot_price
        }
        
        action = engine.process_signal(underlying, signal_type, 5, leg_data)
        return jsonify({"status": "success", "action": action}), 200
    except Exception as e:
        logger.error(f"Toggle Side Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
        
        # Trigger processing (Default to 5m timeframe for manual override)
        result = engine.process_signal(underlying, signal_type, 5, leg_data)
        logger.info(f"UI Signal: {action} processed for {underlying} -> {result.get('action')}")
        
        return jsonify({"status": "success", "result": result}), 200
    except Exception as e:
        logger.error(f"UI Signal Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/volume-alert', methods=['POST'])
def volume_alert():
    """
    Endpoint triggered when NIFTY crosses daily volume.
    Activates Scalping Mode for 5 minutes.
    """
    if not broker or not engine:
        return jsonify({"status": "error", "message": "System not initialized"}), 503
        
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        engine.activate_scalping_mode(5)
        return jsonify({"status": "success", "message": "Scalping Mode activated for 5 minutes."}), 200
    except Exception as e:
        logger.error(f"Volume Alert Processing Error: {e}")
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

@app.route('/get-ai-logs', methods=['POST'])
def get_ai_logs():
    data = request.get_json(force=True, silent=True)
    if not data or data.get('secret') != SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    return jsonify({"status": "success", "logs": _AI_LOG}), 200

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
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
