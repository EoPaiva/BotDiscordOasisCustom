import Link from "next/link";

import { CommandState } from "@/components/ui";

export default async function AccessDeniedPage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string }>;
}) {
  const { reason } = await searchParams;
  const permissionRevoked = reason === "permission-revoked";
  return (
    <main className="standalone-state">
      <CommandState
        actions={(
          <Link className="button button-secondary" href={permissionRevoked ? "/dashboard" : "/login"}>
            {permissionRevoked ? "Voltar ao Centro de Comando" : "Voltar à identificação"}
          </Link>
        )}
        code="AUT / 403"
        happened={permissionRevoked
          ? "Seus cargos Discord mudaram e a área que estava aberta deixou de fazer parte do seu acesso."
          : "A conta Discord foi reconhecida, mas não corresponde a um membro autorizado."}
        next={permissionRevoked
          ? "Retorne ao Centro de Comando; a navegação será atualizada conforme suas permissões atuais."
          : "Volte à identificação ou procure um responsável se seu cadastro deveria estar ativo."}
        title={permissionRevoked ? "Acesso atualizado" : "Acesso não autorizado"}
        tone="warning"
      />
    </main>
  );
}
