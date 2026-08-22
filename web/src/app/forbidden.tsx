import Link from "next/link";

export default function Forbidden() {
  return (
    <main className="standalone-state">
      <span className="technical-index">AUT / 403</span>
      <h1>Acesso não autorizado</h1>
      <p>Seu perfil atual não possui acesso a esta seção.</p>
      <Link className="button button-secondary" href="/dashboard">Voltar ao centro</Link>
    </main>
  );
}

