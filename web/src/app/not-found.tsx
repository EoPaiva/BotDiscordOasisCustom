import Link from "next/link";

import { CommandState } from "@/components/ui";

export default function NotFound() {
  return (
    <main className="standalone-state">
      <CommandState
        actions={<Link className="button button-secondary" href="/dashboard">Voltar ao centro</Link>}
        code="NAV / 404"
        happened="A rota ou o registro solicitado não está disponível."
        next="Confira o endereço ou retorne ao Centro de Comando para continuar."
        title="Registro não localizado"
      />
    </main>
  );
}
