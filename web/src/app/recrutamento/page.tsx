import {
  ArrowDown,
  ArrowRight,
  Check,
  ClipboardCheck,
  Clock3,
  RadioTower,
  Search,
  ShieldCheck,
} from "lucide-react";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { recruitmentCandidateFetch, recruitmentPublicFetch } from "@/lib/api";
import { getRecruitmentCandidateIdentity } from "@/lib/identity";

import { startRecruitmentApplication } from "./actions";

export const metadata: Metadata = {
  title: "Recrutamento",
  description: "Inicie e acompanhe sua candidatura oficial para a CHOQUE - BGR.",
  alternates: { canonical: "/recrutamento" },
};

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

const steps = [
  {
    number: "01",
    title: "Identificação",
    description: "Informe somente os dados necessários para localizar sua ficha no Discord e no BGR.",
    meta: "cerca de 2 min",
  },
  {
    number: "02",
    title: "Avaliação operacional",
    description: "Responda 10 questões curtas sobre Roleplay policial, comunicação e códigos Q.",
    meta: "cerca de 6 a 9 min",
  },
  {
    number: "03",
    title: "Análise humana",
    description: "O Comando confere o alistamento, registra a decisão e atualiza o protocolo no Discord.",
    meta: "acompanhamento por protocolo",
  },
];

