# Plan: Phase 13 - Modular Broker Facade & Dedicated Services

Goal: Decompose monolithic `DhanClient` into dedicated domain services with clean protocols/interfaces while maintaining 100% backwards compatibility via a Facade.

## Tasks
- [x] Create `broker/interfaces.py` defining protocols for Auth, Instrument, MarketData, Order, ConditionalOrder, Safety, and Socket.
- [x] Implement `broker/auth_service.py` (`DhanAuthService`).
- [x] Implement `broker/instrument_service.py` (`DhanInstrumentService`) with `load_scrip=False` offline test capability.
- [x] Implement `broker/market_data_service.py` (`DhanMarketDataService`) with LTP cache and margin calculation.
- [x] Implement `broker/order_service.py` (`DhanOrderService`) for Super and standard orders.
- [x] Implement `broker/conditional_order_service.py` (`DhanConditionalOrderService`) for GTT orders.
- [x] Implement `broker/safety_service.py` (`DhanSafetyService`) for kill switch and alarm reporting.
- [x] Implement `broker/socket_service.py` (`DhanSocketService`) for real-time WebSocket listener.
- [x] Refactor `broker_dhan.py` to use `broker/` services via the backwards-compatible `DhanClient` Facade.
- [x] Create `tests/test_modular_broker.py` to test isolated services and the facade.
- [x] Run complete test suite (`pytest tests/`) and verify zero regression.
