"use client";

import { useState } from "react";
import { Bell, BellOff, Plus, Trash2, Volume2, VolumeX } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAlertsStore } from "@/lib/alerts/store";
import { requestNotificationPermission } from "@/lib/alerts/notify";
import { playAlertSound, unlockAudio } from "@/lib/alerts/sound";
import type { AlertRule } from "@/lib/alerts/types";
import { cn } from "@/lib/utils";

export function VixAlertsPanel() {
  const rules = useAlertsStore((s) => s.rules);
  const history = useAlertsStore((s) => s.history);
  const toggleRule = useAlertsStore((s) => s.toggleRule);
  const removeRule = useAlertsStore((s) => s.removeRule);
  const addRule = useAlertsStore((s) => s.addRule);
  const clearHistory = useAlertsStore((s) => s.clearHistory);
  const desktopEnabled = useAlertsStore((s) => s.notificationsEnabled);
  const setDesktopEnabled = useAlertsStore((s) => s.setNotificationsEnabled);
  const soundEnabled = useAlertsStore((s) => s.soundEnabled);
  const setSoundEnabled = useAlertsStore((s) => s.setSoundEnabled);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Alertas VIX</CardTitle>
            <CardDescription>
              Regras determinísticas. Toast in-app sempre dispara; notificação do
              browser depende de permissão.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <SoundToggle
              enabled={soundEnabled}
              onToggle={() => {
                const next = !soundEnabled;
                setSoundEnabled(next);
                // The click is the user gesture that unlocks Web Audio. Beep
                // once on enable so the user confirms it's actually audible.
                if (next) {
                  unlockAudio();
                  playAlertSound("info");
                }
              }}
            />
            <DesktopToggle
              enabled={desktopEnabled}
              onToggle={async () => {
                if (!desktopEnabled) {
                  const granted = await requestNotificationPermission();
                  setDesktopEnabled(granted);
                } else {
                  setDesktopEnabled(false);
                }
              }}
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <section>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
            Regras ({rules.filter((r) => r.enabled).length} ativas)
          </h4>
          <div className="space-y-2">
            {rules.map((rule) => (
              <RuleRow
                key={rule.id}
                rule={rule}
                onToggle={() => toggleRule(rule.id)}
                onDelete={() => removeRule(rule.id)}
              />
            ))}
          </div>
          <NewRuleForm onAdd={(rule) => addRule(rule)} />
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
              Histórico ({history.length})
            </h4>
            {history.length > 0 && (
              <Button variant="ghost" size="sm" onClick={clearHistory}>
                limpar
              </Button>
            )}
          </div>
          {history.length === 0 ? (
            <p className="text-sm text-zinc-500">
              Sem alertas disparados ainda. As regras avaliam a cada novo tick.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {history.slice(0, 20).map((event) => (
                <li
                  key={event.id}
                  className="rounded border border-zinc-800 bg-zinc-900/40 p-2.5 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-zinc-100">{event.title}</span>
                    <span className="text-xs text-zinc-500">
                      {new Date(event.firedAt).toLocaleTimeString("pt-BR")}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-zinc-400">{event.detail}</div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </CardContent>
    </Card>
  );
}

function DesktopToggle({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onToggle}>
      {enabled ? <Bell className="mr-1.5 size-4" /> : <BellOff className="mr-1.5 size-4" />}
      {enabled ? "notificações ativas" : "ativar notificações"}
    </Button>
  );
}

function SoundToggle({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onToggle}
      aria-pressed={enabled}
      title={enabled ? "som dos alertas ligado" : "som dos alertas desligado"}
    >
      {enabled ? <Volume2 className="mr-1.5 size-4" /> : <VolumeX className="mr-1.5 size-4" />}
      {enabled ? "som ativo" : "som off"}
    </Button>
  );
}

function RuleRow({
  rule,
  onToggle,
  onDelete,
}: {
  rule: AlertRule;
  onToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded border border-zinc-800 bg-zinc-900/30 p-2.5">
      <div className="flex items-center gap-3">
        <ToggleSwitch enabled={rule.enabled} onToggle={onToggle} />
        <div className="text-sm text-zinc-200">{describeRule(rule)}</div>
      </div>
      <Button variant="ghost" size="icon" onClick={onDelete} aria-label="remover regra">
        <Trash2 className="size-4 text-zinc-500" />
      </Button>
    </div>
  );
}

/**
 * Accessible toggle switch. Track 44×24px, thumb 20×20, 2px gap each side.
 * Dot travels exactly 20px between states (44 - 20 - 2 - 2).
 */
function ToggleSwitch({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      onClick={onToggle}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900",
        enabled ? "bg-emerald-600" : "bg-zinc-700",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "block size-5 rounded-full bg-white shadow ring-1 ring-black/10 transition-transform",
          enabled ? "translate-x-5" : "translate-x-0",
        )}
      />
    </button>
  );
}

function describeRule(rule: AlertRule): string {
  switch (rule.kind) {
    case "vix_cross":
      return `VIX cruzar ${rule.level} (${rule.direction})`;
    case "regime_change":
      return rule.to ? `Regime → ${rule.to}` : "Qualquer mudança de regime";
    case "term_flip":
      return rule.to ? `Term structure → ${rule.to}` : "Qualquer flip da term structure";
    case "vix_delta":
      return `VIX moveu ${rule.pct_change}% em ${Math.round(rule.window_seconds / 60)}min`;
  }
}

function NewRuleForm({ onAdd }: { onAdd: (rule: AlertRule) => void }) {
  const [level, setLevel] = useState("");

  const handleAdd = () => {
    const n = parseFloat(level);
    if (!Number.isFinite(n) || n <= 0) return;
    onAdd({
      id: `cross-${Date.now()}`,
      kind: "vix_cross",
      level: n,
      direction: "either",
      enabled: true,
    });
    setLevel("");
  };

  return (
    <div className="mt-3 flex items-center gap-2">
      <input
        type="number"
        inputMode="decimal"
        placeholder="nível ex 18"
        value={level}
        onChange={(e) => setLevel(e.target.value)}
        className="h-8 w-32 rounded border border-zinc-700 bg-zinc-900 px-2 text-sm text-zinc-100 placeholder-zinc-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      />
      <Button size="sm" onClick={handleAdd} disabled={!level}>
        <Plus className="mr-1 size-3.5" />
        adicionar regra de cruzamento
      </Button>
      <Badge tone="info" className="ml-auto">
        ativa nos dois sentidos
      </Badge>
    </div>
  );
}
