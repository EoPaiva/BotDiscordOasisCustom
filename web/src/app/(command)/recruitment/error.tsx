"use client";

import Link from "next/link";

import { CommandState } from "@/components/ui";

export default function RecruitmentErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <CommandState
      actions={(
        <>
          <button className="button button-primary" onClick={reset} type="button">
            Tentar novamente
          </button>
          <Link className="button button-secondary" href="/login?reauth=1&returnTo=%2Frecruitment">
            Renovar identificação
          </Link>
        </>
      )}
      className="command-state-contained"
      code="REC / CONEXÃO"
      happened="O recrutamento não pôde ser carregado. A fila e a candidatura não foram alteradas."
      next="Tente novamente. Se o erro persistir, renove sua identificação pelo Discord antes de continuar."
      reference={error.digest}
      title="Não foi possível carregar o Recrutamento"
      tone="danger"
    />
  );
}
