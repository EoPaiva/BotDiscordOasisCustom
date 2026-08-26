import { ArrowLeft, Check, Clock3, FileCheck2 } from "lucide-react";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { recruitmentCandidateFetch } from "@/lib/api";
import { getRecruitmentCandidateIdentity } from "@/lib/identity";

import { withdrawRecruitmentApplication } from "../recrutamento/actions";

export const metadata: Metadata = {
  title: "Minha candidatura",
  robots: { index: false, follow: false },
};

type ApplicationState = {
  application: Record<string, unknown>;
  progress: { total: number; completed: number };
  history: { event_type: string; public_message: string; created_at: number }[];
};

const publicStatusLabels: Record<string, string> = {
  DRAFT: "Preenchimento",
  SUBMITTED: "Candidatura recebida",
  UNDER_REVIEW: "Em análise",
  INTERVIEW_PENDING: "Entrevista pendente",
  INTERVIEW_SCHEDULED: "Entrevista agendada",
  INTERVIEW_COMPLETED: "Entrevista concluída",
  FINAL_REVIEW: "Análise final",
  APPROVED: "Aprovada",
  REJECTED: "Não aprovada",
  WITHDRAWN: "Retirada pelo candidato",
  CANCELLED: "Encerrada",
};

const applicationJourney = ["Identificação", "Avaliação", "Análise", "Resultado"];

function journeyIndex(status: string): number {
  if (status === "DRAFT") return 1;
  if (["SUBMITTED", "UNDER_REVIEW", "INTERVIEW_PENDING", "INTERVIEW_SCHEDULED", "INTERVIEW_COMPLETED", "FINAL_REVIEW"].includes(status)) return 2;
  if (["APPROVED", "REJECTED", "WITHDRAWN", "CANCELLED"].includes(status)) return 3;
  return 0;
}

export default async function MyRecruitmentApplicationPage() {
  const identity = await getRecruitmentCandidateIdentity();
  const data = identity
    ? await recruitmentCandidateFetch<ApplicationState | null>("/v1/me/recruitment/application")
    : null;
  const status = data ? String(data.application.status) : "";
  const activeJourneyIndex = journeyIndex(status);
  return (
    <main className="recruitment-shell recruitment-redesign">
      <header className="recruitment-masthead"><Link className="recruitment-brand" href="/recrutamento"><span className="recruitment-brand-mark"><Image alt="" aria-hidden="true" height={38} src="/choque-emblem.png" width={38} /></span><div><strong>CHOQUE BGR</strong><small>ACOMPANHAMENTO</small></div></Link><nav><Link href="/recrutamento"><ArrowLeft size={14} /> Voltar ao alistamento</Link></nav></header>
      <section className="candidate-status-page">
        <span className="eyebrow">CONSULTA INDIVIDUAL / ACESSO PROTEGIDO</span>
        <h1>Minha candidatura</h1>
        {!identity ? <div className="candidate-login"><h3>Identificação necessária</h3><p>Inicie pelo portal de alistamento para criar seu acesso protegido.</p><Link className="button button-primary" href="/recrutamento">Iniciar identificação</Link></div> : !data ? <div className="candidate-blocked"><strong>Nenhuma candidatura localizada</strong><p>Quando um processo estiver aberto, inicie pelo portal de alistamento.</p><Link className="text-link" href="/recrutamento">Acessar alistamento</Link></div> : <>
          <div className="candidate-status-strip"><div><span>PROTOCOLO</span><strong>{String(data.application.protocol)}</strong></div><div><span>STATUS</span><strong>{publicStatusLabels[status] ?? status}</strong></div><div><span>ETAPA</span><strong>{String(data.application.stage)}</strong></div><div><span>PROGRESSO</span><strong>{data.progress.completed ?? 0} / {data.progress.total ?? 0}</strong></div></div>
          <ol className="candidate-stage-flow" aria-label="Etapas da candidatura">
            {applicationJourney.map((stage, index) => (
              <li className={index < activeJourneyIndex ? "complete" : index === activeJourneyIndex ? "current" : "pending"} key={stage}>
                <span>{index < activeJourneyIndex ? <Check aria-hidden="true" size={14} /> : index + 1}</span>
                <strong>{stage}</strong>
                {index === activeJourneyIndex && <small>Etapa atual</small>}
              </li>
            ))}
          </ol>
          {data.application.status === "DRAFT" && <Link className="button button-primary candidate-continue" href="/recrutamento/avaliacao">Continuar avaliação</Link>}
          {["DRAFT","SUBMITTED","UNDER_REVIEW","INTERVIEW_PENDING","INTERVIEW_SCHEDULED","INTERVIEW_COMPLETED","FINAL_REVIEW"].includes(String(data.application.status)) && <form action={withdrawRecruitmentApplication} className="candidate-withdraw"><input name="applicationId" type="hidden" value={String(data.application.id)} /><input name="expectedVersion" type="hidden" value={String(data.application.version)} /><label>Se não deseja mais participar, digite <strong>RETIRAR</strong> para confirmar.<input autoComplete="off" name="confirmation" required /></label><button className="button button-danger" type="submit">Retirar candidatura</button></form>}
          <section className="candidate-history"><header><FileCheck2 /><div><h2>Linha do tempo</h2><p>Somente comunicações destinadas ao candidato aparecem aqui.</p></div></header>{data.history.length ? data.history.map((event, index) => <article key={`${event.created_at}-${index}`}><Clock3 size={15} /><div><strong>{event.public_message}</strong><time>{new Date(event.created_at).toLocaleString("pt-BR")}</time></div></article>) : <p className="muted">Nenhuma atualização pública registrada.</p>}</section>
        </>}
      </section>
      <footer className="recruitment-footer"><span>CHOQUE BGR • SISTEMA DE GESTÃO</span><span>O conteúdo administrativo permanece restrito ao comando</span></footer>
    </main>
  );
}
