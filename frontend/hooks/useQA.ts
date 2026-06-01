"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { QAEntryInput } from "@/lib/types";

const QA_KEY = ["qa"] as const;

/** Fetch all saved Q&A entries (most recently updated first). */
export function useQAEntries() {
  return useQuery({
    queryKey: QA_KEY,
    queryFn: () => api.listQA(),
  });
}

/**
 * Create / update / delete share a single invalidation of the list query so
 * the panel always reflects the server state after a mutation settles.
 */
export function useCreateQA() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: QAEntryInput) => api.createQA(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: QA_KEY }),
  });
}

export function useUpdateQA() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: QAEntryInput }) =>
      api.updateQA(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: QA_KEY }),
  });
}

export function useDeleteQA() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteQA(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: QA_KEY }),
  });
}
