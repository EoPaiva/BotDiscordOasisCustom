import { DataTable, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function AuditPage() {
  const rows = await commandCenterFetch<Row[]>("/v1/audit?limit=150");
  return <>
    <PageHeader code="INT / 03" title="Auditoria do sistema" description="Trilha cronológica de ações, decisões, automações e reconciliações." />
    <section className="command-section"><SectionHeader index="01" title="Registros recentes" meta={`${rows.length} eventos`} />
      <DataTable rows={rows} columns={[
        { key: "created_at", label: "DATA", render: (row) => dateTime(Number(row.created_at)) },
        { key: "action", label: "AÇÃO", render: (row) => <strong>{label(row.action)}</strong> },
        { key: "actor_id", label: "RESPONSÁVEL", render: (row) => <code>{String(row.actor_id ?? "SISTEMA")}</code> },
        { key: "target_id", label: "ALVO", render: (row) => <code>{String(row.target_id ?? "—")}</code> },
        { key: "reason", label: "MOTIVO" },
        { key: "delivery_status", label: "ENTREGA", render: (row) => <Status value={row.delivery_status} /> },
        { key: "correlation_id", label: "CORRELAÇÃO", render: (row) => <code className="truncate-code">{String(row.correlation_id)}</code> },
      ]} />
    </section>
  </>;
}

