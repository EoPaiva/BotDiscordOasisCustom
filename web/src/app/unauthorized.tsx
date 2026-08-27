import Link from "next/link";

import { CommandState } from "@/components/ui";

export default function Unauthorized() {
  return (
    <main className="standalone-state">
      <CommandState
        actions={<Link className="button button-primary" href="/login">Ir para identificação</Link>}
        code="AUT / 401"
        happened="Esta área exige uma identidade Discord válida e ainda não há uma sessão reconhecida."
        next="Faça a identificação pelo Discord para acessar o Centro de Comando."
        title="Identificação necessária"
        tone="info"
      />
    </main>
  );
}
