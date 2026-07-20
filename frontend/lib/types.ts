/**
 * Domain types mirrored from the Python backend.
 *
 * Each type uses a Zod schema so we get runtime validation at the network
 * boundary (REST + WebSocket). If the backend ever drifts, we fail loudly
 * on parse rather than crashing components reading undefined fields.
 */
import { z } from "zod";

export const AssetSymbol = z.enum(["USTEC", "SPX", "GOLD", "BITCOIN"]);
export type AssetSymbol = z.infer<typeof AssetSymbol>;

export const VixRegime = z.enum(["low", "mid", "high"]);
export type VixRegime = z.infer<typeof VixRegime>;

export const TermStructure = z.enum(["contango", "flat", "backwardation"]);
export type TermStructure = z.infer<typeof TermStructure>;

export const BiasLevel = z.enum(["bullish", "neutral", "bearish"]);
export type BiasLevel = z.infer<typeof BiasLevel>;

export const ImpactLevel = z.enum(["low", "medium", "high", "holiday"]);
export type ImpactLevel = z.infer<typeof ImpactLevel>;

export const DayRegime = z.enum(["expansion", "normal", "thin"]);
export type DayRegime = z.infer<typeof DayRegime>;

export const PriceQuote = z.object({
  symbol: z.string(),
  price: z.number(),
  timestamp: z.string(), // ISO 8601 UTC
  ma200_d: z.number().nullable(),
  ma200_h4: z.number().nullable(),
  change_pct: z.number().nullable(),
});
export type PriceQuote = z.infer<typeof PriceQuote>;

export const VixSnapshot = z.object({
  vix: z.number(),
  vix9d: z.number().nullable(),
  vix3m: z.number().nullable(),
  regime: VixRegime,
  term_structure: TermStructure,
});
export type VixSnapshot = z.infer<typeof VixSnapshot>;

export const MarketSnapshot = z.object({
  timestamp: z.string(),
  assets: z.record(AssetSymbol, PriceQuote),
  vix: VixSnapshot,
});
export type MarketSnapshot = z.infer<typeof MarketSnapshot>;

