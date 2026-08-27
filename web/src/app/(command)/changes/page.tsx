import { DataTable, MetricStrip, PageHeader, SectionHeader } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, isoDateTime, label } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function ChangesPage() {
  const data = await commandCenterFetch<{ period_days: number; since: number; counts: Record<string, number>; events: Row[] }>("/v1/changes?days=7");
  return <>
    <PageHeader code="INT / 01" title="O que mudou?" description={<>Briefing operacional desde <time dateTime={isoDateTime(data.since)}>{dateTime(data.since)}</time>.</>} />
    <MetricStrip items={Object.entries(data.counts).slice(0, 7).map(([key, value]) => ({ label: label(key), value }))} />
    <section className="command-section"><SectionHeader index="01" title="Linha de mudanças" meta={`${data.events.length} eventos`} />
      <DataTable caption="Linha de mudanças" rows={data.events} columns={[
        { key: "created_at", label: "DATA", render: (row) => dateTime(Number(row.created_at)) },
        { key: "event_type", label: "EVENTO", render: (row) => <strong>{label(row.event_type)}</strong> },
        { key: "aggregate_type", label: "DOMÍNIO", render: (row) => label(row.aggregate_type) },
        { key: "aggregate_id", label: "REFERÊNCIA", render: (row) => <code>{String(row.aggregate_id ?? "—")}</code> },
      ]} />
    </section>
  </>;
}
