# Concerns

## Known Limitations
- **Dhan Token Persistence**: Redis connection frequently fails on local setups, leading to in-memory state loss on restart.
- **Scalping Logic Thresholds**: Volumes and timeframes are currently hardcoded (e.g., 5-minute scalping window).
- **Index Identification**: Relies on a hardcoded map of NIFTY/BANKNIFTY/FINNIFTY IDs.

## Future Focus
- Multi-symbol support in the dashboard.
- Automated token refresh via "Smart Login".
- Real-time P&L display (currently omitted per user request).
