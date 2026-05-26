/**
 * Domain types mirrored from the Python backend.
 *
 * Each type uses a Zod schema so we get runtime validation at the network
 * boundary (REST + WebSocket). If the backend ever drifts, we fail loudly
 * on parse rather than crashing components reading undefined fields.
 */
import { z } from "zod";

export const AssetSymbol = z.enum(["USTEC", "SPX", "GOLD"]);
export type AssetSymbol = z.infer<typeof AssetSymbol>;

export const VixRegime = z.enum(["low", "mid", "high"]);
export type VixRegime = z.infer<typeof VixRegime>;

export const TermStructure = z.enum(["contango", "flat", "backwardation"]);
export type TermStructure = z.infer<typeof TermStructure>;

export const BiasLevel = z.enum(["bullish", "neutral", "bearish"]);
export type BiasLevel = z.infer<typeof BiasLevel>;

export const ImpactLevel = z.enum(["low", "medium", "high"]);
export type ImpactLevel = z.infer<typeof ImpactLevel>;

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
  intraday_levels: z.record(AssetSymbol, z.unknown()),
  breakouts_recent: z.array(Breakout).default([]),
});
export type DashboardTick = z.infer<typeof DashboardTick>;

/** Response from /api/vix/history. */
export const VixHistoryResponse = z.object({
  symbol: z.string(),
  bars: z.array(IntradayBar),
  count: z.number(),
});
export type VixHistoryResponse = z.infer<typeof VixHistoryResponse>;

/** Response from /api/brief. */
export const BriefResponse = z.object({
  kind: z.enum(["briefing", "snapshot"]),
  content: z.string(),
  timestamp: z.string(),
  model: z.string().nullable().default(null),
  note: z.string().nullable().default(null),
});
export type BriefResponse = z.infer<typeof BriefResponse>;