export const IntradayBar = z.object({
  timestamp: z.string(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number(),
});
export type IntradayBar = z.infer<typeof IntradayBar>;

export const EconomicEvent = z.object({
  name: z.string(),
  currency: z.string(),
  impact: ImpactLevel,
  scheduled_at: z.string(),
  forecast: z.string().nullable(),
  previous: z.string().nullable(),
  actual: z.string().nullable(),
  source: z.string(),
});
export type EconomicEvent = z.infer<typeof EconomicEvent>;

export const BiasComponents = z.object({
  technical: z.number(),
  macro: z.number(),
  sentiment: z.number(),
});
export type BiasComponents = z.infer<typeof BiasComponents>;

export const BiasReport = z.object({
  asset: AssetSymbol,
  timestamp: z.string(),
  score: z.number(),
  level: BiasLevel,
  components: BiasComponents,
  rationale: z.array(z.string()),
});
export type BiasReport = z.infer<typeof BiasReport>;

export const Timeframe = z.enum(["5m", "15m", "30m", "60m", "4h"]);
export type Timeframe = z.infer<typeof Timeframe>;

export const BreakoutDirection = z.enum(["up", "down"]);
export type BreakoutDirection = z.infer<typeof BreakoutDirection>;

export const Breakout = z.object({
  id: z.string(),
  asset: AssetSymbol,
  timeframe: Timeframe,
  direction: BreakoutDirection,
  level: z.number(),
  close: z.number(),
  bar_range: z.number(),
  expansion_ratio: z.number(),
  strength: z.number(),
  squeeze: z.boolean(),
  signal_bar_at: z.string(),
  detected_at: z.string(),
});
export type Breakout = z.infer<typeof Breakout>;

/** Per-asset intraday-only bias (mirrors BiasReport but derived from 5m). */
export const IntradayBiasReport = z.object({
  asset: AssetSymbol,
  score: z.number(),
  level: BiasLevel,
  signals: z.array(z.string()),
});
export type IntradayBiasReport = z.infer<typeof IntradayBiasReport>;

/** Per-asset intraday reference levels computed on the 5m timeframe. */
export const IntradayLevels = z.object({
  symbol: z.string(),
  asof: z.string(),
  last_price: z.number(),
  hod: z.number(),
  lod: z.number(),
  vwap: z.number().nullable(),
  orh: z.number().nullable(),
  orl: z.number().nullable(),
  pdc: z.number().nullable(),
  pdh: z.number().nullable(),
  pdl: z.number().nullable(),
  ema_9: z.number().nullable(),
  ema_20: z.number().nullable(),
  ema_50: z.number().nullable(),
  ema_200: z.number().nullable(),
  sma_200: z.number().nullable(),
  atr_14: z.number().nullable(),
  last_swing_high: z.number().nullable(),
  last_swing_high_at: z.string().nullable(),
  last_swing_low: z.number().nullable(),
  last_swing_low_at: z.string().nullable(),
});
export type IntradayLevels = z.infer<typeof IntradayLevels>;

export const TradeSetup = z.object({
  asset: AssetSymbol,
  direction: z.enum(["LONG", "SHORT"]),
  trend_label: z.string(),
  continuation_label: z.string(),
  entry_zone_low: z.number(),
  entry_zone_high: z.number(),
  stop_level: z.number(),
  target_level: z.number(),
  risk_reward: z.number(),
  rationale: z.array(z.string()),
});
export type TradeSetup = z.infer<typeof TradeSetup>;

export const NewsItem = z.object({
  headline: z.string(),
  source: z.string(),
  url: z.string(),
  published_at: z.string(),
  summary: z.string().nullable(),
  sentiment_label: z.enum(["positive", "neutral", "negative"]).nullable(),
  sentiment_score: z.number().nullable(),
});
export type NewsItem = z.infer<typeof NewsItem>;

/** The "Perfil do Dia" movement-potential gate. */
export const DayOutlook = z.object({
  asof: z.string(),
  score: z.number(), // 0-100 movement potential
  regime: DayRegime,
  headline: z.string(),
  rationale: z.array(z.string()).default([]),
  is_us_holiday: z.boolean().default(false),
  high_impact_count: z.number().default(0),
  liquidity_ratio: z.number().nullable().default(null),
});
export type DayOutlook = z.infer<typeof DayOutlook>;

/** Latest DashboardTick from /api/tick or /ws/ticks. */
export const DashboardTick = z.object({
  timestamp: z.string(),
  market: MarketSnapshot,
  macro: z.object({
    timestamp: z.string(),
    indicators: z.record(z.string(), z.unknown()),
    fedwatch: z.unknown().nullable(),
  }),
  events_today: z.array(EconomicEvent),
  recent_news: z.array(NewsItem),
  bias: z.record(AssetSymbol, BiasReport),
  setups: z.array(TradeSetup),
  intraday_levels: z.record(AssetSymbol, IntradayLevels).default({}),
  intraday_bias: z.record(AssetSymbol, IntradayBiasReport).default({}),
  breakouts_recent: z.array(Breakout).default([]),
  day_outlook: DayOutlook.nullable().default(null),
});
export type DashboardTick = z.infer<typeof DashboardTick>;

// -----------------------------------------------------------------------------
// Order flow (live DOM / footprint / tape — fed by the MT5 collector)
// -----------------------------------------------------------------------------

export const TradeSide = z.enum(["buy", "sell", "unknown"]);
export type TradeSide = z.infer<typeof TradeSide>;

export const OrderBookLevel = z.object({
  price: z.number(),
  volume: z.number(),
});
export type OrderBookLevel = z.infer<typeof OrderBookLevel>;

export const OrderBookSnapshot = z.object({
  symbol: AssetSymbol,
  asof: z.string(),
  bids: z.array(OrderBookLevel), // best (highest) first
  asks: z.array(OrderBookLevel), // best (lowest) first
});
export type OrderBookSnapshot = z.infer<typeof OrderBookSnapshot>;

export const TapeTrade = z.object({
  symbol: AssetSymbol,
  at: z.string(),
  price: z.number(),
  volume: z.number(),
  side: TradeSide,
});
export type TapeTrade = z.infer<typeof TapeTrade>;

export const FootprintCell = z.object({
  price: z.number(),
  bid_volume: z.number(),
  ask_volume: z.number(),
});
export type FootprintCell = z.infer<typeof FootprintCell>;

export const FootprintBar = z.object({
  symbol: AssetSymbol,
  bar_open: z.string(),
  interval_seconds: z.number(),
  cells: z.array(FootprintCell), // sorted high→low price
  bid_volume: z.number(),
  ask_volume: z.number(),
  delta: z.number(),
  poc_price: z.number().nullable(),
});
export type FootprintBar = z.infer<typeof FootprintBar>;

/** Today's tick-volume vs the same-time-of-day baseline (from the MT5 collector). */
export const SessionLiquidity = z.object({
  symbol: AssetSymbol,
  asof: z.string(),
  realized_volume: z.number(),
  baseline_volume: z.number(),
  ratio: z.number(), // volume: 1.0 = normal participation
  sample_days: z.number(),
  realized_range: z.number().nullable().default(null),
  baseline_range: z.number().nullable().default(null),
  range_ratio: z.number().nullable().default(null), // candle travel vs normal
});
export type SessionLiquidity = z.infer<typeof SessionLiquidity>;

/** Real-time candle/volume read from the live footprint (no baseline needed). */
export const LiveActivity = z.object({
  range_per_bar: z.number(),
  volume_per_bar: z.number(),
  interval_seconds: z.number(),
  sampled_bars: z.number(),
});
export type LiveActivity = z.infer<typeof LiveActivity>;

/** One open MT5 position (read-only mirror), streamed live by the collector. */
export const Position = z.object({
  symbol: AssetSymbol,
  ticket: z.number(),
  side: z.enum(["buy", "sell"]),
  volume: z.number(),
  price_open: z.number(),
  price_current: z.number(),
  profit: z.number(), // floating P&L in account currency
  sl: z.number().nullable().default(null),
  tp: z.number().nullable().default(null),
  seconds_open: z.number(), // time-in-trade at the moment the snapshot was built
});
export type Position = z.infer<typeof Position>;

/** A deterministic in-trade alert about one open position. */
export const TradeSignal = z.object({
  symbol: AssetSymbol,
  ticket: z.number(),
  code: z.enum(["pressure_against", "take_profit"]),
  severity: z.enum(["info", "warn", "urgent"]),
  stance: z.enum(["against", "caution", "favor"]),
  message: z.string(),
});
export type TradeSignal = z.infer<typeof TradeSignal>;

/**
 * THE per-symbol entry/exit signal derived from the live flow — the same
 * object the armed scalper bot acts on (computed once in the backend from the
 * scalper/assess thresholds). Decision support, not advice: on quote-only CFD
 * feeds it reads a synthesized tape.
 */
export const FlowSignal = z.object({
  symbol: AssetSymbol,
  action: z.enum(["enter_long", "enter_short", "exit", "hold"]),
  reason: z.string(),
  strength: z.number(), // 0..1 conviction cue (UI only; the bot ignores it)
  basis: z.enum(["explosion", "lean", "reversal", "against", "exhaustion", "none"]),
});
export type FlowSignal = z.infer<typeof FlowSignal>;

/** One per-symbol order-flow message from /ws/orderflow. */
export const OrderFlowSnapshot = z.object({
  symbol: AssetSymbol,
  asof: z.string(),
  book: OrderBookSnapshot.nullable().default(null),
  recent_trades: z.array(TapeTrade).default([]),
  footprint: z.array(FootprintBar).default([]),
  source: z.string().nullable().default(null),
  account: z.number().nullable().default(null),
  liquidity: SessionLiquidity.nullable().default(null),
  live_activity: LiveActivity.nullable().default(null),
  positions: z.array(Position).default([]),
  signals: z.array(TradeSignal).default([]),
  flow_signal: FlowSignal.nullable().default(null),
});
export type OrderFlowSnapshot = z.infer<typeof OrderFlowSnapshot>;

/** Response from GET /api/orderflow. */
export const OrderFlowList = z.array(OrderFlowSnapshot);

/** State of the whole-account profit-target auto-close (/api/orderflow/autoclose). */
export const AutoCloseStatus = z.object({
  enabled: z.boolean(), // collector permits execution (allow_auto_close)
  armed: z.boolean(),
  target_usd: z.number().nullable().default(null),
  open_profit: z.number(),
  last_fired_at: z.string().nullable().default(null),
  last_result: z.string().nullable().default(null),
});
export type AutoCloseStatus = z.infer<typeof AutoCloseStatus>;

/** Realized account P&L over calendar day/week/month (/api/orderflow/pnl). */
export const AccountPnl = z.object({
  day: z.number(),
  week: z.number(),
  month: z.number(),
  currency: z.string().nullable().default(null),
  asof: z.string().nullable().default(null),
});
export type AccountPnl = z.infer<typeof AccountPnl>;

/** State of the explosion-scalper bot (/api/orderflow/bot). */
export const BotStatus = z.object({
  enabled: z.boolean(), // collector allow_auto_trade AND demo account
  armed: z.boolean(),
  profit_target: z.number(),
  loss_stop: z.number(),
  open_profit: z.number(),
  realized: z.number().default(0),
  open_count: z.number(),
  last_result: z.string().nullable().default(null),
  lots: z.record(z.string(), z.number()).default({}), // per-symbol trade size
});
export type BotStatus = z.infer<typeof BotStatus>;

/** Response from /api/vix/history. */
export const VixHistoryResponse = z.object({
  symbol: z.string(),
  bars: z.array(IntradayBar),
  count: z.number(),
});
export type VixHistoryResponse = z.infer<typeof VixHistoryResponse>;

/** A saved Q&A entry from /api/qa. */
export const QAEntry = z.object({
  id: z.number(),
  question: z.string(),
  answer: z.string(), // markdown
  tags: z.array(z.string()),
  created_at: z.string(),
  updated_at: z.string(),
});
export type QAEntry = z.infer<typeof QAEntry>;

export const QAEntryList = z.array(QAEntry);

/** Create/update payload for /api/qa. */
export interface QAEntryInput {
  question: string;
  answer: string;
  tags: string[];
}

/** Response from /api/brief. */
export const BriefResponse = z.object({
  kind: z.enum(["briefing", "snapshot"]),
  content: z.string(),
  timestamp: z.string(),
  model: z.string().nullable().default(null),
  note: z.string().nullable().default(null),
});
export type BriefResponse = z.infer<typeof BriefResponse>;
