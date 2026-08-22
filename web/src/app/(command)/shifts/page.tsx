import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, duration } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function ShiftsPage() {
  const rows = await commandCenterFetch<Row[]>("/v1/shifts");
  const active = rows.filter((row) => ["ACTIVE", "GRACE"].includes(String(row.status))).length;
  const invalid = rows.filter((row) => row.validation_status === "INVALIDATED").length;
  return <>
    <PageHeader code="OP / 03" title="Controle de ponto" description="Sessões por timestamp, tempo bruto, patrulha válida e revisão administrativa." />
    <MetricStrip items={[
      { label: "PONTOS ATIVOS", value: active, tone: "success" },
      { label: "EM REVISÃO", value: rows.filter((row) => row.status === "REVIEW_REQUIRED").length, tone: "warning" },
      { label: "INVALIDADOS", value: invalid, tone: "danger" },
      { label: "REGISTROS EXIBIDOS", value: rows.length },
    ]} />
    <section className="command-section">
      <SectionHeader index="01" title="Sessões recentes" />
      <DataTable rows={rows} columns={[
        { key: "id", label: "SESSÃO", render: (row) => <code>PT-{String(row.id).padStart(5, "0")}</code> },
        { key: "mta_nick", label: "MEMBRO", render: (row) => <strong>{String(row.mta_nick)}</strong> },
        { key: "started_at", label: "INÍCIO", render: (row) => dateTime(Number(row.started_at)) },
        { key: "gross_duration_ms", label: "TEMPO BRUTO", render: (row) => duration(Number(row.gross_duration_ms)) },
        { key: "patrol_duration_ms", label: "PATRULHA", render: (row) => duration(Number(row.patrol_duration_ms)) },
        { key: "minimum_patrol_ms", label: "MÍNIMO", render: (row) => duration(Number(row.minimum_patrol_ms)) },
        { key: "validation_status", label: "VALIDAÇÃO", render: (row) => <Status value={row.validation_status} /> },
      ]} />
    </section>
  </>;
}

