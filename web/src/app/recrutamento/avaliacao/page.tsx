import Link from "next/link";
import { redirect } from "next/navigation";

import { CandidateQuestion, type ReadyQuestion } from "@/components/candidate-question";
import { recruitmentCandidateFetch } from "@/lib/api";
import { getRecruitmentCandidateIdentity } from "@/lib/identity";

type Application = { id: number; protocol: string; status: string };

export default async function RecruitmentAssessmentPage() {
  const identity = await getRecruitmentCandidateIdentity();
  if (!identity) redirect("/recrutamento");
  const current = await recruitmentCandidateFetch<{ application: Application } | null>(
    "/v1/me/recruitment/application",
  );
  if (!current) redirect("/recrutamento");
  if (current.application.status !== "DRAFT") redirect("/minha-candidatura");
  const ready = await recruitmentCandidateFetch<ReadyQuestion>(
    `/v1/recruitment/applications/${current.application.id}/next-question`,
  );
  return (
    <main className="assessment-shell">
      <header className="assessment-header"><Link href="/recrutamento"><span>CB</span><div><strong>AVALIAÇÃO DE ALISTAMENTO</strong><small>CHOQUE BGR • AMBIENTE CONTROLADO</small></div></Link><Link href="/minha-candidatura">Consultar protocolo</Link></header>
      <span aria-hidden="true" className="assessment-watermark">{current.application.protocol} • {identity.discordId.slice(-6)}</span>
      <div className="assessment-stage">
        <CandidateQuestion
          key={ready.complete ? `complete:${ready.application_version ?? "current"}` : `question:${ready.id}:${ready.status}`}
          applicationId={current.application.id}
          protocol={current.application.protocol}
          ready={ready}
        />
      </div>
    </main>
  );
}
