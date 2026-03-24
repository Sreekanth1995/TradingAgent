# Conventions

## Coding Standards
- **Python**: PEP 8 followed (mostly). Descriptive function names (e.g., `_execute_native_super_order`).
- **Logging**: Extensive logging via `logger`. Critical paths (Order placement/exit) use `INFO`.
- **Error Handling**: Graceful initialization (fallback to Simulation/Memory if Broker/Redis fails).

## UI Standards
- **Interactivity**: All buttons must have unique IDs.
- **Status Feed**: All UI actions must report success/failure to a status display.
- **Authentication**: `secret` required for all manual dashboard actions.
