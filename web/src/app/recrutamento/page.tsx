import { ArrowRight, BadgeCheck, Clock3, FileText, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { CommandCenterApiError, recruitmentCandidateFetch, recruitmentPublicFetch } from "@/lib/api";
import { getRecruitmentCandidateIdentity } from "@/lib/identity";

import { startRecruitmentApplication } from "./actions";

type Campaign = {
  id: number;
  public_id: string;
  name: string;
  status: string;
  opens_at: number | null;
  closes_at: number | null;
  minimum_age: number;
  maximum_applications: number | null;
};

type Eligibility = {
  eligible: boolean;
  reasons: string[];
  active_application: { id: number; protocol: string; status: string } | null;
  cooldown_until: number | null;
};

const reasonLabels: Record<string, string> = {
  RECRUITMENT_CLOSED: "O processo seletivo não está recebendo novas candidaturas.",
  ACTIVE_MEMBER_LINK: "Sua conta já possui vínculo ativo com o efetivo.",
  ACTIVE_APPLICATION: "Você já possui uma candidatura em andamento.",
  COOLDOWN_ACTIVE: "Existe um período de espera antes de uma nova tentativa.",
  CAPACITY_REACHED: "O limite desta campanha foi atingido.",
  ADMINISTRATIVE_BLOCK: "Existe uma restrição administrativa ativa.",
};

export default async function RecruitmentLandingPage() {
  const identity = await getRecruitmentCandidateIdentity();
  let campaign: Campaign | null = null;
  let eligibility: Eligibility | null = null;
  let unavailable = "";
  try {
    campaign = (await recruitmentPublicFetch<{ campaign: Campaign | null }>("/v1/recruitment/current")).campaign;
    if (identity) eligibility = await recruitmentCandidateFetch<Eligibility>("/v1/recruitment/eligibility");
  } catch (error) {
    unavailable = error instanceof CommandCenterApiError ? error.message : "Portal temporariamente indisponível.";
  }
  const open = campaign?.status === "OPEN";
  return (
    <main className="recruitment-shell">
      <header className="recruitment-masthead">
        <Link className="recruitment-brand" href="/recrutamento"><span>CB</span><div><strong>CHOQUE BGR</strong><small>PROCESSO SELETIVO</small></div></Link>
        <nav><Link href="/minha-candidatura">Minha candidatura</Link>{identity && <Link href="/dashboard">Centro de Comando</Link>}</nav>
      </header>
      <section className="recruitment-hero">
        <div className="recruitment-hero-copy">
          <span className="eyebrow">ALISTAMENTO / INGRESSO INSTITUCIONAL</span>
          <h1>Disciplina antes da função.<br /><strong>Postura antes da patente.</strong></h1>
          <p>O processo de ingresso da CHOQUE BGR avalia disponibilidade, conduta, comunicação, roleplay e capacidade de atuar em equipe sob procedimento.</p>
          <div className="campaign-state"><i className={open ? "operational" : "closed"} /><div><span>SITUAÇÃO DO PROCESSO</span><strong>{campaign?.status ?? "INDISPONÍVEL"}</strong></div><div><span>CAMPANHA</span><strong>{campaign?.name ?? "Nenhuma campanha ativa"}</strong></div></div>
        </div>
        <aside className="recruitment-briefing">
          <span className="technical-index">DIRETRIZ / 01</span>
          <h2>Antes de iniciar</h2>
          <ul>
            <li><ShieldCheck /> Identificação declarada e protegida por protocolo</li>
            <li><FileText /> Aproximadamente 24 questões individuais</li>
            <li><Clock3 /> Cronômetro e autosave controlados pelo servidor</li>
            <li><BadgeCheck /> Decisão final realizada por pessoa autorizada</li>
          </ul>
          <p>Eventos de foco, cópia ou colagem servem apenas como evidência de integridade. Nenhum sinal gera reprovação automática.</p>
        </aside>
      </section>
      <section className="recruitment-intake">
        <div className="intake-heading"><span>02</span><div><h2>Apresentação do candidato</h2><p>Informe seus dados. Não é necessário entrar com o Discord.</p></div></div>
        {unavailable ? <div className="candidate-blocked"><strong>Portal indisponível</strong><p>{unavailable}</p></div> : eligibility?.active_application ? (
          <div className="candidate-login"><h3>Candidatura em andamento</h3><p>Protocolo <strong>{eligibility.active_application.protocol}</strong> • {eligibility.active_application.status}</p><Link className="button button-primary" href={eligibility.active_application.status === "DRAFT" ? "/recrutamento/avaliacao" : "/minha-candidatura"}>Continuar acompanhamento <ArrowRight size={16} /></Link></div>
        ) : open ? (
          <form action={startRecruitmentApplication} className="candidate-start-form">
            <label>ID do Discord<input autoComplete="off" inputMode="numeric" name="discordId" pattern="[0-9]{15,22}" required /></label>
            <label>Usuário no Discord<input autoComplete="username" name="discordUsername" placeholder="usuario" required minLength={2} maxLength={100} /></label>
            <label>Nick no servidor BGR<input autoComplete="nickname" name="candidateNick" required minLength={2} maxLength={80} /></label>
            <label>ID no servidor BGR<input inputMode="numeric" name="bgrId" required maxLength={40} /></label>
            <label>Idade<input inputMode="numeric" name="age" required min={13} max={100} type="number" /></label>
            <label className="consent-field"><input name="consent" required type="checkbox" value="accepted" /><span>Declaro que as informações são verdadeiras e aceito o tratamento dos dados estritamente para recrutamento, auditoria e ingresso na CHOQUE BGR.</span></label>
            <button className="button button-primary" type="submit">Iniciar candidatura <ArrowRight size={16} /></button>
          </form>
        ) : (
          <div className="candidate-blocked"><strong>Candidatura indisponível</strong>{eligibility?.reasons.map((reason) => <p key={reason}>{reasonLabels[reason] ?? reason}</p>)}{eligibility?.cooldown_until && <p>Nova tentativa a partir de <time>{new Date(eligibility.cooldown_until).toLocaleDateString("pt-BR")}</time>.</p>}</div>
        )}
      </section>
      <footer className="recruitment-footer"><span>CHOQUE BGR • SISTEMA DE GESTÃO</span><span>Dados protegidos por controle de acesso e trilha de auditoria</span></footer>
    </main>
  );
}
