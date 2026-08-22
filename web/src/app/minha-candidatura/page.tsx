import { ArrowLeft, Clock3, FileCheck2 } from "lucide-react";
import Link from "next/link";

import { loginForRecruitment } from "@/app/login/actions";
import { recruitmentCandidateFetch } from "@/lib/api";
import { getDiscordSessionIdentity } from "@/lib/identity";

import { withdrawRecruitmentApplication } from "../recrutamento/actions";

type ApplicationState = {
  application: Record<string, unknown>;
  progress: { total: number; completed: number };
  history: { event_type: string; public_message: string; created_at: number }[];
};

export default async function MyRecruitmentApplicationPage() {
  const identity = await getDiscordSessionIdentity();
  const data = identity
    ? await recruitmentCandidateFetch<ApplicationState | null>("/v1/me/recruitment/application")
    : null;
  return (
    <main className="recruitment-shell">
      <header className="recruitment-masthead"><Link className="recruitment-brand" href="/recrutamento"><span>CB</span><div><strong>CHOQUE BGR</strong><small>ACOMPANHAMENTO</small></div></Link><nav><Link href="/recrutamento"><ArrowLeft size={14} /> Voltar ao alistamento</Link></nav></header>
      <section className="candidate-status-page">
        <span className="eyebrow">CONSULTA INDIVIDUAL / ACESSO PROTEGIDO</span>
        <h1>Minha candidatura</h1>
        {!identity ? <div className="candidate-login"><h3>Entre com o Discord</h3><p>Use a mesma conta empregada no alistamento.</p><form action={loginForRecruitment}><button className="button button-primary" type="submit">Identificar com Discord</button></form></div> : !data ? <div className="candidate-blocked"><strong>Nenhuma candidatura localizada</strong><p>Quando um processo estiver aberto, inicie pelo portal de alistamento.</p><Link className="text-link" href="/recrutamento">Acessar alistamento</Link></div> : <>
          <div className="candidate-status-strip"><div><span>PROTOCOLO</span><strong>{String(data.application.protocol)}</strong></div><div><span>STATUS</span><strong>{String(data.application.status)}</strong></div><div><span>ETAPA</span><strong>{String(data.application.stage)}</strong></div><div><span>PROGRESSO</span><strong>{data.progress.completed ?? 0} / {data.progress.total ?? 0}</strong></div></div>
          {data.application.status === "DRAFT" && <Link className="button button-primary candidate-continue" href="/recrutamento/avaliacao">Continuar avaliação</Link>}
          {["DRAFT","SUBMITTED","UNDER_REVIEW","INTERVIEW_PENDING","INTERVIEW_SCHEDULED","INTERVIEW_COMPLETED","FINAL_REVIEW"].includes(String(data.application.status)) && <form action={withdrawRecruitmentApplication} className="candidate-withdraw"><input name="applicationId" type="hidden" value={String(data.application.id)} /><input name="expectedVersion" type="hidden" value={String(data.application.version)} /><label>Se não deseja mais participar, digite <strong>RETIRAR</strong> para confirmar.<input autoComplete="off" name="confirmation" required /></label><button className="button button-danger" type="submit">Retirar candidatura</button></form>}
          <section className="candidate-history"><header><FileCheck2 /><div><h2>Linha do tempo</h2><p>Somente comunicações destinadas ao candidato aparecem aqui.</p></div></header>{data.history.length ? data.history.map((event, index) => <article key={`${event.created_at}-${index}`}><Clock3 size={15} /><div><strong>{event.public_message}</strong><time>{new Date(event.created_at).toLocaleString("pt-BR")}</time></div></article>) : <p className="muted">Nenhuma atualização pública registrada.</p>}</section>
        </>}
      </section>
      <footer className="recruitment-footer"><span>CHOQUE BGR • SISTEMA DE GESTÃO</span><span>O conteúdo administrativo permanece restrito ao comando</span></footer>
    </main>
  );
}
