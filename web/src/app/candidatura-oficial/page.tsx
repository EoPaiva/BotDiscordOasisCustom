import { ArrowRight, CheckCircle2, Clock3, ShieldCheck } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CommandCenterApiError, commandCenterFetch } from "@/lib/api";
import { duration, label } from "@/lib/format";
import { getDiscordIdentity } from "@/lib/identity";
import { buildLoginUrl } from "@/lib/login-return";

import {
  saveOfficerDraft,
  startOfficerApplication,
  submitOfficerApplication,
} from "./actions";

type Question = {
  id: number;
  question_number: number;
  competency: string;
  question_type: string;
  prompt: string;
};

type Questionnaire = {
  id: number;
  version_number: number;
  title: string;
  criteria: { advisory_only: boolean; final_decision: string };
  questions: Question[];
};

type Eligibility = {
  eligible: boolean;
  missing: string[];
  rank_name: string | null;
  minimum_rank_name: string;
  valid_hours_ms: number;
  minimum_valid_hours_ms: number;
  resubmit_after: number | null;
};

type ApplicationDetail = {
  application: {
    id: number;
    status: string;
    submitted_at: number | null;
    reviewed_at: number | null;
    decision_reason: string | null;
    result_released_at: number | null;
  };
  answers: Array<Question & { answer_text: string | null }>;
  conditions: Array<{ condition_text: string; due_at: number | null; status: string }>;
};

const missingLabels: Record<string, string> = {
  STATUS: "Seu cadastro precisa estar ativo.",
  IDENTIDADE: "Complete seu nick e ID BGR na Portaria.",
  VINCULO_DISCORD: "Reconcilie seu vínculo atual com o Discord.",
  PATENTE: "A patente mínima é Soldado.",
  HORAS: "Complete cinco horas válidas de serviço.",
  COOLDOWN: "Aguarde o período de reaplicação informado abaixo.",
};

function applicationStatus(status: string) {
  const values: Record<string, string> = {
    DRAFT: "Rascunho",
    SUBMITTED: "Enviada",
    IN_REVIEW: "Em análise humana",
    INTERVIEW_REQUIRED: "Entrevista necessária",
    APPROVED_CONDITIONAL: "Aprovada com condição",
    APPROVED: "Aprovada",
    REJECTED: "Reprovada",
    RETURNED: "Devolvida para ajuste",
    CANCELLED: "Cancelada",
  };
  return values[status] ?? label(status);
}

