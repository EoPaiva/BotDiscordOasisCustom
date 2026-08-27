import Link from "next/link";

import { CommandState } from "@/components/ui";

export default function Forbidden() {
  return (
    <main className="standalone-state">
      <CommandState
        actions={<Link className="button button-secondary" href="/dashboard">Voltar ao centro</Link>}
        code="AUT / 403"
        happened="Seu perfil atual não possui autorização para consultar esta seção."
        next="Volte ao Centro de Comando e utilize somente as áreas liberadas para o seu perfil."
        title="Acesso não autorizado"
        tone="warning"
      />
    </main>
  );
}
