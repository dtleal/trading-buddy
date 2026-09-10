import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  AutoscaleInfo,
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitivePaneRenderer,
  ISeriesPrimitivePaneView,
  Logical,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from "lightweight-charts";
import type { PriceZone } from "@/lib/types";

/**
 * Paints the price zones (`/api/orderflow/zones`) as shaded bands across the
 * whole chart width — the region the market turned at, not a line.
 *
 * lightweight-charts has no rectangle shape, so this is a series primitive:
 * it draws straight onto the chart canvas under the candles, converting each
 * zone's price edges with the series' own `priceToCoordinate`, so the bands
 * stay glued to the price scale through any zoom or pan.
 */

const SELL = { fill: "239,68,68", edge: "248,113,113" }; // red-500 / red-400
const BUY = { fill: "16,185,129", edge: "52,211,153" }; // emerald-500 / 400

/** Fill opacity: the weakest zone is barely there, the strongest is obvious. */
const ALPHA_MIN = 0.10;
const ALPHA_SPAN = 0.22;

/** A band thinner than this (in pixels) is widened so it stays visible when
 * the chart is zoomed out. */
const MIN_HEIGHT_PX = 3;

const LABEL_FONT_PX = 10;
const LABEL_PAD_PX = 6;

/** "3× · 1d+15m" — how many touches and which timeframes agreed. */
function label(zone: PriceZone): string {
  const tfs = zone.timeframes.join("+");
  const both = zone.kind === "both" ? " · 2 lados" : "";
  return `${zone.touches}× ${tfs}${both}`;
}

class ZonesRenderer implements ISeriesPrimitivePaneRenderer {
  constructor(
    private readonly _series: ISeriesApi<"Candlestick", Time>,
    private readonly _zones: readonly PriceZone[],
  ) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const width = scope.bitmapSize.width;
      for (const zone of this._zones) {
        const yHigh = this._series.priceToCoordinate(zone.high);
        const yLow = this._series.priceToCoordinate(zone.low);
        if (yHigh === null || yLow === null) continue;
        const top = Math.round(yHigh * scope.verticalPixelRatio);
        const bottom = Math.round(yLow * scope.verticalPixelRatio);
        const height = Math.max(MIN_HEIGHT_PX * scope.verticalPixelRatio, bottom - top);
        const color = zone.side === "sell" ? SELL : BUY;
        const alpha = ALPHA_MIN + ALPHA_SPAN * Math.min(1, Math.max(0, zone.strength));

        ctx.fillStyle = `rgba(${color.fill},${alpha.toFixed(3)})`;
        ctx.fillRect(0, top, width, height);

        // Edges drawn solid: the exact prices are what gets traded, and a
        // gradient-looking band hides where it actually starts and ends.
        const line = Math.max(1, Math.round(scope.verticalPixelRatio));
        ctx.fillStyle = `rgba(${color.edge},${(0.35 + 0.45 * zone.strength).toFixed(3)})`;
        ctx.fillRect(0, top, width, line);
        ctx.fillRect(0, top + height - line, width, line);

        // Label inside the band, or just under its top edge when the band is
        // too thin to hold the text.
        const font = Math.round(LABEL_FONT_PX * scope.verticalPixelRatio);
        ctx.font = `${font}px ui-sans-serif, system-ui, sans-serif`;
        ctx.textBaseline = "top";
        ctx.fillStyle = `rgba(${color.edge},0.9)`;
        const pad = LABEL_PAD_PX * scope.horizontalPixelRatio;
        const inside = height > font * 1.6;
        ctx.fillText(label(zone), pad, inside ? top + (height - font) / 2 : top + line + 1);
      }
    });
  }
}

class ZonesPaneView implements ISeriesPrimitivePaneView {
  constructor(private readonly _source: ZonesPrimitive) {}

  // Under the candles: the zones are context, the price action is the subject.
  zOrder(): SeriesPrimitivePaneViewZOrder {
    return "bottom";
  }

  renderer(): ISeriesPrimitivePaneRenderer | null {
    const series = this._source.series;
    if (!series || this._source.zones.length === 0) return null;
    return new ZonesRenderer(series, this._source.zones);
  }
}

export class ZonesPrimitive implements ISeriesPrimitive<Time> {
  series: ISeriesApi<"Candlestick", Time> | null = null;
  zones: readonly PriceZone[] = [];
  private readonly _views = [new ZonesPaneView(this)];
  private _requestUpdate: (() => void) | null = null;

  attached(param: SeriesAttachedParameter<Time>): void {
    this.series = param.series as ISeriesApi<"Candlestick", Time>;
    this._requestUpdate = param.requestUpdate;
    this._requestUpdate();
  }

  detached(): void {
    this.series = null;
    this._requestUpdate = null;
  }

  /** Swap in a new set of zones and repaint. */
  setZones(zones: readonly PriceZone[]): void {
    this.zones = zones;
    this._requestUpdate?.();
  }

  paneViews(): readonly ISeriesPrimitivePaneView[] {
    return this._views;
  }

  /**
   * Widen the price scale so the zones fit on screen. Without this the scale
   * only covers the candles, and a zone just above the last high — the one
   * price is heading for — would be drawn off the top of the pane.
   *
   * The caller already limits how far out a zone may be (see the chart), so
   * every zone handed here is meant to be visible.
   */
  autoscaleInfo(_start: Logical, _end: Logical): AutoscaleInfo | null {
    if (this.zones.length === 0) return null;
    return {
      priceRange: {
        minValue: Math.min(...this.zones.map((z) => z.low)),
        maxValue: Math.max(...this.zones.map((z) => z.high)),
      },
    };
  }
}
