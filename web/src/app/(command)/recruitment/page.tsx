import { Ban, Bot, FileCog, Flag } from "lucide-react";
import Link from "next/link";

import { DataTable, MetricStrip, PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { recruitmentAdminFetch } from "@/lib/api";
import { label } from "@/lib/format";

type Application = Record<string, unknown>;
type Statistics = { by_status: Record<string, number>; stale: number; stale_hours: number };

export default async function RecruitmentAdminPage({ searchParams }: PageProps<"/recruitment">) {
  const query = await searchParams;
  const status = typeof query.status === "string" ? query.status : "";
  const search = typeof query.search === "string" ? query.search : "";
  const assignedTo = typeof query.assigned_to === "string" ? query.assigned_to : "";
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (search) params.set("search", search);
  if (/^[1-9]\d*$/.test(assignedTo)) params.set("assigned_to", assignedTo);
  const queryString = params.toString();
  const data = await recruitmentAdminFetch<{ applications: Application[]; statistics: Statistics }>(
    `/v1/admin/recruitment/applications${queryString ? `?${queryString}` : ""}`,
  );
  const counts = data.statistics.by_status;
  return <>
    <PageHeader code="REC / 01" title="Recrutamento" description="Fila humana de análise, integridade, entrevista e ingresso." />
    <MetricStrip items={[
      { label: "RECEBIDAS", value: Object.values(counts).reduce((total, value) => total + value, 0) },
      { label: "AGUARDANDO", value: counts.SUBMITTED ?? 0, tone: "warning" },
      { label: "EM ANÁLISE", value: counts.UNDER_REVIEW ?? 0 },
      { label: "ENTREVISTAS", value: (counts.INTERVIEW_SCHEDULED ?? 0) + (counts.FINAL_REVIEW ?? 0) },
      { label: "APROVADAS", value: counts.APPROVED ?? 0, tone: "success" },
      { label: `ATRASADAS ${data.statistics.stale_hours}H`, value: data.statistics.stale, tone: data.statistics.stale ? "danger" : "success" },
    ]} />
    <div className="recruitment-admin-links"><Link className="button button-secondary" href="/recruitment/campaign"><Flag size={15} /> Processo seletivo</Link><Link className="button button-secondary" href="/recruitment/form"><FileCog size={15} /> Formulário e questões</Link><Link className="button button-secondary" href="/recruitment/ai"><Bot size={15} /> Analista IA</Link><Link className="button button-secondary" href="/recruitment/blocks"><Ban size={15} /> Bloqueios</Link></div>
    <section className="command-section"><SectionHeader index="01" title="Fila de candidaturas" meta="Decisão final sempre humana" />
      <form className="recruitment-filters"><input aria-label="Pesquisar por nick, Discord, ID BGR ou protocolo" defaultValue={search} name="search" placeholder="Nick, Discord, ID BGR ou protocolo" /><select aria-label="Filtrar por status" defaultValue={status} name="status"><option value="">Todos os status</option>{["DRAFT","SUBMITTED","UNDER_REVIEW","INTERVIEW_SCHEDULED","FINAL_REVIEW","APPROVED","REJECTED"].map((item) => <option key={item}>{item}</option>)}</select><input defaultValue={assignedTo} name="assigned_to" inputMode="numeric" pattern="[0-9]*" placeholder="ID do responsável" aria-label="Filtrar por ID do responsável" /><button className="button button-secondary compact" type="submit">Filtrar</button></form>
      <DataTable caption="Fila de candidaturas" emptyTitle="Fila sem registros" emptyDetail="Nenhuma candidatura corresponde aos filtros atuais." rows={data.applications} columns={[
        { key: "protocol", label: "PROTOCOLO", render: (application) => <Link className="member-link" href={`/recruitment/${application.id}`}><strong>{String(application.protocol)}</strong><code>abrir dossiê</code></Link> },
        { key: "candidate_nick", label: "CANDIDATO", render: (application) => <><strong>{String(application.candidate_nick)}</strong><br /><code>{String(application.discord_id)}</code></> },
        { key: "bgr_id", label: "ID BGR", render: (application) => <code>{String(application.bgr_id)}</code> },
        { key: "submitted_at", label: "ENVIO", render: (application) => application.submitted_at ? new Date(Number(application.submitted_at)).toLocaleString("pt-BR") : "Rascunho" },
        { key: "stage", label: "ETAPA", render: (application) => label(String(application.stage)) },
        { key: "integrity_signals", label: "INTEGRIDADE", render: (application) => <StatusLabel label={Number(application.integrity_signals) ? `${application.integrity_signals} sinais` : "Normal"} tone={Number(application.integrity_signals) ? "warning" : "success"} /> },
        { key: "assigned_to", label: "RESPONSÁVEL", render: (application) => application.assigned_to ? <code>{String(application.assigned_to)}</code> : "Não atribuído" },
        { key: "status", label: "STATUS", render: (application) => <StatusLabel label={label(String(application.status))} tone={application.status === "APPROVED" ? "success" : application.status === "REJECTED" ? "danger" : "warning"} /> },
      ]} />
    </section>
  </>;
}
