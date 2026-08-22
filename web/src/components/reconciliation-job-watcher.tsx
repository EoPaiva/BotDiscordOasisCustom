"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const TERMINAL = new Set(["COMPLETED", "FAILED"]);

export function ReconciliationJobWatcher({
  jobId,
  initialStatus,
}: {
  jobId: number;
  initialStatus: string;
}) {
  const [status, setStatus] = useState(initialStatus.toUpperCase());
  const router = useRouter();

  useEffect(() => {
    if (TERMINAL.has(status)) return;
    let disposed = false;
    let running = false;
    const check = async () => {
      if (disposed || running || document.visibilityState !== "visible" || !navigator.onLine) return;
      running = true;
      try {
        const response = await fetch(`/api/discord-reconciliation/${jobId}`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok || disposed) return;
        const payload = await response.json() as { job?: { status?: string } };
        const nextStatus = String(payload.job?.status ?? status).toUpperCase();
        setStatus(nextStatus);
        if (TERMINAL.has(nextStatus)) router.refresh();
      } catch {
        // A próxima janela repete a leitura; nenhuma mutação é assumida no cliente.
      } finally {
        running = false;
      }
    };
    const interval = window.setInterval(() => void check(), 3_000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [jobId, router, status]);

  if (TERMINAL.has(status)) return null;
  return <p className="job-live-state" aria-live="polite">Atualização automática ativa · {status.replaceAll("_", " ")}</p>;
}
