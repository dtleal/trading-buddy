"use client";

import { useMemo, useState } from "react";
import { BookOpen, Plus, Search } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { QAEditor } from "@/components/qa/QAEditor";
import { QAEntryCard } from "@/components/qa/QAEntryCard";
import { useCreateQA, useDeleteQA, useQAEntries, useUpdateQA } from "@/hooks/useQA";
import type { QAEntry, QAEntryInput } from "@/lib/types";

function matches(entry: QAEntry, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    entry.question.toLowerCase().includes(q) ||
    entry.answer.toLowerCase().includes(q) ||
    entry.tags.some((t) => t.includes(q))
  );
}

/**
 * The Q&A knowledge base: a searchable list of saved question/answer pairs the
 * user curates as a day-to-day trading playbook. Create at the top, edit/delete
 * inline on each card.
 */
export function QAPanel() {
  const { data: entries, isLoading, isError, error } = useQAEntries();
  const create = useCreateQA();
  const update = useUpdateQA();
  const remove = useDeleteQA();

  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = useMemo(
    () => (entries ?? []).filter((e) => matches(e, search)),
    [entries, search],
  );

  const handleCreate = (input: QAEntryInput) => {
    create.mutate(input, {
      onSuccess: () => {
        setCreating(false);
        toast.success("Pergunta salva");
      },
      onError: (err) => toast.error("Falha ao salvar", { description: msg(err) }),
    });
  };

  const handleUpdate = (id: number, input: QAEntryInput) => {
    update.mutate(
      { id, input },
      {
        onSuccess: () => toast.success("Pergunta atualizada"),
        onError: (err) => toast.error("Falha ao atualizar", { description: msg(err) }),
      },
    );
  };

  const handleDelete = (id: number) => {
    remove.mutate(id, {
      onSuccess: () => toast.success("Pergunta excluída"),
      onError: (err) => toast.error("Falha ao excluir", { description: msg(err) }),
    });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <BookOpen className="size-4 text-sky-400" />
              <CardTitle>Perguntas &amp; Respostas</CardTitle>
            </div>
            <CardDescription>
              Seu caderno de respostas pro dia a dia — busque, adicione e edite.
            </CardDescription>
          </div>
          <Button size="sm" onClick={() => setCreating((v) => !v)}>
            <Plus className="mr-1.5 size-3.5" />
            nova
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {creating && (
          <QAEditor
            pending={create.isPending}
            onSubmit={handleCreate}
            onCancel={() => setCreating(false)}
          />
        )}

        <div className="relative">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-500" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por pergunta, resposta ou tag…"
            className="pl-9"
          />
        </div>

        {isLoading && <p className="text-sm text-zinc-500">Carregando…</p>}

        {isError && (
          <p className="rounded border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
            Não foi possível carregar as perguntas. {msg(error)}
          </p>
        )}

        {!isLoading && !isError && filtered.length === 0 && (
          <p className="py-8 text-center text-sm text-zinc-500">
            {search
              ? "Nenhuma pergunta corresponde à busca."
              : "Nenhuma pergunta salva ainda. Clique em “nova” pra começar."}
          </p>
        )}

        <div className="space-y-3">
          {filtered.map((entry) => (
            <QAEntryCard
              key={entry.id}
              entry={entry}
              onUpdate={handleUpdate}
              onDelete={handleDelete}
              updating={update.isPending}
              deleting={remove.isPending}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function msg(err: unknown): string {
  return err instanceof Error ? err.message : "Erro desconhecido";
}
