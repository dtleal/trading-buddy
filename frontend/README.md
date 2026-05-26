# frontend

Reserved for the web UI (phase 2).

The backend is built around use cases that already return structured DTOs from
`day_trading_buddy.core.models`, so adding a FastAPI/WebSocket adapter under
`backend/src/day_trading_buddy/cli/` (or a new `api/` package) and a Next.js
client here will not require touching the domain or use cases.
