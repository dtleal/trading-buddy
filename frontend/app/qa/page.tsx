"use client";

import { Header } from "@/components/shared/Header";
import { QAPanel } from "@/components/qa/QAPanel";

export default function QAPage() {
  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-6">
        <QAPanel />
      </main>
    </>
  );
}
