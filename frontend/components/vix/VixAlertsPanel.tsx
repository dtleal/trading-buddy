"use client";

import { useState } from "react";
import { Bell, BellOff, Plus, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAlertsStore } from "@/lib/alerts/store";
import { requestNotificationPermission } from "@/lib/alerts/notify";
import type { AlertRule } from "@/lib/alerts/types";

export function VixAlertsPanel() {
  const rules = useAlertsStore((s) => s.rules);
  const history = useAlertsStore((s) => s.history);
  const toggleRule = useAlertsStore((s) => s.toggleRule);
  const removeRule = useAlertsStore((s) => s.removeRule);
  const addRule = useAlertsStore((s) => s.addRule);
  const clearHistory = useAlertsStore((s) => s.clearHistory);
  const desktopEnabled = useAlertsStore((s) => s.notificationsEnabled);
  const setDesktopEnabled = useAlertsStore((s) => s.setNotificationsEnabled);

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
        <button
          onClick={onToggle}
          className={`h-5 w-9 rounded-full transition-colors ${
            rule.enabled ? "bg-emerald-600" : "bg-zinc-700"
          } relative`}
          aria-label="toggle rule"
        >
          <span
            className={`absolute top-0.5 size-4 rounded-full bg-white transition-transform ${
              rule.enabled ? "translate-x-4" : "translate-x-0.5"
            }`}
          />
        </button>
        <div className="text-sm text-zinc-200">{describeRule(rule)}</div>
      </div>
      <Button variant="ghost" size="icon" onClick={onDelete} aria-label="remover regra">
        <Trash2 className="size-4 text-zinc-500" />
      </Button>
    </div>
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
