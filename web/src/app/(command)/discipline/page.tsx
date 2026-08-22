import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function DisciplinePage() {
  const data = await commandCenterFetch<{ occurrences: Row[]; measures: Row[] }>("/v1/discipline");
  return <>
    <PageHeader code="ADM / 02" title="Disciplina" description="Ocorrências e medidas funcionais com acesso restrito e trilha imutável." />
    <MetricStrip items={[
      { label: "OCORRÊNCIAS ABERTAS", value: data.occurrences.length, tone: data.occurrences.length ? "warning" : "success" },
      { label: "MEDIDAS ATIVAS", value: data.measures.filter((row) => ["ACTIVE", "SCHEDULED"].includes(String(row.status))).length, tone: "danger" },
      { label: "HISTÓRICO EXIBIDO", value: data.measures.length },
    ]} />
    <div className="dashboard-grid">
      <section className="command-section"><SectionHeader index="01" title="Ocorrências" /><DataTable rows={data.occurrences} columns={[
        { key: "id", label: "REGISTRO", render: (row) => <code>OCR-{String(row.id).padStart(4, "0")}</code> },
        { key: "mta_nick", label: "MEMBRO" },
        { key: "description", label: "DESCRIÇÃO" },
        { key: "status", label: "STATUS", render: (row) => <Status value={row.status} /> },
        { key: "created_at", label: "DATA", render: (row) => dateTime(Number(row.created_at)) },
      ]} /></section>
      <section className="command-section"><SectionHeader index="02" title="Medidas registradas" /><DataTable rows={data.measures} columns={[
        { key: "punishment_type", label: "MEDIDA", render: (row) => label(row.punishment_type) },
        { key: "mta_nick", label: "MEMBRO" },
        { key: "status", label: "STATUS", render: (row) => <Status value={row.status} /> },
        { key: "starts_at", label: "INÍCIO", render: (row) => dateTime(Number(row.starts_at)) },
      ]} /></section>
    </div>
  </>;
}
