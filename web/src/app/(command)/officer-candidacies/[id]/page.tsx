import Link from "next/link";
import { notFound } from "next/navigation";

import { PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

import {
  claimOfficerApplication,
  decideOfficerApplication,
  recordOfficerInterview,
  scoreOfficerQuestion,
} from "../actions";

type Detail = {
  application: Record<string, unknown>;
  identity_snapshot: Record<string, unknown>;
  career_snapshot: Record<string, unknown>;
  analysis_report: Record<string, unknown>;
  answers: Array<Record<string, unknown>>;
  scores: Array<Record<string, unknown>>;
  interviews: Array<Record<string, unknown>>;
  conditions: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
};

export default async function OfficerCandidacyDetailPage({ params }: PageProps<"/officer-candidacies/[id]">) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const data = await commandCenterFetch<Detail>(`/v1/officer-applications/${id}`);
  const app = data.application;
  const assigned = Boolean(app.assigned_to);
  const open = ["SUBMITTED", "IN_REVIEW", "INTERVIEW_REQUIRED"].includes(String(app.status));
  const ruleScores = new Map(data.scores.filter((item) => item.source === "RULES").map((item) => [Number(item.question_number), Number(item.score)]));
  const humanScores = new Map(data.scores.filter((item) => item.source === "HUMAN").map((item) => [Number(item.question_number), Number(item.score)]));
  return <>
    <PageHeader code={`OF / ${String(id).padStart(5, "0")}`} title={String(data.identity_snapshot.mta_nick ?? "Candidatura ao Oficialato")} description="Relatório consultivo, evidências e decisão humana na mesma trilha auditável." />
    <div className="recruitment-admin-links"><Link className="button button-secondary" href="/officer-candidacies">Voltar para fila</Link><StatusLabel label={label(String(app.status))} tone={app.status === "REJECTED" ? "danger" : String(app.status).startsWith("APPROVED") ? "success" : "warning"} /></div>
    <section className="command-section"><SectionHeader index="01" title="Identidade e carreira" meta={`Enviada em ${app.submitted_at ? dateTime(Number(app.submitted_at)) : "rascunho"}`} /><div className="rank-roster"><div><span>MILITAR</span><strong>{String(data.identity_snapshot.mta_nick)}</strong><p>ID BGR {String(data.identity_snapshot.character_id)}</p></div><div><span>PATENTE</span><strong>{String(data.career_snapshot.rank_name)}</strong><p>{Math.floor(Number(data.career_snapshot.valid_hours_ms ?? 0) / 3_600_000)}h válidas</p></div><div><span>RESPONSÁVEL</span><strong>{app.assigned_to ? String(app.assigned_to) : "Não atribuído"}</strong><p>{String(app.status)}</p></div></div>{app.status === "SUBMITTED" && !assigned ? <form action={claimOfficerApplication} className="section-action"><input type="hidden" name="applicationId" value={id} /><button className="button button-primary" type="submit">Assumir análise</button></form> : null}</section>
    <section className="command-section"><SectionHeader index="02" title="Relatório consultivo local" meta="Nunca decide aprovação ou reprovação" /><div className="identity-access-body"><h2>{label(String(data.analysis_report.profile ?? "SEM PERFIL"))}</h2><strong>{String(data.analysis_report.overall_score ?? "—")} / 10</strong><p>{String(data.analysis_report.recommendation ?? "Relatório ainda não gerado.")}</p></div></section>
    <section className="command-section"><SectionHeader index="03" title="Perguntas, respostas e notas" meta="1 a 10 por questão" /><div className="officer-review-answers">{data.answers.map((answer) => <article key={String(answer.question_number)}><header><span>{String(answer.question_number).padStart(2, "0")} · {label(String(answer.competency))}</span><strong>{String(answer.prompt)}</strong></header><p>{String(answer.answer_text ?? "Sem resposta")}</p><div><small>Regra local: {ruleScores.get(Number(answer.question_number)) ?? "—"}</small><small>Nota humana: {humanScores.get(Number(answer.question_number)) ?? "—"}</small></div>{assigned && open ? <form action={scoreOfficerQuestion}><input type="hidden" name="applicationId" value={id} /><input type="hidden" name="questionId" value={String(answer.question_id ?? "")} /><label>Nota<input defaultValue={humanScores.get(Number(answer.question_number)) ?? ""} min={1} max={10} name="score" required type="number" /></label><label>Justificativa<input name="rationale" required minLength={5} maxLength={2000} /></label><button className="button button-secondary compact" type="submit">Salvar nota humana</button></form> : null}</article>)}</div></section>
    {assigned && open ? <section className="command-section"><SectionHeader index="04" title="Entrevista" meta="Registro humano" /><form action={recordOfficerInterview} className="campaign-form"><input type="hidden" name="applicationId" value={id} /><label>Data e hora<input name="scheduledAt" type="datetime-local" /></label><label>Resultado<select name="result" defaultValue="PENDING"><option>PENDING</option><option>POSITIVE</option><option>NEUTRAL</option><option>NEGATIVE</option></select></label><label>Observações<textarea name="observations" maxLength={4000} /></label><button className="button button-secondary" type="submit">Registrar entrevista</button></form></section> : null}
    {assigned && open ? <section className="command-section"><SectionHeader index="05" title="Decisão final" meta="Exclusivamente humana" /><form action={decideOfficerApplication} className="campaign-form"><input type="hidden" name="applicationId" value={id} /><label>Decisão<select name="decision"><option>APPROVED</option><option>APPROVED_CONDITIONAL</option><option>REJECTED</option><option>RETURNED</option></select></label><label>Justificativa<textarea name="reason" required minLength={10} maxLength={2000} /></label><label>Condição, quando aplicável<textarea name="conditionText" maxLength={2000} /></label><label>Prazo da condição<input name="conditionDueAt" type="datetime-local" /></label><label>Confirmação<input name="confirmation" pattern="CONFIRMAR" placeholder="CONFIRMAR" required /></label><button className="button button-primary" type="submit">Registrar decisão humana</button></form></section> : null}
  </>;
}
