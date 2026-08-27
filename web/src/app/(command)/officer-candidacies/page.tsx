import Link from "next/link";

import { DataTable, EmptyState, MetricStrip, PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

type Application = Record<string, unknown>;

export default async function OfficerCandidaciesPage({ searchParams }: PageProps<"/officer-candidacies">) {
  const query = await searchParams;
  const status = typeof query.status === "string" ? query.status : "";
  const assignedTo = typeof query.assigned_to === "string" ? query.assigned_to : "";
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (/^[1-9]\d*$/.test(assignedTo)) params.set("assigned_to", assignedTo);
  const suffix = params.size ? `?${params.toString()}` : "";
  const applications = await commandCenterFetch<Application[]>(`/v1/officer-applications${suffix}`);
  const waiting = applications.filter((item) => item.status === "SUBMITTED").length;
  const review = applications.filter((item) => ["IN_REVIEW", "INTERVIEW_REQUIRED"].includes(String(item.status))).length;
  const decided = applications.filter((item) => ["APPROVED", "APPROVED_CONDITIONAL", "REJECTED"].includes(String(item.status))).length;
  return <>
    <PageHeader code="CAR / 04" title="Candidaturas ao Oficialato" description="O sistema organiza e resume; a decisão final permanece humana." />
    <MetricStrip items={[
      { label: "NA FILA", value: applications.length },
      { label: "AGUARDANDO", value: waiting, tone: waiting ? "warning" : "success" },
      { label: "EM ANÁLISE", value: review },
      { label: "DECIDIDAS", value: decided, tone: "success" },
    ]} />
    <section className="command-section"><SectionHeader index="01" title="Fila dos responsáveis por upamento" meta="Dados internos e relatório consultivo" />
      <form className="recruitment-filters"><select defaultValue={status} name="status"><option value="">Todos os status</option>{["SUBMITTED", "IN_REVIEW", "INTERVIEW_REQUIRED", "APPROVED_CONDITIONAL", "APPROVED", "REJECTED", "RETURNED"].map((item) => <option key={item}>{item}</option>)}</select><input defaultValue={assignedTo} name="assigned_to" inputMode="numeric" pattern="[0-9]*" placeholder="ID do responsável" /><button className="button button-secondary compact" type="submit">Filtrar</button></form>
      {applications.length ? <DataTable caption="Candidaturas de oficiais" rows={applications} rowKey="id" columns={[
        { key: "id", label: "FICHA", render: (row) => <Link className="member-link" href={`/officer-candidacies/${String(row.id)}`}><strong>OF-{String(row.id).padStart(5, "0")}</strong><code>abrir análise</code></Link> },
        { key: "mta_nick", label: "MILITAR", render: (row) => <strong>{String(row.mta_nick)}</strong> },
        { key: "rank_name", label: "PATENTE" },
        { key: "submitted_at", label: "ENVIO", render: (row) => row.submitted_at ? dateTime(Number(row.submitted_at)) : "—" },
        { key: "assigned_to", label: "RESPONSÁVEL", render: (row) => row.assigned_to ? <code>{String(row.assigned_to)}</code> : "Não atribuído" },
        { key: "status", label: "STATUS", render: (row) => <StatusLabel label={label(String(row.status))} tone={row.status === "REJECTED" ? "danger" : String(row.status).startsWith("APPROVED") ? "success" : "warning"} /> },
      ]} /> : <EmptyState title="Fila sem registros" detail="Nenhuma candidatura corresponde aos filtros atuais." />}
    </section>
  </>;
}
