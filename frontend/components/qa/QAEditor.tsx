"use client";

import { useState } from "react";
import { Loader2, Save, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { QAEntry, QAEntryInput } from "@/lib/types";

/**
 * Create/edit form for a Q&A entry. Tags are entered comma-separated and
 * split client-side; the backend still normalises them (trim/lowercase/dedupe),
 * so we keep the parsing here deliberately forgiving.
 */
export function QAEditor({
  initial,
  pending,
  onSubmit,
  onCancel,
}: {
  initial?: QAEntry;
  pending: boolean;
  onSubmit: (input: QAEntryInput) => void;
  onCancel: () => void;
}) {
  const [question, setQuestion] = useState(initial?.question ?? "");
  const [answer, setAnswer] = useState(initial?.answer ?? "");
  const [tags, setTags] = useState((initial?.tags ?? []).join(", "));

  const canSave = question.trim().length > 0 && answer.trim().length > 0 && !pending;

  const handleSubmit = () => {
    if (!canSave) return;
    onSubmit({
      question: question.trim(),
      answer: answer.trim(),
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    });
  };

  return (
    <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="space-y-1.5">
        <label className="text-xs font-medium uppercase tracking-wider text-zinc-400">
          Pergunta
        </label>
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ex: vale a pena operar lateralidade na Bollinger?"
          autoFocus
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium uppercase tracking-wider text-zinc-400">
          Resposta <span className="text-zinc-600">(markdown)</span>
        </label>
        <Textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Use **negrito**, listas com -, títulos com ##…"
          rows={10}
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium uppercase tracking-wider text-zinc-400">
          Tags <span className="text-zinc-600">(separadas por vírgula)</span>
        </label>
        <Input
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="bollinger, lateralidade, 5min"
        />
      </div>

      <div className="flex items-center justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={pending}>
          <X className="mr-1 size-3.5" />
          cancelar
        </Button>
        <Button size="sm" onClick={handleSubmit} disabled={!canSave}>
          {pending ? (
            <Loader2 className="mr-1.5 size-3.5 animate-spin" />
          ) : (
            <Save className="mr-1.5 size-3.5" />
          )}
          salvar
        </Button>
      </div>
    </div>
  );
}
