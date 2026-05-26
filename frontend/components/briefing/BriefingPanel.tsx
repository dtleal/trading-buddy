"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, ChevronUp, Copy, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

/**
 * On-demand macro briefing.
 *
 * - With CLAUDE_API_KEY: backend returns a Claude-generated briefing in PT-BR.
 * - Without: backend returns the raw markdown payload, ready to be pasted
 *   into Claude Code (/dtb-brief) for a free briefing.
 *
 * The panel collapses by default to avoid pulling focus from the live data.
 */
export function BriefingPanel() {
  const [open, setOpen] = useState(false);

  const brief = useMutation({
    mutationFn: () => api.generateBrief(),
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Erro desconhecido";
      toast.error("Falha ao gerar briefing", { description: msg });
    },
  });

  const handleGenerate = () => {
    setOpen(true);
    brief.mutate();
  };

  const handleCopy = async () => {
    if (!brief.data) return;
    await navigator.clipboard.writeText(brief.data.content);
    toast.success("Copiado pra área de transferência", {
      description: "Cola no Claude Code ou em qualquer LLM.",
    });
  };

  const isLLM = brief.data?.kind === "briefing";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-violet-400" />
              <CardTitle>Briefing macro</CardTitle>
            </div>
            <CardDescription>
              Equivalente ao <code className="text-zinc-300">/dtb-brief</code> do CLI.
              Usa o tick atual + dados macro + headlines.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              onClick={handleGenerate}
              disabled={brief.isPending}
              size="sm"
            >
              {brief.isPending ? (
                <>
                  <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                  gerando…
                </>
              ) : brief.data ? (
                <>
                  <RefreshCw className="mr-1.5 size-3.5" />
                  atualizar
                </>
              ) : (
                <>
                  <Sparkles className="mr-1.5 size-3.5" />
                  gerar briefing
                </>
              )}
            </Button>
            {brief.data && (
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setOpen((v) => !v)}
                aria-label="alternar conteúdo"
              >
                {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      {brief.data && open && (
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge tone={isLLM ? "positive" : "info"}>
              {isLLM ? `via Claude (${brief.data.model ?? "Anthropic API"})` : "snapshot · sem custo"}
            </Badge>
            <span className="tabular-nums text-zinc-500">
              gerado em {new Date(brief.data.timestamp).toLocaleTimeString("pt-BR")}
            </span>
            <div className="ml-auto">
              <Button
                size="sm"
                variant="outline"
                onClick={handleCopy}
                className="h-7"
              >
                <Copy className="mr-1 size-3.5" />
                copiar
              </Button>
            </div>
          </div>

          {brief.data.note && (
            <p className="rounded border border-zinc-800 bg-zinc-900/50 p-2 text-xs italic text-zinc-400">
              {brief.data.note}
            </p>
          )}

          <article
            className={cn(
              // Trader-friendly typography: tight, monospace numbers, light prose
              "prose prose-invert max-w-none prose-sm",
              "prose-headings:font-semibold prose-headings:tracking-tight",
              "prose-h1:text-lg prose-h2:text-base prose-h3:text-sm",
              "prose-p:leading-relaxed",
              "prose-code:rounded prose-code:bg-zinc-900 prose-code:px-1 prose-code:py-0.5 prose-code:text-xs prose-code:before:hidden prose-code:after:hidden",
              "prose-strong:text-zinc-100",
              "prose-a:text-sky-400 prose-a:no-underline hover:prose-a:underline",
              "prose-table:text-xs",
              "prose-li:my-0.5",
            )}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{brief.data.content}</ReactMarkdown>
          </article>
        </CardContent>
      )}
    </Card>
  );
}
