import Link from "next/link";

export default function NotFound() {
  return (
    <main className="standalone-state">
      <span className="technical-index">NAV / 404</span>
      <h1>Registro não localizado</h1>
      <p>A rota ou o registro solicitado não está disponível.</p>
      <Link className="button button-secondary" href="/dashboard">Voltar ao centro</Link>
    </main>
  );
}