export default async function OfficerApplicationPage() {
  if (!(await getDiscordIdentity())) {
    redirect(buildLoginUrl("/candidatura-oficial", process.env.AUTH_URL));
  }
  let eligibility: Eligibility;
  let questionnaire: Questionnaire;
  let current: ApplicationDetail | null;
  try {
    [eligibility, questionnaire, current] = await Promise.all([
      commandCenterFetch<Eligibility>("/v1/officer-candidacy/eligibility"),
      commandCenterFetch<Questionnaire>("/v1/officer-candidacy/questionnaire"),
      commandCenterFetch<ApplicationDetail | null>("/v1/officer-candidacy/application"),
    ]);
  } catch (error) {
    const message = error instanceof CommandCenterApiError
      ? error.message
      : "A candidatura ao oficialato está temporariamente indisponível.";
    return <main className="recruitment-shell"><section className="command-section"><h1>Candidatura ao Oficialato</h1><p>{message}</p><Link className="button button-secondary" href="/">Voltar</Link></section></main>;
  }

  const application = current?.application;
  const editable = application?.status === "DRAFT" || application?.status === "RETURNED";
  const answers = new Map(current?.answers.map((item) => [item.question_number, item.answer_text ?? ""]));

  return <main className="recruitment-shell officer-application-shell">
    <header className="recruitment-masthead">
      <Link className="recruitment-brand" href="/"><span className="recruitment-brand-mark"><Image alt="" aria-hidden="true" height={38} src="/choque-emblem.png" width={38} /></span><div><strong>CHOQUE BGR</strong><small>CARREIRA E OFICIALATO</small></div></Link>
      <nav><Link href="/profile">Minha identidade</Link></nav>
    </header>
    <section className="enlistment-hero officer-application-hero">
      <div className="enlistment-hero-copy">
        <div className="enlistment-kicker"><span /><p>PROCESSO INTERNO</p></div>
        <h1>Candidatura ao<br /><strong>Oficialato.</strong></h1>
        <p className="enlistment-lead">Trinta perguntas profissionais avaliam sua forma de liderar, decidir e prestar contas. O relatório automático é apenas consultivo; a decisão final é sempre humana.</p>
        <div className="enlistment-time"><ShieldCheck size={17} /><span><strong>Dados restritos</strong> aos responsáveis por upamento e ao Comando.</span></div>
      </div>
      <aside className="enlistment-brief">
        <span className="enlistment-serial">ELEGIBILIDADE</span>
        <h2>{eligibility.eligible || application ? "Requisitos conferidos" : "Requisitos pendentes"}</h2>
        <ul>
          <li><CheckCircle2 size={15} /> Patente atual: {eligibility.rank_name ?? "não identificada"}</li>
          <li><Clock3 size={15} /> Horas válidas: {duration(eligibility.valid_hours_ms)}</li>
          <li><ShieldCheck size={15} /> Mínimo: {eligibility.minimum_rank_name} + {duration(eligibility.minimum_valid_hours_ms)}</li>
        </ul>
      </aside>
    </section>

    <section className="recruitment-intake">
      {!application && eligibility.eligible ? <div className="candidate-login">
        <ShieldCheck size={28} />
        <div><h2>Você pode iniciar</h2><p>O rascunho fica salvo e pode ser continuado depois.</p></div>
        <form action={startOfficerApplication}><button className="button button-primary" type="submit">Iniciar 30 perguntas <ArrowRight size={16} /></button></form>
      </div> : null}

      {!application && !eligibility.eligible ? <div className="candidate-blocked">
        <strong>A candidatura ainda não pode ser iniciada</strong>
        {eligibility.missing.map((item) => <p key={item}>{missingLabels[item] ?? item}</p>)}
        {eligibility.resubmit_after ? <p>Nova tentativa a partir de {new Date(eligibility.resubmit_after).toLocaleString("pt-BR")}.</p> : null}
      </div> : null}

      {application && !editable ? <div className="candidate-login">
        <CheckCircle2 size={30} />
        <div><h2>{applicationStatus(application.status)}</h2><p>{application.decision_reason ?? "Acompanhe aqui a etapa atual da análise."}</p></div>
        {current?.conditions.map((condition) => <div key={condition.condition_text}><strong>Condição</strong><p>{condition.condition_text}</p></div>)}
      </div> : null}

      {application && editable ? <form action={saveOfficerDraft} className="officer-questionnaire">
        <input type="hidden" name="applicationId" value={application.id} />
        <header><span className="technical-index">QUESTIONÁRIO / V{questionnaire.version_number}</span><h2>{questionnaire.title}</h2><p>Responda com exemplos, critérios e justificativas. Cada resposta aceita de 20 a 4.000 caracteres.</p></header>
        {questionnaire.questions.map((question) => <label className="officer-question" key={question.id}>
          <span>{String(question.question_number).padStart(2, "0")} · {label(question.competency)} · {label(question.question_type)}</span>
          <strong>{question.prompt}</strong>
          <textarea defaultValue={answers.get(question.question_number)} maxLength={4000} minLength={20} name={`answer:${question.id}`} required rows={5} />
        </label>)}
        <div className="enlistment-actions">
          <button className="button button-secondary" type="submit">Salvar rascunho</button>
          <button className="button button-primary" formAction={submitOfficerApplication} type="submit">Salvar e enviar para análise</button>
        </div>
      </form> : null}
    </section>
    <footer className="recruitment-footer"><span>CHOQUE - BGR • OFICIALATO</span><span>Relatório consultivo • decisão final humana</span></footer>
  </main>;
}
