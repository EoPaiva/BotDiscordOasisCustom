import Link from "next/link";

import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, duration } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function MembersPage() {
  const rows = await commandCenterFetch<Row[]>("/v1/members");
  return <>
    <PageHeader code="EF / 01" title="Efetivo" description="Quadro funcional, identidade, atividade e vínculo de patente." />
    <MetricStrip items={[
      { label: "EFETIVO LISTADO", value: rows.length },
      { label: "ATIVOS", value: rows.filter((row) => row.status === "ACTIVE").length, tone: "success" },
      { label: "AUSENTES", value: rows.filter((row) => row.status === "AWAY").length },
      { label: "DIVERGÊNCIAS", value: rows.filter((row) => row.rank_sync_status !== "SYNCED").length, tone: "warning" },
    ]} />
    <section className="command-section">
      <SectionHeader index="01" title="Relação do efetivo" meta="Selecione um membro para abrir o dossiê" />
      <DataTable caption="Relação do efetivo" rows={rows} columns={[
        { key: "discord_id", label: "IDENTIFICAÇÃO", render: (row) => <Link className="member-link" href={`/members/${String(row.discord_id)}`}><strong>{String(row.rank_prefix ?? "")} {String(row.mta_nick)}</strong><code>ID {String(row.character_id ?? "—")}</code></Link> },
        { key: "rank_name", label: "PATENTE" },
        { key: "status", label: "STATUS", render: (row) => <Status value={row.status} /> },
        { key: "valid_hours_ms", label: "HORAS VÁLIDAS", render: (row) => duration(Number(row.valid_hours_ms)) },
        { key: "patrols", label: "PATRULHAS" },
        { key: "last_activity_at", label: "ÚLTIMA ATIVIDADE", render: (row) => dateTime(Number(row.last_activity_at)) },
        { key: "rank_sync_status", label: "IDENTIDADE", render: (row) => <Status value={row.rank_sync_status} /> },
      ]} />
    </section>
  </>;
}
