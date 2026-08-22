import Link from "next/link";

export default async function AccessDeniedPage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string }>;
}) {
  const { reason } = await searchParams;
  const permissionRevoked = reason === "permission-revoked";
  return (
    <main className="standalone-state">
      <span className="technical-index">AUT / 403</span>
      <h1>{permissionRevoked ? "Acesso atualizado" : "Acesso não autorizado"}</h1>
      <p>{permissionRevoked
        ? "Seus cargos Discord mudaram e você não possui mais acesso à área que estava aberta."
        : "A conta Discord foi reconhecida, mas não corresponde a um membro autorizado."}</p>
      <Link className="button button-secondary" href={permissionRevoked ? "/dashboard" : "/login"}>
        {permissionRevoked ? "Voltar ao Centro de Comando" : "Voltar à identificação"}
      </Link>
    </main>
  );
}
