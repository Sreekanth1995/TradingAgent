# Integrations

## TradingView (Webhook Input)
- **Format**: JSON Payload.
- **Fields**: `ticker`, `action`, `underlying`, `timeframe`, `order_legs`.
- **Authentication**: `WEBHOOK_SECRET` header or payload field.

## Dhan API (Broker Output)
- **Endpoints Used**:
    - Manage Super Orders (Native BO).
    - Get LTP (Indices and Options).
    - Place Market/Limit Orders.
    - Get Order Status.
    - Auth: Consumes `tokenId` via consent flow for 24h JWT.

## Redis (State Persistence)
- **Purpose**: Persist `last_signal` and `active_positions` across server restarts.
- **Keyspace**: `state:{underlying}`.
