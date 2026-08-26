import { Activity, ArrowRight, Radio, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { EmptyState, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { LiveDataRefresh } from "@/components/live-data-refresh";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, duration, label } from "@/lib/format";

type Row = Record<string, unknown>;
type DashboardData = {
  generated_at: number;
  readiness: { counts: Record<string, number> };
  patrols: Row[];
  queue: Row[];
  inbox: Row[];
  changes: { counts?: Record<string, number>; events?: Row[] };
  capabilities: {
    view_inbox: boolean;
    view_changes: boolean;
    view_all_operations: boolean;
  };
};

function memberIds(value: unknown): string[] {
  return String(value ?? "").split(",").filter(Boolean);
}

export default async function DashboardPage() {
  const data = await commandCenterFetch<DashboardData>("/v1/dashboard");
  const counts = data.readiness.counts ?? {};
  const changeCounts = data.changes.counts ?? {};
  const generatedAt = new Date(data.generated_at);
  const generatedAtLabel = new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo",
  }).format(generatedAt);
  return (
    <>
      <LiveDataRefresh intervalMs={10_000} />
      <PageHeader
        code="CC / 01"
        title="Centro de Comando"
        description={<><time dateTime={generatedAt.toISOString()}>{generatedAtLabel}</time> • Situação consolidada</>}
      />
      <MetricStrip items={[
        { label: "EM PATRULHA", value: counts.ON_PATROL ?? 0, tone: "success" },
        { label: "AGUARDANDO", value: counts.QUEUED ?? 0, tone: "warning" },
        { label: "DISPONÍVEIS", value: counts.AVAILABLE_FOR_PATROL ?? 0 },
        { label: "AUSENTES", value: counts.AWAY ?? 0 },
        { label: "TREINAMENTO", value: counts.IN_TRAINING ?? 0 },
        { label: "SUSPENSOS", value: counts.SUSPENDED ?? 0, tone: "danger" },
      ]} />

      <div className="dashboard-grid">
        <section className="command-section patrol-sector">
          <SectionHeader index="02" title="Patrulhas em andamento" meta={`${data.patrols.length} operações ativas`} />
          {data.patrols.length ? <div className="patrol-list">
            {data.patrols.map((patrol) => (
              <article className="patrol-record" key={String(patrol.id)}>
                <div className="patrol-code"><span>PTR</span><strong>{String(patrol.sequence_number ?? patrol.id).padStart(3, "0")}</strong></div>
                <div className="patrol-body">
                  <header><Status value={patrol.status} /><code>{String(patrol.voice_channel_name ?? `CALL ${String(patrol.voice_channel_id)}`)}</code></header>
                  <div className="patrol-members">
                    {String(patrol.member_names ?? "").split(" | ").filter(Boolean).map((name, index) => <span key={`${name}-${index}`}>EFETIVO <strong>{name}</strong></span>)}
                    {!patrol.member_names && memberIds(patrol.member_ids).map((id) => <span key={id}>{id === String(patrol.commander_discord_id ?? "") ? "COMANDANTE" : "EFETIVO"} <strong>{id}</strong></span>)}
                  </div>
                </div>
                <div className="patrol-time"><Radio size={15} aria-hidden="true" /><strong>{duration(data.generated_at - Number(patrol.started_at ?? data.generated_at))}</strong><span>{String(patrol.member_count ?? 0)} militares</span></div>
              </article>
            ))}
          </div> : <EmptyState title="Nenhuma patrulha ativa" detail="As calls de patrulhamento permanecem disponíveis." />}
          <Link className="text-link" href="/patrols">Abrir central de patrulhas <ArrowRight size={15} /></Link>
        </section>

        {data.capabilities.view_inbox && <section className="command-section pending-sector">
          <SectionHeader index="03" title="Pendências" meta={`${data.inbox.length} itens recentes`} />
          {data.inbox.length ? <div className="inbox-summary">{data.inbox.map((item, index) => {
            const detail = (item.data ?? {}) as Row;
            return <Link href="/inbox" key={`${item.type}-${item.id}-${index}`}>
              <div><code>{String(detail.code ?? `SOL-${item.id ?? index + 1}`)}</code><strong>{label(item.type ?? detail.request_type)}</strong></div>
              <div><Status value={detail.status ?? "PENDING"} /><span>{dateTime(Number(detail.created_at ?? detail.submitted_at ?? 0))}</span></div>
            </Link>;
          })}</div> : <EmptyState title="Caixa regular" detail="Nenhuma pendência administrativa no momento." />}
          <Link className="text-link" href="/inbox">Abrir caixa administrativa <ArrowRight size={15} /></Link>
        </section>}
      </div>

      <div className="dashboard-grid lower">
        <section className="command-section">
          <SectionHeader index="04" title="Fila operacional" meta="Ordem FIFO" />
          {data.queue.length ? <div className="queue-list">{data.queue.slice(0, 8).map((entry, index) => (
            <div key={String(entry.id)}><code>{String(index + 1).padStart(2, "0")}</code><strong>{String(entry.mta_nick ?? entry.discord_id)}</strong><span>{duration(data.generated_at - Number(entry.queue_entered_at ?? data.generated_at))}</span></div>
          ))}</div> : <EmptyState title="Fila vazia" detail="Nenhum militar aguarda formação de patrulha." />}
        </section>
        {data.capabilities.view_changes && <section className="command-section briefing-sector">
          <SectionHeader index="05" title="Briefing de mudanças" meta="Últimos 7 dias" />
          <div className="briefing-lines">
            {Object.entries(changeCounts).slice(0, 6).map(([key, value]) => (
              <div key={key}><Activity size={14} aria-hidden="true" /><span>{label(key)}</span><strong>{String(value)}</strong></div>
            ))}
            {!Object.keys(changeCounts).length && <div><ShieldAlert size={14} /><span>Sem alterações registradas</span></div>}
          </div>
        </section>}
      </div>
    </>
  );
}
