"use client";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="standalone-state">
      <span className="technical-index">SYS / FALHA</span>
      <h1>Comunicação interrompida</h1>
      <p>{error.message}</p>
      {error.digest && <code>Referência {error.digest}</code>}
      <button className="button button-primary" onClick={reset}>Tentar novamente</button>
    </main>
  );
}
