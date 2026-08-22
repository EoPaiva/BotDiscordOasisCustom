import { ArrowLeft, Eye } from "lucide-react";
import Link from "next/link";

import { PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";

type Question = Record<string, unknown>;

export default async function RecruitmentFormPreviewPage() {
  const questions = await commandCenterFetch<Question[]>("/v1/admin/recruitment/questions");
  const enabled = questions.filter((question) => Boolean(question.enabled));
  return <>
    <PageHeader code="REC / PREVIEW" title="Prévia administrativa" description="Simulação visual do banco atual. Esta rota nunca é exposta ao candidato." />
    <div className="recruitment-admin-links"><Link className="button button-secondary" href="/recruitment/form"><ArrowLeft size={14} /> Voltar ao construtor</Link></div>
    <section className="command-section"><SectionHeader index="01" title="Questões elegíveis" meta={`${enabled.length} questões antes do sorteio`} /><div className="recruitment-preview-list">{enabled.map((question) => <article key={String(question.id)}><header><code>{String(question.stable_key)}</code><StatusLabel label={String(question.security_level)} tone={question.security_level === "STRICT" ? "warning" : "success"} /></header><span>{String(question.group_name)}</span><h2>{String(question.title)}</h2>{Boolean(question.description) && <p>{String(question.description)}</p>}<footer><Eye size={13} /> {String(question.question_type)} • {String(question.timer_mode)} • {Boolean(question.allow_back) ? "retorno permitido" : "sem retorno"}</footer></article>)}</div></section>
  </>;
}
