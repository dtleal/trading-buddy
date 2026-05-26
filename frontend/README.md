# frontend

Reserved for the web UI (phase 2).

The backend is built around use cases that already return structured DTOs from
`core.models`, so adding a FastAPI/WebSocket adapter under `backend/cli/`
(or a new `backend/api/` package) and a Next.js client here will not require
touching the domain or use cases.
