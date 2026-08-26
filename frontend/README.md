# frontend

Next.js 15 + TypeScript + Tailwind 4 web UI for `trading-buddy`.

## Stack

- **Next.js 15** App Router (RSC + Turbopack)
- **TypeScript** strict
- **Tailwind CSS 4** + custom dark palette, with a light mode on top of it
  (see [Dark / light theme](#dark--light-theme))
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
│   ├── layout.tsx             Theme class + providers
│   ├── page.tsx               Dashboard (/)
│   ├── qa/page.tsx            Q&A knowledge base (/qa)
│   ├── providers.tsx          QueryClient + Toaster
│   └── globals.css
├── components/
│   ├── ui/                    Card, Button, Badge, Input, Textarea (shadcn-style)
│   ├── shared/                Header (tab nav), ConnectionStatusIndicator, ThemeToggle
│   └── qa/                    QAPanel, QAEntryCard, QAEditor
├── hooks/
│   ├── useLiveTick.ts         Subscribes to /ws/ticks
│   └── useQA.ts               Q&A list + create/update/delete mutations
├── lib/
│   ├── api.ts                 fetch + Zod validation
│   ├── ws.ts                  Auto-reconnecting WebSocket client
│   ├── types.ts               Domain Zod schemas (mirror of backend DTOs)
│   ├── theme.ts               Dark/light switch + chart colors
│   └── utils.ts               cn(), fmtPrice(), fmtPct()
└── package.json
```

## Dark / light theme

The sun/moon button in the header flips the whole app between dark and light.
The choice is kept in `localStorage` under `dtb-theme`, and a tiny inline script
in `app/layout.tsx` puts the class on `<html>` before the first paint, so a
reload in light mode never flashes the dark palette.

Every panel is written with the dark palette spelled out in the class names
(`bg-zinc-900`, `text-zinc-100`, `text-emerald-400`, ...). Tailwind 4 compiles
those to `var(--color-<hue>-<shade>)`, so light mode is one block in
`app/globals.css`: `html.light` mirrors the scale (950 <-> 50, 900 <-> 100,
400 <-> 600, 500 stays) for the ten hues the UI uses. Page background is forced
to pure white. Nothing else changes — no component carries `dark:` variants, and
a new panel gets light mode for free as long as it sticks to the palette.

Two places can't read CSS, so they are handed the theme directly:

- **Charts** (`lightweight-charts` paints on a canvas) — `chartColors()` in
  `lib/theme.ts` returns axis/grid/border colors, and each chart re-applies them
  when the toggle flips.
- **Toasts** (`sonner`) — `app/providers.tsx` passes the current theme.

Use `useTheme()` from `lib/theme.ts` if a new component ever needs the same.

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
