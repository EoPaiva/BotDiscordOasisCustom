import { ArrowRight, LockKeyhole, RadioTower } from "lucide-react";
import Image from "next/image";
import { redirect } from "next/navigation";

import { authConfigurationReady, getDiscordIdentity } from "@/lib/identity";
import { resolveLoginDestination } from "@/lib/login-return";

import { loginWithDiscord } from "./actions";

export default async function LoginPage({
  searchParams,
}: PageProps<"/login">) {
  const query = await searchParams;
  const renewing = query.reauth === "1";
  const destination = resolveLoginDestination(query);
  if (!renewing && await getDiscordIdentity()) redirect(destination);
  const ready = authConfigurationReady();

  return (
    <main className="login-shell">
      <section className="login-signature" aria-label="Identidade CHOQUE - BGR">
        <div className="brand-mark brand-emblem" aria-hidden="true"><Image alt="" height={60} priority src="/choque-emblem.png" width={60} /></div>
        <div>
          <span className="eyebrow">SISTEMA INTERNO / ACESSO RESTRITO</span>
          <h1>CHOQUE <strong>BGR</strong></h1>
          <p>CENTRO DE COMANDO</p>
        </div>
      </section>

      <section className="login-panel">
        <div className="technical-index">AUT / 01</div>
        <RadioTower size={27} strokeWidth={1.5} aria-hidden="true" />
          <h2>{renewing ? "Renovar identificação" : "Identificação operacional"}</h2>
          <p>
          {renewing
            ? "Sua confirmação recente expirou. Entre novamente pelo Discord para concluir a ação que estava em andamento."
            : "Entre com sua conta Discord. O acesso será conferido novamente contra o cadastro, a situação funcional e as permissões vigentes."}
          </p>
        {ready ? (
          <form action={loginWithDiscord}>
            <input name="returnTo" type="hidden" value={destination} />
            <button className="button button-primary login-button" type="submit">
              {renewing ? "Renovar com Discord" : "Entrar com Discord"} <ArrowRight size={17} aria-hidden="true" />
            </button>
          </form>
        ) : (
          <div className="configuration-notice" role="status">
            <LockKeyhole size={17} aria-hidden="true" />
            OAuth Discord ainda não configurado neste ambiente.
          </div>
        )}
        <div className="login-footnote">
          <span>Canal seguro</span><span>•</span><span>Sessão limitada a 8 horas</span>
        </div>
      </section>
    </main>
  );
}
