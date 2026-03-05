import logging
import json
from unittest.mock import MagicMock, patch
from ranking_engine import RankingEngine

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_directional_exit():
    print("\n--- TESTING DIRECTIONAL EXIT (LONG_EXIT / SHORT_EXIT) ---")
    
    broker = MagicMock()
    # Mock ITM contracts
    itm_ce = {"symbol": "NIFTY_25000_CE", "security_id": "123"}
    itm_pe = {"symbol": "NIFTY_25100_PE", "security_id": "456"}
    
    def side_effect_itm(underlying, opt_type, spot):
        if opt_type == 'CE': return itm_ce
        if opt_type == 'PE': return itm_pe
        return None
    
    broker.get_itm_contract.side_effect = side_effect_itm
    broker.get_ltp.return_value = 100.0 # Mock option LTP
    
    # Mock Super Orders: One CE and One PE
    mock_legs = [
        {
            'orderId': 'SO_CE_1',
            'legName': 'TARGET_LEG',
            'transactionType': 'SELL',
            'securityId': '123',
            'tradingSymbol': 'NIFTY_25000_CE'
        },
        {
            'orderId': 'SO_CE_1',
            'legName': 'STOP_LOSS_LEG',
            'transactionType': 'SELL',
            'securityId': '123',
            'tradingSymbol': 'NIFTY_25000_CE'
        },
        {
            'orderId': 'SO_PE_1',
            'legName': 'TARGET_LEG',
            'transactionType': 'SELL',
            'securityId': '456',
            'tradingSymbol': 'NIFTY_25100_PE'
        },
        {
            'orderId': 'SO_PE_1',
            'legName': 'STOP_LOSS_LEG',
            'transactionType': 'SELL',
            'securityId': '456',
            'tradingSymbol': 'NIFTY_25100_PE'
        }
    ]
    broker.get_super_orders.return_value = mock_legs
    
    engine = RankingEngine(broker)
    underlying = "NIFTY"
    leg_data = {"underlying": "NIFTY", "current_price": 25050}

    # 1. Test LONG_EXIT
    print("\n[Step 1] Sending LONG_EXIT signal")
    result_long = engine.process_signal(underlying, "LONG_EXIT", 5, leg_data)
    print(f"Result: {result_long['action']}")
    
    # Verify CE orders were targeted for modification
    # _manage_opposite_orders should call modify_super_target_leg and modify_super_sl_leg for CE
    ce_modify_calls = [call for call in broker.modify_super_target_leg.call_args_list if call.args[0] == 'SO_CE_1']
    assert len(ce_modify_calls) > 0, "CE Target leg should have been modified"
    
    # Verify PE orders were NOT targeted
    pe_modify_calls = [call for call in broker.modify_super_target_leg.call_args_list if call.args[0] == 'SO_PE_1']
    assert len(pe_modify_calls) == 0, "PE Target leg should NOT have been modified during LONG_EXIT"
    
    # Reset mocks for next step
    broker.modify_super_target_leg.reset_mock()
    broker.modify_super_sl_leg.reset_mock()

    # 2. Test SHORT_EXIT
    print("\n[Step 2] Sending SHORT_EXIT signal")
    result_short = engine.process_signal(underlying, "SHORT_EXIT", 5, leg_data)
    print(f"Result: {result_short['action']}")
    
    # Verify PE orders were targeted
    pe_modify_calls = [call for call in broker.modify_super_target_leg.call_args_list if call.args[0] == 'SO_PE_1']
    assert len(pe_modify_calls) > 0, "PE Target leg should have been modified"
    
    # Verify CE orders were NOT targeted
    ce_modify_calls = [call for call in broker.modify_super_target_leg.call_args_list if call.args[0] == 'SO_CE_1']
    assert len(ce_modify_calls) == 0, "CE Target leg should NOT have been modified during SHORT_EXIT"

    print("\n✅ DIRECTIONAL EXIT TEST PASSED")

if __name__ == "__main__":
    test_directional_exit()
