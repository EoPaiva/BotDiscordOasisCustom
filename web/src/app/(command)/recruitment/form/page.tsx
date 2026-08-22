import { Eye, FilePlus2, Layers3, Plus } from "lucide-react";
import Link from "next/link";

import { MetricStrip, PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";

import {
  createRecruitmentQuestion,
  publishRecruitmentForm,
  updateRecruitmentQuestion,
  updateRecruitmentQuestionGroup,
} from "../actions";

type Question = Record<string, unknown>;
type Group = Record<string, unknown>;

const questionTypes = [
  "SHORT_TEXT",
  "LONG_TEXT",
  "NUMBER",
  "DATE",
  "BOOLEAN",
  "SINGLE_SELECT",
  "MULTI_SELECT",
];

function condition(question: Question) {
  if (!question.condition_json) return { question: "", value: "" };
  try {
    const parsed = JSON.parse(String(question.condition_json));
    return { question: String(parsed.question ?? ""), value: JSON.stringify(parsed.equals) };
  } catch {
    return { question: "", value: "" };
  }
}

function QuestionFields({ question, groups }: { question?: Question; groups: Group[] }) {
  const dependency = question ? condition(question) : { question: "", value: "" };
  return <>
    {question && <input name="questionId" type="hidden" value={String(question.id)} />}
    {!question && <label>Identificador<input name="stableKey" pattern="[A-Za-z0-9_]+" placeholder="Q46" required /></label>}
    <label>Grupo<select defaultValue={String(question?.group_id ?? groups[0]?.id ?? "")} name="groupId" required>{groups.map((group) => <option key={String(group.id)} value={String(group.id)}>{String(group.name)}</option>)}</select></label>
    <label>Tipo<select defaultValue={String(question?.question_type ?? "LONG_TEXT")} name="questionType">{questionTypes.map((type) => <option key={type}>{type}</option>)}</select></label>
    <label>Posição<input defaultValue={String(question?.position ?? 100)} min={1} name="position" required type="number" /></label>
    <label className="wide">Enunciado<textarea defaultValue={String(question?.title ?? "")} name="title" required rows={3} /></label>
    <label className="wide">Descrição<textarea defaultValue={String(question?.description ?? "")} name="description" rows={2} /></label>
    <label>Ativa<select defaultValue={String(question ? Boolean(question.enabled) : true)} name="enabled"><option value="true">Sim</option><option value="false">Não</option></select></label>
    <label>Obrigatória<select defaultValue={String(question ? Boolean(question.required) : true)} name="required"><option value="true">Sim</option><option value="false">Não</option></select></label>
    <label>Segurança<select defaultValue={String(question?.security_level ?? "CONTROLLED")} name="securityLevel"><option>NORMAL</option><option>CONTROLLED</option><option>STRICT</option></select></label>
    <label>Dificuldade<select defaultValue={String(question?.difficulty ?? "MEDIUM")} name="difficulty"><option>EASY</option><option>MEDIUM</option><option>HARD</option></select></label>
    <label>Mínimo<input defaultValue={String(question?.min_length ?? "")} min={0} name="minLength" type="number" /></label>
    <label>Máximo<input defaultValue={String(question?.max_length ?? "")} min={1} name="maxLength" type="number" /></label>
    <label>Esperado mínimo<input defaultValue={String(question?.expected_min_length ?? "")} min={0} name="expectedMinLength" type="number" /></label>
    <label>Esperado máximo<input defaultValue={String(question?.expected_max_length ?? "")} min={1} name="expectedMaxLength" type="number" /></label>
    <label>Temporizador<select defaultValue={String(question ? Boolean(question.timer_enabled) : true)} name="timerEnabled"><option value="true">Sim</option><option value="false">Não</option></select></label>
    <label>Modo<select defaultValue={String(question?.timer_mode ?? "AUTO")} name="timerMode"><option>AUTO</option><option>FIXED</option><option>NONE</option></select></label>
    <label>Segundos fixos<input defaultValue={String(question?.fixed_time_seconds ?? "")} min={30} name="fixedTimeSeconds" type="number" /></label>
    <label>Permite voltar<select defaultValue={String(question ? Boolean(question.allow_back) : true)} name="allowBack"><option value="true">Sim</option><option value="false">Não</option></select></label>
    <label>Embaralhar<select defaultValue={String(question ? Boolean(question.shuffle_position) : true)} name="shufflePosition"><option value="true">Sim</option><option value="false">Não</option></select></label>
    <label className="wide">Opções separadas por |<input defaultValue={question ? JSON.parse(String(question.options_json)).join(" | ") : ""} name="options" /></label>
    <label>Depende da questão<input defaultValue={dependency.question} name="conditionQuestion" placeholder="Q08" /></label>
    <label>Valor esperado<input defaultValue={dependency.value} name="conditionValue" placeholder="true ou texto" /></label>
  </>;
}

export default async function RecruitmentFormPage() {
  const [questions, groups] = await Promise.all([
    commandCenterFetch<Question[]>("/v1/admin/recruitment/questions"),
    commandCenterFetch<Group[]>("/v1/admin/recruitment/question-groups"),
  ]);
  return <>
    <PageHeader code="REC / 03" title="Formulário de alistamento" description="Banco versionado; alterações só alcançam novas candidaturas após publicação." />
    <MetricStrip items={[{ label: "QUESTÕES", value: questions.length }, { label: "ATIVAS", value: questions.filter((item) => item.enabled).length, tone: "success" }, { label: "RIGOROSAS", value: questions.filter((item) => item.security_level === "STRICT").length }, { label: "GRUPOS", value: groups.length }]} />
    <section className="command-section"><SectionHeader index="01" title="Publicação" meta="Cria snapshot imutável" /><form action={publishRecruitmentForm} className="form-publish-bar"><div><FilePlus2 /><span><strong>Publicar nova versão</strong><small>Candidaturas existentes permanecem exatamente como foram sorteadas.</small></span></div><div className="form-publish-actions"><Link className="button button-secondary" href="/recruitment/form/preview"><Eye size={14} /> Pré-visualizar</Link><button className="button button-primary" type="submit">Publicar formulário</button></div></form></section>
    <section className="command-section"><SectionHeader index="02" title="Distribuição por grupos" meta="Quantidade sorteada por candidatura" /><div className="recruitment-group-grid">{groups.map((group) => <form action={updateRecruitmentQuestionGroup} className="question-group-card" key={String(group.id)}><input name="groupId" type="hidden" value={String(group.id)} /><header><Layers3 size={15} /><code>{String(group.code)}</code></header><label>Nome<input defaultValue={String(group.name)} name="name" required /></label><label>Posição<input defaultValue={String(group.position)} min={1} name="position" type="number" /></label><label>Selecionadas por prova<input defaultValue={String(group.questions_per_application)} min={0} name="questionsPerApplication" type="number" /></label><label>Grupo ativo<select defaultValue={String(Boolean(group.active))} name="active"><option value="true">Sim</option><option value="false">Não</option></select></label><small>{String(group.enabled_question_count ?? 0)} ativas de {String(group.question_count ?? 0)}</small><button className="button button-secondary compact" type="submit">Salvar grupo</button></form>)}</div></section>
    <section className="command-section"><SectionHeader index="03" title="Nova questão" meta="Entra no rascunho atual" /><details className="question-create"><summary><Plus size={15} /> Adicionar questão ao banco</summary><form action={createRecruitmentQuestion} className="question-admin-form"><QuestionFields groups={groups} /><button className="button button-primary" type="submit">Criar questão</button></form></details></section>
    <section className="command-section recruitment-question-bank"><SectionHeader index="04" title="Banco de questões" meta={`${questions.length} questões configuradas`} />{questions.map((question) => <details key={String(question.id)}><summary><code>{String(question.stable_key)}</code><div><strong>{String(question.title)}</strong><span>{String(question.group_name)} • {String(question.question_type)} • posição {String(question.position)}</span></div><StatusLabel label={String(question.security_level)} tone={question.security_level === "STRICT" ? "warning" : "success"} /></summary><form action={updateRecruitmentQuestion} className="question-admin-form"><QuestionFields groups={groups} question={question} /><button className="button button-secondary" type="submit">Salvar questão no rascunho</button></form></details>)}</section>
  </>;
}
