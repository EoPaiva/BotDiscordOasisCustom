import { BarChart3, Bot, FileCheck2, FlaskConical, ShieldCheck } from "lucide-react";

import { MetricStrip, PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";

import {
  createRecruitmentAiRubricDraft,
  createRecruitmentAiContextDraft,
  previewRecruitmentAiRubric,
  publishRecruitmentAiContext,
  publishRecruitmentAiRubric,
  updateRecruitmentAiContext,
  updateRecruitmentAiConfiguration,
  updateRecruitmentAiRubric,
} from "../actions";

type Configuration = {
  enabled: boolean;
  auto_analyze: boolean;
  analyze_integrity: boolean;
  generate_interview_questions: boolean;
  generate_summary: boolean;
  final_assisted_after_interview: boolean;
  discord_notice: boolean;
  show_score: boolean;
  provider: string;
  model: string;
  provider_ready: boolean;
  prompt_version: string;
};

type Criterion = {
  id: number;
  code: string;
  label: string;
  description: string;
  weight: number;
};

type Rubric = {
  selected: { id: number; name: string; status: string; version_number: number; settings: { review_min: number; recommended_min: number; show_score: boolean } };
  criteria: Criterion[];
  weight_total: number;
  versions: { id: number; name: string; status: string; version_number: number }[];
};

type EvaluationContext = {
  selected: { id: number; name: string; status: string; version_number: number; content: { principles: string[]; prohibitions: string[] } };
  versions: { id: number; name: string; status: string; version_number: number }[];
};

type Quality = {
  recommendations: Record<string, number>;
  human_decisions: Record<string, number>;
  divergences: number;
  feedback: Record<string, number>;
  notice: string;
};

export default async function RecruitmentAiPage() {
  const [config, rubric, evaluationContext, quality] = await Promise.all([
    commandCenterFetch<Configuration>("/v1/admin/recruitment/ai/config"),
    commandCenterFetch<Rubric>("/v1/admin/recruitment/ai/rubric"),
    commandCenterFetch<EvaluationContext>("/v1/admin/recruitment/ai/context"),
    commandCenterFetch<Quality>("/v1/admin/recruitment/ai/quality"),
  ]);
  const draft = rubric.selected.status === "DRAFT";
  const contextDraft = evaluationContext.selected.status === "DRAFT";
  return <>
    <PageHeader code="REC / IA" title="Analista de candidaturas" description="Assistência por rubrica e evidências. A decisão final continua exclusivamente humana." />
    <MetricStrip items={[
      { label: "ROBÔ ANALISTA", value: config.enabled ? "ATIVO" : "INATIVO", tone: config.enabled ? "success" : "warning" },
      { label: "MOTOR", value: config.provider_ready ? config.provider : "NÃO CONFIGURADO", tone: config.provider_ready ? "success" : "warning" },
      { label: "RUBRICA", value: `V${rubric.selected.version_number}` },
      { label: "PESOS", value: `${rubric.weight_total}%`, tone: rubric.weight_total === 100 ? "success" : "danger" },
      { label: "DIVERGÊNCIAS", value: quality.divergences, tone: quality.divergences ? "warning" : "success" },
    ]} />
    <div className="ai-governance-notice"><ShieldCheck /><div><strong>Analista, nunca juiz</strong><p>Sem tools, sem acesso administrativo, sem atributos protegidos, sem ranking e sem aprovação automática.</p></div></div>
    <div className="dashboard-grid">
      <section className="command-section"><SectionHeader index="01" title="Configuração operacional" meta={`${config.provider} / ${config.model}`} />
        <form action={updateRecruitmentAiConfiguration} className="ai-config-form">
          {[
            ["enabled", "Robô analista ativo", config.enabled],
            ["autoAnalyze", "Analisar automaticamente após envio", config.auto_analyze],
            ["analyzeIntegrity", "Incluir sinais de integridade como evidência", config.analyze_integrity],
            ["generateInterviewQuestions", "Gerar perguntas sugeridas para entrevista", config.generate_interview_questions],
            ["generateSummary", "Gerar resumo factual", config.generate_summary],
            ["finalAssistedAfterInterview", "Gerar análise final assistida após entrevista", config.final_assisted_after_interview],
            ["discordNotice", "Notificar no Discord quando a análise estiver disponível", config.discord_notice],
            ["showScore", "Mostrar índice numérico de apoio", config.show_score],
          ].map(([name, text, checked]) => <label className="ai-toggle" key={String(name)}><input defaultChecked={Boolean(checked)} disabled={name === "enabled" && !config.provider_ready} name={String(name)} type="checkbox" /><span>{String(text)}</span></label>)}
          {!config.provider_ready && <p className="candidate-notice">O motor de análise está indisponível; o recrutamento continua funcionando normalmente.</p>}
          <button className="button button-primary" type="submit">Salvar configuração</button>
        </form>
      </section>
      <section className="command-section"><SectionHeader index="02" title="Qualidade e divergências" meta="Não mede desempenho do recrutador" />
        <div className="ai-quality-grid"><div><BarChart3 /><span>IA recomendou</span><strong>{quality.recommendations.RECOMMENDED ?? 0}</strong></div><div><FileCheck2 /><span>Humanos aprovaram</span><strong>{quality.human_decisions.APPROVED ?? 0}</strong></div><div><Bot /><span>Feedback útil</span><strong>{quality.feedback.YES ?? 0}</strong></div></div>
        <p className="ai-quality-notice">{quality.notice}</p>
      </section>
    </div>
    <section className="command-section"><SectionHeader index="03" title="Rubrica versionada" meta={`${rubric.selected.name} • ${rubric.selected.status}`} />
      <div className="form-publish-bar"><div><FileCheck2 /><span><strong>Versão {rubric.selected.version_number}</strong><small>Análises antigas nunca são sobrescritas.</small></span></div><div className="form-publish-actions">{!draft && <form action={createRecruitmentAiRubricDraft}><button className="button button-secondary" type="submit">Criar nova versão</button></form>}<form action={previewRecruitmentAiRubric}><button className="button button-secondary" disabled={!config.provider_ready} type="submit"><FlaskConical size={14} /> Preview sintético</button></form>{draft && <form action={publishRecruitmentAiRubric}><input name="rubricId" type="hidden" value={rubric.selected.id} /><button className="button button-primary" disabled={rubric.weight_total !== 100} type="submit">Publicar rubrica</button></form>}</div></div>
      <form action={updateRecruitmentAiRubric} className="ai-rubric-editor"><input name="rubricId" type="hidden" value={rubric.selected.id} />{rubric.criteria.map((criterion, index) => <article key={criterion.id}><header><code>{String(index + 1).padStart(2,"0")}</code><StatusLabel label={`${criterion.weight}%`} tone="success" /></header><label>Código<input defaultValue={criterion.code} disabled={!draft} name="code" required /></label><label>Critério<input defaultValue={criterion.label} disabled={!draft} name="criterionLabel" required /></label><label className="wide">Descrição<textarea defaultValue={criterion.description} disabled={!draft} name="description" required rows={3} /></label><label>Peso (%)<input defaultValue={criterion.weight} disabled={!draft} max={100} min={1} name="weight" required type="number" /></label></article>)}{draft && <footer className="ai-rubric-thresholds"><label>Revisão a partir de<input defaultValue={rubric.selected.settings.review_min} max={99} min={0} name="reviewMin" type="number" /></label><label>Recomendado a partir de<input defaultValue={rubric.selected.settings.recommended_min} max={100} min={1} name="recommendedMin" type="number" /></label><label className="checkbox-row"><input defaultChecked={rubric.selected.settings.show_score} name="rubricShowScore" type="checkbox" /> Score habilitado nesta versão</label><span>Total configurado: <strong>{rubric.weight_total}%</strong></span><button className="button button-secondary" type="submit">Salvar rascunho</button></footer>}</form>
    </section>
    <section className="command-section ai-context-editor"><SectionHeader index="04" title="Contexto institucional versionado" meta={`${evaluationContext.selected.name} • ${evaluationContext.selected.status}`} /><div className="form-publish-bar"><div><ShieldCheck /><span><strong>Regras oficiais de avaliação</strong><small>Somente o contexto autorizado é processado pelo motor local.</small></span></div><div className="form-publish-actions">{!contextDraft && <form action={createRecruitmentAiContextDraft}><button className="button button-secondary" type="submit">Criar nova versão</button></form>}{contextDraft && <form action={publishRecruitmentAiContext}><input name="contextId" type="hidden" value={evaluationContext.selected.id} /><button className="button button-primary" type="submit">Publicar contexto</button></form>}</div></div><form action={updateRecruitmentAiContext}><input name="contextId" type="hidden" value={evaluationContext.selected.id} /><label>Princípios — um por linha<textarea defaultValue={evaluationContext.selected.content.principles.join("\n")} disabled={!contextDraft} name="principles" rows={8} /></label><label>Proibições — uma por linha<textarea defaultValue={evaluationContext.selected.content.prohibitions.join("\n")} disabled={!contextDraft} name="prohibitions" rows={8} /></label>{contextDraft && <button className="button button-secondary" type="submit">Salvar contexto</button>}</form></section>
    <section className="command-section ai-version-history"><SectionHeader index="05" title="Histórico de versões" meta="Sem alterações retroativas" /><div>{rubric.versions.map((version) => <p key={`r-${version.id}`}><code>R{version.version_number}</code><strong>{version.name}</strong><StatusLabel label={version.status} tone={version.status === "PUBLISHED" ? "success" : "warning"} /></p>)}{evaluationContext.versions.map((version) => <p key={`c-${version.id}`}><code>C{version.version_number}</code><strong>{version.name}</strong><StatusLabel label={version.status} tone={version.status === "PUBLISHED" ? "success" : "warning"} /></p>)}</div></section>
  </>;
}