export default async function RecruitmentLandingPage() {
  const identity = await getRecruitmentCandidateIdentity();
  let campaign: Campaign | null = null;
  let eligibility: Eligibility | null = null;
  let unavailable = "";
  try {
    campaign = (await recruitmentPublicFetch<{ campaign: Campaign | null }>("/v1/recruitment/current")).campaign;
    if (identity) eligibility = await recruitmentCandidateFetch<Eligibility>("/v1/recruitment/eligibility");
  } catch {
    unavailable = "A Central de Recrutamento não respondeu. Nenhuma candidatura foi iniciada ou alterada.";
  }
  const open = campaign?.status === "OPEN";
  const activeApplication = eligibility?.active_application;
  const primaryHref = activeApplication
    ? activeApplication.status === "DRAFT"
      ? "/recrutamento/avaliacao"
      : "/minha-candidatura"
    : "#candidatura";
  const primaryLabel = activeApplication ? "Continuar candidatura" : "Iniciar candidatura";

  return (
    <main className="recruitment-shell recruitment-redesign">
      <header className="recruitment-masthead">
        <Link className="recruitment-brand" href="/recrutamento">
          <span className="recruitment-brand-mark">
            <Image alt="" aria-hidden="true" height={38} priority src="/choque-emblem.png" width={38} />
          </span>
          <div><strong>CHOQUE BGR</strong><small>POSTO DIGITAL DE ALISTAMENTO</small></div>
        </Link>
        <nav aria-label="Navegação do recrutamento">
          <Link href="/minha-candidatura"><Search size={14} /> Consultar candidatura</Link>
          {identity && <Link href="/dashboard">Centro de Comando</Link>}
        </nav>
      </header>

      <section className="enlistment-hero">
        <span aria-hidden="true" className="enlistment-watermark">CHOQUE</span>
        <div className="enlistment-hero-copy">
          <div className="enlistment-kicker">
            <span />
            <p>{open ? "ALISTAMENTO ABERTO" : "ALISTAMENTO EM CONSULTA"}</p>
          </div>
          <h1>Seu primeiro passo<br /><strong>começa pela postura.</strong></h1>
          <p className="enlistment-lead">
            Entre para a CHOQUE - BGR por um processo direto, transparente e feito para respeitar
            seu tempo. Você conclui tudo em poucos minutos e acompanha o resultado pelo protocolo.
          </p>
          <div className="enlistment-actions">
            <Link className="enlistment-primary-action" href={primaryHref}>
              {primaryLabel} <ArrowRight size={18} />
            </Link>
            <Link className="enlistment-secondary-action" href="/minha-candidatura">
              <Search size={16} /> Já me candidatei
            </Link>
          </div>
          <div className="enlistment-time"><Clock3 size={17} /><span><strong>8 a 12 minutos</strong> para concluir • sem anexos</span></div>
        </div>
        <aside className="enlistment-brief">
          <span className="enlistment-serial">DIRETRIZ / 01</span>
          <div className="enlistment-emblem" aria-hidden="true">
            <Image alt="" fill priority sizes="(max-width: 980px) 132px, 168px" src="/choque-emblem.png" />
          </div>
          <h2>O que você precisa</h2>
          <ul>
            <li><Check size={15} /> Conta ativa no Discord</li>
            <li><Check size={15} /> Nick e ID utilizados no BGR</li>
            <li><Check size={15} /> Noções de RP policial e códigos Q</li>
          </ul>
          <p>10 QUESTÕES <i /> 3 ETAPAS <i /> 1 PROTOCOLO</p>
        </aside>
        <a className="enlistment-scroll" href="#como-funciona"><ArrowDown size={16} /> Entenda o processo</a>
      </section>

      <section className="enlistment-process" id="como-funciona" aria-labelledby="process-title">
        <header>
          <span className="technical-index">PROCESSO / 03 ETAPAS</span>
          <h2 id="process-title">Simples do início ao resultado.</h2>
          <p>Uma etapa por vez, sem telas desnecessárias e sem repetir informações.</p>
        </header>
        <ol>
          {steps.map((step) => (
            <li key={step.number}>
              <span>{step.number}</span>
              <div><h3>{step.title}</h3><p>{step.description}</p><small>{step.meta}</small></div>
            </li>
          ))}
        </ol>
      </section>

      <section className="recruitment-intake" id="candidatura">
        <div className="recruitment-intake-layout">
          <div className="intake-copy">
            <span className="technical-index">FICHA / IDENTIFICAÇÃO</span>
            <h2>{activeApplication ? "Continue de onde parou." : "Vamos começar."}</h2>
            <p>
              Seus dados são usados somente no processo seletivo. As respostas ficam restritas ao
              Comando; no Discord público aparece apenas o protocolo e a etapa.
            </p>
            <div className="intake-trust-line"><ShieldCheck size={18} /><span>Decisão final sempre realizada por pessoa autorizada.</span></div>
          </div>

          <div className="intake-operation">
            <div className="campaign-state">
              <i className={open ? "operational" : "closed"} />
              <div><span>SITUAÇÃO</span><strong>{campaign?.status ?? "INDISPONÍVEL"}</strong></div>
              <div><span>CAMPANHA</span><strong>{campaign?.name ?? "Nenhuma campanha ativa"}</strong></div>
            </div>
            {unavailable ? (
              <div className="candidate-blocked" role="alert"><strong>Portal indisponível</strong><p>{unavailable}</p><p>Atualize a página em alguns instantes antes de tentar novamente.</p></div>
            ) : activeApplication ? (
              <div className="candidate-login">
                <ClipboardCheck size={28} />
                <div><h3>Candidatura em andamento</h3><p>Protocolo <strong>{activeApplication.protocol}</strong> • {activeApplication.status}</p></div>
                <Link className="button button-primary" href={primaryHref}>Continuar <ArrowRight size={16} /></Link>
              </div>
            ) : open && (!identity || eligibility?.eligible === true) ? (
              <form action={startRecruitmentApplication} className="candidate-start-form">
                <label className="wide-field">ID do Discord<input autoComplete="off" inputMode="numeric" name="discordId" pattern="[0-9]{15,22}" required placeholder="Ex.: 123456789012345678" /></label>
                <label>Usuário no Discord<input autoComplete="username" name="discordUsername" placeholder="usuario" required minLength={2} maxLength={100} /></label>
                <label>Nick no servidor BGR<input autoComplete="nickname" name="candidateNick" placeholder="Seu nick no jogo" required minLength={2} maxLength={80} /></label>
                <label>ID no servidor BGR<input inputMode="numeric" name="bgrId" placeholder="Seu ID" required maxLength={40} /></label>
                <label>Idade<input inputMode="numeric" name="age" required min={13} max={100} type="number" /></label>
                <label className="consent-field"><input name="consent" required type="checkbox" value="accepted" /><span>Confirmo que os dados são verdadeiros e autorizo seu uso somente para recrutamento, auditoria e ingresso na CHOQUE - BGR.</span></label>
                <button className="enlistment-primary-action" type="submit">Avançar para as 10 questões <ArrowRight size={17} /></button>
              </form>
            ) : (
              <div className="candidate-blocked"><strong>{open ? "Candidatura não pode ser iniciada" : "Candidatura indisponível"}</strong>{eligibility?.reasons.map((reason) => <p key={reason}>{reasonLabels[reason] ?? reason}</p>)}{eligibility?.cooldown_until && <p>Nova tentativa a partir de <time>{new Date(eligibility.cooldown_until).toLocaleString("pt-BR")}</time>.</p>}</div>
            )}
          </div>
        </div>
      </section>

      <section className="enlistment-focus" aria-label="Conteúdo da avaliação">
        <RadioTower size={25} />
        <div><span>AVALIAÇÃO OBJETIVA</span><strong>Roleplay policial • comunicação • códigos Q • postura operacional</strong></div>
        <Link href="#candidatura">Começar agora <ArrowRight size={15} /></Link>
      </section>

      <footer className="recruitment-footer"><span>CHOQUE - BGR • SISTEMA DE GESTÃO</span><span>Alistamento oficial • dados protegidos por controle de acesso</span></footer>
    </main>
  );
}
