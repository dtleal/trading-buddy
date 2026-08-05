# frontend

Next.js 15 + TypeScript + Tailwind 4 web UI for `trading-buddy`.

## Stack

- **Next.js 15** App Router (RSC + Turbopack)
- **TypeScript** strict
- **Tailwind CSS 4** + custom dark palette
- **shadcn/ui** primitives (Card, Button, Badge), copied locally — not a dep
- **TanStack Query v5** for REST state (initial loads, manual refetch)
- **Zustand** for client state (alert configs)
- **Zod** runtime validation at the network boundary
- **TradingView Lightweight Charts** for the VIX chart (Phase 3)
- **sonner** for in-app toast alerts
- **lucide-react** icons

## Screen layout (6 assets)

The dashboard shows all six tracked assets side by side. Two rows carry one tile
per asset and line up column-for-column, so the eye can drop straight from a
stance to the flow for the same instrument:

- **VIX × Preço** — six compact tiles, a single row from `2xl` up.
- **Fluxo** (order flow) — six half-width columns. Inside each column
  **Atividade** and **Pressão** sit at the top on purpose: those are the two
  reads that get acted on, so they stay visible across all six columns without
  scrolling. Bid/Ask, Footprint and Tape follow underneath.

Both grids step `1 → 2 → 3 → 6` columns (`sm` / `lg` / `2xl`), so a phone gets
one readable column and a wide monitor gets the whole strip in one line. The page
container is capped at `2100px` to give six columns room to breathe.

The asset list itself comes from `TRACKED_ASSETS` in `lib/types.ts` — every panel
maps over that one array, so adding an asset is a single edit on the frontend
side. Keep it in sync with `TRACKED_ASSETS` in `backend/core/enums.py`.

## Layout

```
frontend/
├── app/                       Next.js App Router
│   ├── layout.tsx             Dark theme + providers
│   ├── page.tsx               Dashboard (/)
│   ├── qa/page.tsx            Q&A knowledge base (/qa)
│   ├── providers.tsx          QueryClient + Toaster
│   └── globals.css
├── components/
│   ├── ui/                    Card, Button, Badge, Input, Textarea (shadcn-style)
│   ├── shared/                Header (tab nav), ConnectionStatusIndicator
│   └── qa/                    QAPanel, QAEntryCard, QAEditor
├── hooks/
│   ├── useLiveTick.ts         Subscribes to /ws/ticks
│   └── useQA.ts               Q&A list + create/update/delete mutations
├── lib/
│   ├── api.ts                 fetch + Zod validation
│   ├── ws.ts                  Auto-reconnecting WebSocket client
│   ├── types.ts               Domain Zod schemas (mirror of backend DTOs)
│   └── utils.ts               cn(), fmtPrice(), fmtPct()
└── package.json
```

## Dev

```bash
cp .env.example .env.local
npm install
npm run dev                    # http://localhost:3000
```

Pointing at a different backend:
```bash
NEXT_PUBLIC_API_URL=http://10.0.0.5:8000 npm run dev
```

## What the backend must expose

- `GET  /api/tick`          — latest DashboardTick
- `GET  /api/vix/history`   — 5m VIX bars (1-60 day lookback)
- `WS   /ws/ticks`          — pushes each new DashboardTick
- `GET/POST/PUT/DELETE /api/qa` — Q&A knowledge base CRUD

Run the backend stack with `make docker-up` from the repo root.
