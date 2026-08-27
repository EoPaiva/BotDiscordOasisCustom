"use client";

import { CommandState } from "@/components/ui";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="standalone-state">
      <CommandState
        actions={<button className="button button-primary" onClick={reset}>Tentar novamente</button>}
        code="SYS / FALHA"
        happened="Uma parte do sistema não conseguiu concluir o carregamento. Nenhuma confirmação deve ser presumida."
        next="Tente novamente. Se o problema continuar, informe a referência ao responsável pelo sistema."
        reference={error.digest}
        title="Comunicação interrompida"
        tone="danger"
      />
    </main>
  );
}
