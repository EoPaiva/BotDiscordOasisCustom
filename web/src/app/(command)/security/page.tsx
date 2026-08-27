import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

import { revokeSecuritySessions, setSecurityLockdown } from "../actions";

type Row = Record<string, unknown>;
type SecurityData = {
  lockdown: { active: boolean; reason?: string | null; changed_at?: number | null; changed_by?: number | null };
  last_24_hours: Row[];
  events: Row[];
  health: { api: string; database: string; migration: number; failed_jobs: number };
};

export default async function SecurityPage() {
  const data = await commandCenterFetch<SecurityData>("/v1/security");
  const blocked = data.last_24_hours.reduce((total, row) => total + (/DENIED|BLOCKED/.test(String(row.result)) ? Number(row.total ?? 0) : 0), 0);
  const critical = data.last_24_hours.reduce((total, row) => total + (String(row.severity) === "CRITICAL" ? Number(row.total ?? 0) : 0), 0);
  return <>
    <PageHeader code="SYS / 03" title="Segurança do sistema" description="Controles de emergência, saúde interna e trilha restrita de eventos." />
    <MetricStrip items={[
      { label: "LOCKDOWN", value: <Status value={data.lockdown.active ? "ACTIVE" : "OPERATIONAL"} />, tone: data.lockdown.active ? "danger" : "success" },
      { label: "API / BANCO", value: `${data.health.api} / ${data.health.database}`, tone: "success" },
      { label: "BLOQUEIOS 24H", value: blocked, tone: blocked ? "warning" : "success" },
      { label: "CRÍTICOS 24H", value: critical, tone: critical ? "danger" : "success" },
      { label: "JOBS FALHOS", value: data.health.failed_jobs, tone: data.health.failed_jobs ? "warning" : "success" },
    ]} />
    <section className="command-section"><SectionHeader index="01" title="Modo de emergência" meta="Alterações administrativas são bloqueadas; leitura e auditoria permanecem" />
      {data.lockdown.active && <div className="candidate-blocked"><strong>SECURITY LOCKDOWN ATIVO</strong><p>{data.lockdown.reason ?? "Contenção administrativa em vigor."} {data.lockdown.changed_at ? `Desde ${dateTime(data.lockdown.changed_at)}.` : ""}</p></div>}
      <div className="security-controls">
        <form action={setSecurityLockdown} className="security-control-card"><h3>{data.lockdown.active ? "Encerrar lockdown" : "Ativar lockdown"}</h3><p>Exige justificativa e confirmação literal. Toda mudança é auditada.</p><input name="active" type="hidden" value={String(!data.lockdown.active)} /><label>Justificativa<textarea minLength={10} name="reason" required rows={3} /></label><label>Confirmação<input autoComplete="off" name="confirmation" placeholder={data.lockdown.active ? "LIBERAR" : "BLOQUEAR"} required /></label><button className={data.lockdown.active ? "button button-primary" : "button button-danger"} type="submit">{data.lockdown.active ? "Retornar à operação" : "Conter operações"}</button></form>
        <form action={revokeSecuritySessions} className="security-control-card"><h3>Revogação de sessões</h3><p>Informe um Discord ID para escopo individual ou deixe vazio para logout global.</p><label>Discord ID opcional<input inputMode="numeric" name="discordId" pattern="[0-9]*" /></label><label>Justificativa<textarea minLength={10} name="reason" required rows={3} /></label><label>Confirmação<input autoComplete="off" name="confirmation" placeholder="REVOGAR TODAS ou REVOGAR USUARIO" required /></label><button className="button button-danger" type="submit">Revogar sessões</button></form>
      </div>
    </section>
    <section className="command-section"><SectionHeader index="02" title="Eventos recentes" meta={`${data.events.length} registros append-only`} />
      <DataTable caption="Eventos recentes de segurança" rows={data.events} columns={[
        { key: "created_at", label: "DATA", render: (row) => dateTime(Number(row.created_at)) },
        { key: "severity", label: "SEVERIDADE", render: (row) => <Status value={row.severity} /> },
        { key: "event_type", label: "EVENTO", render: (row) => <strong>{label(row.event_type)}</strong> },
        { key: "result", label: "RESULTADO", render: (row) => <Status value={row.result} /> },
        { key: "actor_discord_id", label: "ATOR", render: (row) => <code>{String(row.actor_discord_id ?? "SISTEMA")}</code> },
        { key: "route", label: "ROTA" },
        { key: "request_id", label: "CORRELAÇÃO", render: (row) => <code className="truncate-code">{String(row.request_id)}</code> },
      ]} />
    </section>
  </>;
}
