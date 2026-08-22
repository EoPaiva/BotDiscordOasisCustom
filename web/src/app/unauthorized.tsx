import Link from "next/link";

export default function Unauthorized() {
  return (
    <main className="standalone-state">
      <span className="technical-index">AUT / 401</span>
      <h1>Identificação necessária</h1>
      <p>Faça login com o Discord para acessar o Centro de Comando.</p>
      <Link className="button button-primary" href="/login">Ir para identificação</Link>
    </main>
  );
}

