import { DataTable, EmptyState, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { LiveDataRefresh } from "@/components/live-data-refresh";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, duration, isoDuration } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function PatrolsPage() {
  const data = await commandCenterFetch<{ generated_at: number; active: Row[]; queue: Row[] }>("/v1/patrols");
  return <>
    <LiveDataRefresh intervalMs={10_000} />
    <PageHeader code="OP / 02" title="Central de patrulhas" description="Formações ativas, ocupação de calls e ordem automática de emprego." />
    <MetricStrip items={[
      { label: "PATRULHAS ATIVAS", value: data.active.length, tone: "success" },
      { label: "MILITARES EMPREGADOS", value: data.active.reduce((sum, row) => sum + Number(row.member_count ?? 0), 0) },
      { label: "AGUARDANDO", value: data.queue.length, tone: "warning" },
    ]} />
    <div className="split-operational">
      <section className="command-section">
        <SectionHeader index="01" title="Operações em andamento" />
        {data.active.length ? <ul aria-label="Patrulhas em andamento" className="patrol-list">{data.active.map((row) => <li key={String(row.id)}><article className="patrol-record">
          <div className="patrol-code"><span>PTR</span><strong>{String(row.sequence_number).padStart(3, "0")}</strong></div>
          <div className="patrol-body"><header><Status value={row.status} /><code>{String(row.voice_channel_name ?? `CALL ${String(row.voice_channel_id)}`)}</code></header><p>{String(row.member_count ?? 0)} militares na call</p><p>{row.member_names ? <><strong>{String(row.member_names).split(" | ").join(" • ")}</strong></> : <>Comandante: <strong>{row.commander_discord_id ? `[${String(row.commander_rank_prefix ?? row.commander_rank_name ?? "")}] ${String(row.commander_mta_nick ?? row.commander_discord_id)}` : "Não definido"}</strong></>}</p></div>
          <div className="patrol-time"><strong><time dateTime={isoDuration(data.generated_at - Number(row.started_at ?? data.generated_at))}>{duration(data.generated_at - Number(row.started_at ?? data.generated_at))}</time></strong><span>desde {dateTime(Number(row.started_at))}</span></div>
        </article></li>)}</ul> : <EmptyState title="Nenhuma patrulha ativa" detail="A central segue monitorando a call de espera." />}
      </section>
      <section className="command-section">
        <SectionHeader index="02" title="Fila FIFO" meta={`${data.queue.length} aguardando`} />
        <DataTable caption="Fila de patrulha" rows={data.queue} columns={[
          { key: "id", label: "POS", render: (row) => <code>{String(row.id).padStart(2, "0")}</code> },
          { key: "mta_nick", label: "MEMBRO", render: (row) => <strong>{String(row.mta_nick ?? row.discord_id)}</strong> },
          { key: "queue_entered_at", label: "ENTRADA", render: (row) => dateTime(Number(row.queue_entered_at)) },
          { key: "status", label: "STATUS", render: (row) => <Status value={row.status} /> },
        ]} />
      </section>
    </div>
  </>;
}
