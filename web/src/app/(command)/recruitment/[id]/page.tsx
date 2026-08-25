import { Bot, ClipboardSignature, MessageSquareText, RefreshCw, ShieldAlert } from "lucide-react";

import { MetricStrip, PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { label } from "@/lib/format";

import { addRecruitmentAdaptation, addRecruitmentNote, assignRecruitmentApplication, decideRecruitmentApplication, evaluateRecruitmentInterview, reanalyzeRecruitmentApplication, recordRecruitmentAnalysisFeedback, scheduleRecruitmentInterview } from "../actions";

type AnalysisEvidence = { text?: string; description?: string; question?: string; evidenceQuestionIds?: string[]; questionIds?: string[] };
type AnalysisResult = {
  id: number;
  analysis_type: string;
  status: string;
  recommendation: string;
  confidence: string;
  overall_score: number;
  summary: string;
  criteria: { criterion: string; score: number; evidenceQuestionIds: string[]; reason: string }[];
  strengths: AnalysisEvidence[];
  concerns: AnalysisEvidence[];
  contradictions: AnalysisEvidence[];
  interview_questions: AnalysisEvidence[];
  integrity_review_recommended: number;
  provider: string;
  model: string;
  prompt_version: string;
  rubric_version: number;
  context_version: number;
  created_at: number;
};

type Dossier = {
  application: Record<string, unknown>;
  questions: Record<string, unknown>[];
  integrity?: { classification: string; counts: Record<string, number>; events: Record<string, unknown>[] };
  interviews: Record<string, unknown>[];
  evaluations: Record<string, unknown>[];
  notes?: Record<string, unknown>[];
  adaptations?: Record<string, unknown>[];
  history: Record<string, unknown>[];
  automated_analysis?: {
    jobs: Record<string, unknown>[];
    results: AnalysisResult[];
    feedback: Record<string, unknown>[];
    show_score: boolean;
  };
};

const ratings = ["EXCELLENT", "GOOD", "REGULAR", "INSUFFICIENT"];

export default async function RecruitmentDossierPage({ params }: PageProps<"/recruitment/[id]">) {
  const { id } = await params;
  const data = await commandCenterFetch<Dossier>(`/v1/admin/recruitment/applications/${id}`);
  const application = data.application;
  const open = !["APPROVED", "REJECTED", "WITHDRAWN", "EXPIRED"].includes(String(application.status));
  const interview = data.interviews.find((item) => item.status === "SCHEDULED");
  const latestAnalysis = data.automated_analysis?.results[0];
  const latestAnalysisJob = data.automated_analysis?.jobs[0];
  return <>
    <PageHeader code="REC / DOSSIÊ" title={String(application.protocol)} description={`${application.candidate_nick} • ID BGR ${application.bgr_id}`} />
    <MetricStrip items={[
      { label: "STATUS", value: label(String(application.status)) },
      { label: "ETAPA", value: label(String(application.stage)) },
      { label: "QUESTÕES", value: data.questions.length },
      { label: "INTEGRIDADE", value: data.integrity?.classification ?? "RESTRITA", tone: data.integrity?.classification === "NORMAL" ? "success" : "warning" },
      { label: "VERSÃO", value: String(application.version) },
    ]} />
    <div className="recruitment-dossier-grid">
      <div className="recruitment-dossier-main">
        <section className="command-section"><SectionHeader index="01" title="Identificação" meta="Vínculo OAuth conferido no início" /><dl className="decision-fields"><div><dt>Discord</dt><dd><code>{String(application.discord_id)}</code></dd></div><div><dt>Usuário</dt><dd>{String(application.discord_global_name ?? application.discord_username)}</dd></div><div><dt>Nick BGR</dt><dd>{String(application.candidate_nick)}</dd></div><div><dt>ID BGR</dt><dd>{String(application.bgr_id)}</dd></div><div><dt>Idade declarada</dt><dd>{String(application.age)}</dd></div><div><dt>Enviado</dt><dd>{application.submitted_at ? new Date(Number(application.submitted_at)).toLocaleString("pt-BR") : "Ainda em rascunho"}</dd></div></dl></section>
        <section className="command-section"><SectionHeader index="02" title="Respostas" meta="Snapshot imutável da prova" /><div className="recruitment-answers">{data.questions.map((question) => <article key={String(question.id)}><header><code>Q{String(question.ordinal).padStart(2,"0")}</code><StatusLabel label={label(String(question.status))} tone={question.status === "SUBMITTED" ? "success" : "warning"} /></header><h3>{String(question.title)}</h3><p>{question.answer == null ? "Sem resposta final." : Array.isArray(question.answer) ? question.answer.join(", ") : String(question.answer)}</p><footer><span>Segurança {String(question.security_level)}</span><span>{Array.isArray(question.integrity_events) && question.integrity_events.length ? `${question.integrity_events.length} sinal(is) de integridade` : "Sem sinais"}</span><span>{question.duration_ms ? `${Math.round(Number(question.duration_ms) / 1000)}s utilizados` : "Sem duração"}</span></footer></article>)}</div></section>
        {data.automated_analysis && <details className="command-section ai-analysis-disclosure"><summary><span><Bot size={17} /><strong>Análise automatizada</strong><small>Abra somente após revisar as respostas. A recomendação não é uma decisão.</small></span><StatusLabel label={latestAnalysis ? "DISPONÍVEL" : String(latestAnalysisJob?.status ?? "NÃO SOLICITADA")} tone={latestAnalysis ? "success" : "warning"} /></summary><div className="ai-analysis-body">
          {latestAnalysis ? <>
            <div className="ai-analysis-header"><div><span>RECOMENDAÇÃO ASSISTIVA</span><strong>{label(latestAnalysis.recommendation)}</strong><small>Confiança {label(latestAnalysis.confidence)} • decisão automática: nenhuma</small></div><div><span>{data.automated_analysis.show_score ? "ÍNDICE DE APOIO" : "VERSÕES DA ANÁLISE"}</span><strong>{data.automated_analysis.show_score ? `${latestAnalysis.overall_score.toFixed(1)} / 100` : `R${latestAnalysis.rubric_version} / C${latestAnalysis.context_version}`}</strong><small>Rubrica v{latestAnalysis.rubric_version} • contexto v{latestAnalysis.context_version}</small></div></div>
            <div className="ai-analysis-summary"><h3>Visão geral</h3><p>{latestAnalysis.summary}</p>{Boolean(latestAnalysis.integrity_review_recommended) && <p className="candidate-notice"><ShieldAlert size={13} /> Existem sinais que recomendam revisão humana de integridade; eles não são prova de culpa.</p>}</div>
            <div className="ai-criteria-grid">{latestAnalysis.criteria.map((criterion) => <article key={criterion.criterion}><header><strong>{label(criterion.criterion)}</strong><code>{criterion.score.toFixed(1)} / 10</code></header><p>{criterion.reason}</p><footer>Evidências: {criterion.evidenceQuestionIds.join(", ")}</footer></article>)}</div>
            <div className="ai-evidence-columns"><AnalysisList title="Pontos positivos" items={latestAnalysis.strengths} /><AnalysisList title="Pontos de atenção" items={latestAnalysis.concerns} /><AnalysisList title="Inconsistências" items={latestAnalysis.contradictions} /><AnalysisList title="Perguntas sugeridas" items={latestAnalysis.interview_questions} /></div>
            <footer className="ai-analysis-provenance"><span>{latestAnalysis.provider} / {latestAnalysis.model}</span><span>{latestAnalysis.prompt_version}</span><time>{new Date(latestAnalysis.created_at).toLocaleString("pt-BR")}</time></footer>
          </> : <div className="empty-state"><Bot /><div><strong>{latestAnalysisJob ? label(String(latestAnalysisJob.status)) : "Sem análise solicitada"}</strong><p>{latestAnalysisJob?.status === "FAILED" ? "O motor local não concluiu esta análise. A candidatura continua normalmente e o retry é limitado." : "A análise é assíncrona e nunca bloqueia o processo seletivo."}</p></div></div>}
          <div className="ai-analysis-actions"><form action={reanalyzeRecruitmentApplication}><input name="applicationId" type="hidden" value={String(application.id)} /><input name="analysisType" type="hidden" value={["INTERVIEW_COMPLETED","FINAL_REVIEW","APPROVED","REJECTED"].includes(String(application.status)) ? "FINAL_ASSISTED" : "PRE_INTERVIEW"} /><button className="button button-secondary" type="submit"><RefreshCw size={14} /> Reanalisar</button></form>{latestAnalysis && <form action={recordRecruitmentAnalysisFeedback}><input name="applicationId" type="hidden" value={String(application.id)} /><input name="resultId" type="hidden" value={String(latestAnalysis.id)} /><label>A análise foi útil?<select name="usefulness"><option value="YES">Sim</option><option value="PARTIAL">Parcialmente</option><option value="NO">Não</option></select></label><label>Observação opcional<input maxLength={1000} name="note" /></label><button className="button button-secondary" type="submit">Registrar feedback</button></form>}</div>
          {data.automated_analysis.results.length > 1 && <div className="ai-analysis-history"><h3>Histórico preservado</h3>{data.automated_analysis.results.map((result) => <p key={result.id}><code>#{result.id}</code><span>{label(result.analysis_type)} • rubrica v{result.rubric_version}</span><StatusLabel label={result.status} tone={result.status === "COMPLETED" ? "success" : "warning"} /></p>)}</div>}
        </div></details>}
        {data.integrity && <section className="command-section"><SectionHeader index="03" title="Integridade" meta="Evidência não punitiva" /><div className="integrity-summary"><ShieldAlert /><div><strong>{data.integrity.classification}</strong><p>Nenhum sinal abaixo produz reprovação automática.</p></div></div><div className="integrity-counts">{Object.entries(data.integrity.counts).map(([event,count]) => <div key={event}><span>{label(event)}</span><strong>{count}</strong></div>)}</div></section>}
        <section className="command-section"><SectionHeader index="04" title="Histórico" meta="Trilha imutável" /><div className="candidate-history compact">{data.history.map((event,index) => <article key={`${event.id}-${index}`}><ClipboardSignature size={14} /><div><strong>{label(String(event.event_type))}</strong><time>{new Date(Number(event.created_at)).toLocaleString("pt-BR")}</time></div></article>)}</div></section>
      </div>
      <aside className="recruitment-dossier-actions">
        {open && <section className="command-section"><SectionHeader index="A" title="Responsável" meta="Lock otimista" /><form action={assignRecruitmentApplication} className="dossier-form"><input name="applicationId" type="hidden" value={String(application.id)} /><input name="expectedVersion" type="hidden" value={String(application.version)} /><p>{application.assigned_to ? <>Assumida por <code>{String(application.assigned_to)}</code>.</> : "Ainda sem recrutador responsável."}</p><button className="button button-secondary" type="submit">Assumir análise</button></form></section>}
        {open && ["SUBMITTED","UNDER_REVIEW","INTERVIEW_PENDING"].includes(String(application.status)) && <section className="command-section"><SectionHeader index="B" title="Entrevista" meta="Agendamento persistente" /><form action={scheduleRecruitmentInterview} className="dossier-form"><input name="applicationId" type="hidden" value={String(application.id)} /><input name="expectedVersion" type="hidden" value={String(application.version)} /><label>Data e horário<input name="scheduledAt" required type="datetime-local" /></label><label>Entrevistador<input defaultValue={String(application.assigned_to ?? "")} inputMode="numeric" name="interviewerId" required /></label><label>Observação<textarea name="notes" rows={3} /></label><button className="button button-secondary" type="submit">Encaminhar para entrevista</button></form></section>}
        {interview && <section className="command-section"><SectionHeader index="C" title="Avaliação da entrevista" meta="Avaliador identificado" /><form action={evaluateRecruitmentInterview} className="dossier-form"><input name="applicationId" type="hidden" value={String(application.id)} /><input name="expectedVersion" type="hidden" value={String(application.version)} /><input name="interviewId" type="hidden" value={String(interview.id)} />{["communication","posture","knowledge","discipline"].map((field) => <label key={field}>{label(field)}<select name={field} required>{ratings.map((rating) => <option key={rating}>{rating}</option>)}</select></label>)}<label>Resultado<select name="result"><option>FIT</option><option>UNFIT</option><option>REEVALUATE</option></select></label><label>Observação<textarea name="observation" rows={4} /></label><button className="button button-secondary" type="submit">Registrar avaliação</button></form></section>}
        {open && ["UNDER_REVIEW","INTERVIEW_COMPLETED","FINAL_REVIEW"].includes(String(application.status)) && <section className="command-section"><SectionHeader index="D" title="Decisão final" meta="Somente comando" /><form action={decideRecruitmentApplication} className="dossier-form decision-form"><input name="applicationId" type="hidden" value={String(application.id)} /><input name="expectedVersion" type="hidden" value={String(application.version)} /><label>Motivo interno<textarea name="internalReason" required rows={3} /></label><label>Mensagem ao candidato<textarea name="candidateMessage" required rows={3} /></label><label>Confirmação<input name="confirmation" placeholder="Digite CONFIRMAR" required /></label><div><button className="button button-primary" name="decision" type="submit" value="approve">Aprovar</button><button className="button button-danger" name="decision" type="submit" value="reject">Reprovar</button></div></form></section>}
        {open && <section className="command-section"><SectionHeader index="E" title="Adaptação de avaliação" meta="Acessibilidade auditada" />{Boolean(data.adaptations?.length) && <div className="internal-notes">{data.adaptations?.map((item) => <article key={String(item.id)}><ShieldAlert size={13} /><div><p>Tempo +{String(item.extra_time_percent)}% • clipboard {item.clipboard_adapted ? "adaptado" : "padrão"}{item.alternative_format ? ` • ${String(item.alternative_format)}` : ""}</p><small>{String(item.approved_by)} • {new Date(Number(item.created_at)).toLocaleString("pt-BR")}</small></div></article>)}</div>}<form action={addRecruitmentAdaptation} className="dossier-form"><input name="applicationId" type="hidden" value={String(application.id)} /><label>Tempo adicional (%)<input defaultValue="0" max={200} min={0} name="extraTimePercent" type="number" /></label><label className="checkbox-row"><input name="clipboardAdapted" type="checkbox" /> Permitir tecnologia assistiva/clipboard</label><label>Formato alternativo<input name="alternativeFormat" placeholder="Ex.: resposta por leitor de tela" /></label><label>Motivo<textarea name="reason" required rows={3} /></label><button className="button button-secondary" type="submit">Registrar adaptação</button></form></section>}
        {data.notes && <section className="command-section"><SectionHeader index="F" title="Notas internas" meta="Nunca exibidas ao candidato" /><div className="internal-notes">{data.notes.map((note) => <article key={String(note.id)}><MessageSquareText size={13} /><div><p>{String(note.note)}</p><small>{String(note.author_id)} • {new Date(Number(note.created_at)).toLocaleString("pt-BR")}</small></div></article>)}</div><form action={addRecruitmentNote} className="dossier-form"><input name="applicationId" type="hidden" value={String(application.id)} /><label>Nova observação<textarea name="note" required rows={3} /></label><button className="button button-secondary" type="submit">Registrar nota</button></form></section>}
      </aside>
    </div>
  </>;
}

function AnalysisList({ title, items }: { title: string; items: AnalysisEvidence[] }) {
  return <section><h3>{title}</h3>{items.length ? <ul>{items.map((item, index) => <li key={`${title}-${index}`}><span>{item.text ?? item.description ?? item.question}</span><small>{(item.evidenceQuestionIds ?? item.questionIds ?? []).join(", ")}</small></li>)}</ul> : <p>Sem registros.</p>}</section>;
}
