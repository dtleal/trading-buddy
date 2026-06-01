"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, ChevronUp, Loader2, Pencil, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { QAEditor } from "@/components/qa/QAEditor";
import type { QAEntry, QAEntryInput } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * One Q&A entry. Collapsed by default (question + tags); expands to render the
 * markdown answer. Editing swaps the body for an inline `QAEditor`; deleting
 * uses a two-click confirm to avoid an accidental destructive action.
 */
export function QAEntryCard({
  entry,
  onUpdate,
  onDelete,
  updating,
  deleting,
}: {
  entry: QAEntry;
  onUpdate: (id: number, input: QAEntryInput) => void;
  onDelete: (id: number) => void;
  updating: boolean;
  deleting: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleUpdate = (input: QAEntryInput) => {
    onUpdate(entry.id, input);
    setEditing(false);
  };

  if (editing) {
    return (
      <QAEditor
        initial={entry}
        pending={updating}
        onSubmit={handleUpdate}
        onCancel={() => setEditing(false)}
      />
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/60">
      <div className="flex items-start justify-between gap-3 p-4">
        <button
          className="flex flex-1 items-start gap-2 text-left"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          {open ? (
            <ChevronUp className="mt-0.5 size-4 shrink-0 text-zinc-500" />
          ) : (
            <ChevronDown className="mt-0.5 size-4 shrink-0 text-zinc-500" />
          )}
          <span className="text-sm font-medium text-zinc-100">{entry.question}</span>
        </button>

        <div className="flex shrink-0 items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            className="size-7"
            onClick={() => setEditing(true)}
            aria-label="editar"
          >
            <Pencil className="size-3.5" />
          </Button>
          <Button
            size="sm"
            variant={confirmDelete ? "destructive" : "ghost"}
            className="h-7"
            onClick={() => {
              if (confirmDelete) {
                onDelete(entry.id);
              } else {
                setConfirmDelete(true);
              }
            }}
            onBlur={() => setConfirmDelete(false)}
            disabled={deleting}
            aria-label="excluir"
          >
            {deleting ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Trash2 className="size-3.5" />
            )}
            {confirmDelete && <span className="ml-1 text-xs">confirmar?</span>}
          </Button>
        </div>
      </div>

      {open && (
        <div className="space-y-3 px-4 pb-4">
          <article
            className={cn(
              "prose prose-invert max-w-none prose-sm",
              "prose-headings:font-semibold prose-headings:tracking-tight",
              "prose-h1:text-base prose-h2:text-sm prose-h3:text-sm",
              "prose-p:leading-relaxed",
              "prose-code:rounded prose-code:bg-zinc-900 prose-code:px-1 prose-code:py-0.5 prose-code:text-xs prose-code:before:hidden prose-code:after:hidden",
              "prose-strong:text-zinc-100",
              "prose-li:my-0.5",
            )}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.answer}</ReactMarkdown>
          </article>

          <div className="flex flex-wrap items-center gap-2 border-t border-zinc-900 pt-2">
            {entry.tags.map((tag) => (
              <Badge key={tag} tone="info">
                {tag}
              </Badge>
            ))}
            <span className="ml-auto text-xs tabular-nums text-zinc-600">
              atualizado em {new Date(entry.updated_at).toLocaleString("pt-BR")}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
