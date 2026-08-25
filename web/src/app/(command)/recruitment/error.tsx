"use client";

import Link from "next/link";

export default function RecruitmentErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="standalone-state">
      <span className="technical-index">REC / CONEXÃO</span>
      <h1>Não foi possível carregar o Recrutamento</h1>
      <p>
        A fila não foi alterada. Tente novamente ou renove sua identificação
        pelo Discord antes de continuar uma ação administrativa.
      </p>
      {error.digest && <code>Referência {error.digest}</code>}
      <div className="section-actions">
        <button className="button button-primary" onClick={reset} type="button">
          Tentar novamente
        </button>
        <Link className="button button-secondary" href="/login?reauth=1&returnTo=%2Frecruitment">
          Renovar identificação
        </Link>
      </div>
    </main>
  );
}
