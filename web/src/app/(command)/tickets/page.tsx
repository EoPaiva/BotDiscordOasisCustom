import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

import { updateTicketConfiguration } from "../actions";

type Row = Record<string, unknown>;
type Resource = { resource_id: number; name: string };
type TicketOperationsData = {
  counts: Record<string, number>;
  tickets: Row[];
  rooms: Row[];
  configuration: Record<string, unknown>;
  resources: { roles: Resource[]; channels: Resource[]; categories: Resource[] };
  validation: { ready: boolean; hierarchy_valid: boolean; blockers: string[] };
};

function ResourceSetting({
  title,
  settingKey,
  current,
  resources,
}: {
  title: string;
  settingKey: string;
  current: unknown;
  resources: Resource[];
}) {
  return <form action={updateTicketConfiguration} className="setting-row">
    <div><strong>{title}</strong><span>Recurso validado pelo registry Discord</span></div>
    <input name="key" type="hidden" value={settingKey} />
    <select defaultValue={String(current ?? "")} name="value" required>
      <option disabled value="">Selecione por ID</option>
      {resources.map((resource) => <option key={resource.resource_id} value={resource.resource_id}>{resource.name}</option>)}
    </select>
    <button className="button button-secondary compact" type="submit">Vincular</button>
  </form>;
}

export default async function TicketOperationsPage() {
  const data = await commandCenterFetch<TicketOperationsData>("/v1/tickets/operations");
  const config = data.configuration;
  const activeRooms = data.rooms.filter((room) => room.status === "OPEN").length;
  const archivedRooms = data.rooms.filter((room) => room.status === "ARCHIVED").length;
  return <>
    <PageHeader code="ADM / 03" title="Operação de Atendimentos" description="Salas privadas, prioridade, responsáveis, participantes, transcrições e reabertura sob auditoria." />
    <MetricStrip items={[
      { label: "CONFIGURAÇÃO", value: <Status value={data.validation.ready ? "READY" : "REVIEW"} />, tone: data.validation.ready ? "success" : "danger" },
      { label: "SALAS ATIVAS", value: activeRooms, tone: activeRooms ? "warning" : "success" },
      { label: "ARQUIVADAS", value: archivedRooms },
      { label: "DENÚNCIAS", value: data.counts.REPORT ?? 0, tone: data.counts.REPORT ? "danger" : "success" },
      { label: "OUTROS", value: data.counts.OTHER ?? 0 },
      { label: "HIERARQUIA DO BOT", value: <Status value={data.validation.hierarchy_valid ? "VALID" : "REVIEW"} />, tone: data.validation.hierarchy_valid ? "success" : "danger" },
    ]} />

    <section className="command-section"><SectionHeader index="01" title="Fila operacional" meta="Prioridade e responsável vêm do estado transacional" />
      <DataTable rows={data.tickets} columns={[
        { key: "id", label: "PROTOCOLO", render: (row) => <strong>TCK-{String(row.id).padStart(4, "0")}</strong> },
        { key: "ticket_type", label: "TIPO", render: (row) => label(row.ticket_type) },
        { key: "status", label: "SITUAÇÃO", render: (row) => <Status value={row.status} /> },
        { key: "priority", label: "PRIORIDADE", render: (row) => <Status value={row.priority} /> },
        { key: "claimed_by", label: "RESPONSÁVEL", render: (row) => <code>{String(row.claimed_by ?? "—")}</code> },
        { key: "channel_id", label: "SALA", render: (row) => <code>{String(row.channel_id ?? "—")}</code> },
        { key: "updated_at", label: "ATUALIZADO", render: (row) => dateTime(Number(row.updated_at)) },
      ]} />
    </section>

    <section className="command-section settings-section"><SectionHeader index="02" title="Configuração Discord" meta="Preview e validação antes de qualquer alteração estrutural" />
      <div className="settings-grid">
        <ResourceSetting title="Categoria de tickets ativos" settingKey="ticket_active_category_id" current={config.ticket_active_category_id} resources={data.resources.categories} />
        <ResourceSetting title="Categoria de tickets arquivados" settingKey="ticket_archive_category_id" current={config.ticket_archive_category_id} resources={data.resources.categories} />
        <ResourceSetting title="Cargo responsável" settingKey="ticket_responsible_role_id" current={config.ticket_responsible_role_id} resources={data.resources.roles} />
        <ResourceSetting title="Canal privado de transcrições" settingKey="ticket_transcript_channel_id" current={config.ticket_transcript_channel_id} resources={data.resources.channels} />
        <form action={updateTicketConfiguration} className="setting-row"><div><strong>Intervalo entre avisos</strong><span>30–3600 segundos</span></div><input name="key" type="hidden" value="ticket_requester_notify_cooldown_seconds" /><input defaultValue={String(config.ticket_requester_notify_cooldown_seconds ?? 60)} max={3600} min={30} name="value" type="number" /><button className="button button-secondary compact" type="submit">Salvar</button></form>
      </div>
      {data.validation.blockers.length ? <div className="notice danger"><strong>Bloqueadores</strong><span>{data.validation.blockers.join(" • ")}</span></div> : null}
    </section>
  </>;
}
