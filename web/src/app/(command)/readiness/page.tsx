import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { duration, label } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function ReadinessPage() {
  const data = await commandCenterFetch<{ summary: { counts: Record<string, number> }; members: Row[] }>("/v1/readiness");
  const counts = data.summary.counts ?? {};
  return <>
    <PageHeader code="OP / 01" title="Prontidão do efetivo" description="Leitura funcional e operacional consolidada em tempo real." />
    <MetricStrip items={Object.entries(counts).map(([key, value]) => ({ label: label(key), value }))} />
    <section className="command-section">
      <SectionHeader index="01" title="Efetivo operacional" meta={`${data.members.length} registros`} />
      <DataTable caption="Efetivo operacional" rows={data.members} columns={[
        { key: "mta_nick", label: "IDENTIFICAÇÃO", render: (row) => <strong>{String(row.mta_nick ?? row.discord_id)}</strong> },
        { key: "rank_name", label: "PATENTE" },
        { key: "status", label: "SITUAÇÃO", render: (row) => <Status value={row.status} /> },
        { key: "activity_status", label: "ATIVIDADE", render: (row) => <Status value={row.activity_status} /> },
        { key: "total_ms", label: "HORAS SEMANA", render: (row) => duration(Number(row.total_ms ?? 0)) },
        { key: "goal_minutes", label: "META", render: (row) => `${row.goal_minutes ?? 0} min` },
      ]} />
    </section>
  </>;
}
