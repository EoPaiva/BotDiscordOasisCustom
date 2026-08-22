import { Check, X } from "lucide-react";
import { notFound } from "next/navigation";

import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, duration, label } from "@/lib/format";

import { changeRank } from "../../actions";

type Row = Record<string, unknown>;
type MemberData = {
  identity?: Row;
  dossier: {
    member: Row;
    identity?: Row;
    positions?: Row[];
    valid_hours_ms: number;
    patrol_statistics: Record<string, unknown>;
    personnel_actions: Row[];
    punishments: Row[];
    absences: Row[];
    qualifications: Row[];
    flags: Row[];
  };
  eligibility: {
    checks: Record<string, boolean>;
    next_rank: Row | null;
    rank_days: number;
    valid_hours_ms: number;
    missing_courses: string[];
    eligible_for_human_review: boolean;
  };
};

function asRow(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function displayName(value: unknown, fallback?: unknown): string {
  if (typeof value === "string" && value.trim()) return value;
  const row = asRow(value);
  return String(row.name ?? row.display_name ?? fallback ?? "—");
}

export default async function MemberPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const data = await commandCenterFetch<MemberData>(`/v1/members/${id}`);
  const member = data.dossier.member;
  const stats = data.dossier.patrol_statistics;
  const identity = asRow(data.identity ?? data.dossier.identity);
  const positions = Array.isArray(data.dossier.positions)
    ? data.dossier.positions
    : Array.isArray(identity.functions)
      ? identity.functions.map(asRow)
      : Array.isArray(member.functions)
        ? member.functions.map(asRow)
        : [];
  const functions = positions.filter((position) => position.is_primary !== true && position.is_primary !== 1);
  const primaryPosition = displayName(
    identity.primary_position ?? member.primary_position,
    identity.primary_position_name ?? member.primary_position_name,
  );
  const accessProfile = displayName(
    identity.access_profile ?? member.access_profile,
    identity.access_profile_name ?? identity.access_profile_code
      ?? member.access_profile_name ?? member.access_profile_code,
  );
  const identitySyncStatus = String(
    identity.identity_sync_status ?? member.identity_sync_status ?? member.rank_sync_status ?? "PENDING",
  );
  const discordSyncedAt = Number(
    identity.discord_synced_at ?? identity.discord_roles_synced_at
      ?? member.discord_synced_at ?? member.discord_roles_synced_at ?? 0,
  );
  return <>
    <PageHeader code={`DOS / ${String(member.character_id ?? "—")}`} title={`${String(member.rank_name ?? "SEM PATENTE")} / ${String(member.mta_nick)}`} description="Dossiê funcional consolidado. Dados sensíveis sujeitos a RBAC e auditoria." />
    <MetricStrip items={[
      { label: "SITUAÇÃO", value: <Status value={member.status} /> },
      { label: "HORAS VÁLIDAS", value: duration(data.dossier.valid_hours_ms) },
      { label: "PATRULHAS", value: String(stats.total ?? 0) },
      { label: "TEMPO NA PATENTE", value: `${data.eligibility.rank_days} dias` },
    ]} />
    <div className="dossier-layout">
      <div className="dossier-main">
        <section className="command-section dossier-section"><SectionHeader index="01" title="Identificação" />
          <dl className="document-grid">
            <div><dt>Discord ID</dt><dd><code>{String(member.discord_id)}</code></dd></div>
            <div><dt>ID MTA</dt><dd>{String(member.character_id ?? "—")}</dd></div>
            <div><dt>Unidade</dt><dd>{String(member.unit ?? "—")}</dd></div>
            <div><dt>Ingresso</dt><dd>{dateTime(Number(member.joined_at))}</dd></div>
            <div><dt>Sincronização</dt><dd><Status value={member.rank_sync_status} /></dd></div>
            <div><dt>Última atividade</dt><dd>{dateTime(Number(member.last_activity_at))}</dd></div>
          </dl>
        </section>
        <section className="command-section dossier-section"><SectionHeader index="02" title="Identidade funcional Discord" meta={`Autorização v${String(identity.authorization_version ?? member.authorization_version ?? 1)}`} />
          <dl className="document-grid identity-dossier-grid">
            <div><dt>Patente</dt><dd>{String(member.rank_name ?? "—")}</dd></div>
            <div><dt>Cargo principal</dt><dd>{primaryPosition}</dd></div>
            <div><dt>Perfil de acesso</dt><dd>{accessProfile}</dd></div>
            <div><dt>Estado</dt><dd><Status value={identitySyncStatus} /></dd></div>
            <div><dt>Último sync Discord</dt><dd>{discordSyncedAt ? dateTime(discordSyncedAt) : "Aguardando sincronização"}</dd></div>
            <div><dt>Presença na guild</dt><dd><Status value={(identity.discord_present ?? member.discord_present ?? true) ? "PRESENT" : "DISCORD_ABSENT"} /></dd></div>
          </dl>
          <div className="dossier-functions">
            <span>FUNÇÕES SECUNDÁRIAS</span>
            {functions.length ? <div className="function-badges">{functions.map((position, index) => (
              <span key={String(position.code ?? position.id ?? index)}>
                <strong>{displayName(position)}</strong>
                {position.code != null && <code>{String(position.code)}</code>}
              </span>
            ))}</div> : <p className="muted">Nenhuma função secundária vinculada.</p>}
          </div>
        </section>
        <section className="command-section dossier-section"><SectionHeader index="03" title="Carreira" />
          <div className="timeline">{data.dossier.personnel_actions.length ? data.dossier.personnel_actions.map((row) => <div key={String(row.id)}><time>{dateTime(Number(row.created_at))}</time><span /><div><strong>{label(row.action_type)}</strong><p>{String(row.reason ?? "Sem observação")}</p></div></div>) : <p className="muted">Nenhuma movimentação registrada.</p>}</div>
        </section>
        <section className="command-section dossier-section"><SectionHeader index="04" title="Qualificações" />
          <DataTable rows={data.dossier.qualifications} columns={[
            { key: "course_name", label: "CURSO", render: (row) => <strong>{String(row.course_name)}</strong> },
            { key: "result", label: "RESULTADO", render: (row) => <Status value={row.result} /> },
            { key: "recorded_at", label: "REGISTRO", render: (row) => dateTime(Number(row.recorded_at)) },
          ]} />
        </section>
        <section className="command-section dossier-section"><SectionHeader index="05" title="Disciplina e integridade" />
          <DataTable rows={[...data.dossier.punishments, ...data.dossier.flags]} columns={[
            { key: "id", label: "REGISTRO", render: (row) => <code>#{String(row.id)}</code> },
            { key: "punishment_type", label: "TIPO", render: (row) => label(row.punishment_type ?? row.flag_type) },
            { key: "status", label: "STATUS", render: (row) => <Status value={row.status} /> },
            { key: "reason", label: "MOTIVO" },
          ]} />
        </section>
      </div>
      <aside className="eligibility-panel">
        <span className="technical-index">CAR / ANÁLISE</span><h2>Elegibilidade</h2>
        <Status value={data.eligibility.eligible_for_human_review ? "ELIGIBLE" : "REVIEW_REQUIRED"} />
        <div className="checklist">{Object.entries(data.eligibility.checks).map(([key, passed]) => <div key={key}>{passed ? <Check size={15} /> : <X size={15} />}<span>{label(key)}</span><strong>{passed ? "ATENDIDO" : "PENDENTE"}</strong></div>)}</div>
        {data.eligibility.next_rank && <form action={changeRank} className="decision-form">
          <h3>Propor movimentação</h3>
          <div className="rank-transition"><span>{String(member.rank_name ?? "Sem patente")}</span><strong>→</strong><span>{String(data.eligibility.next_rank.name)}</span></div>
          <input type="hidden" name="discordId" value={id} /><input type="hidden" name="targetRankId" value={String(data.eligibility.next_rank.id)} /><input type="hidden" name="action" value="PROMOTION" />
          <label>Motivo<textarea name="reason" required minLength={3} /></label>
          <label>Confirmação<input name="confirmation" required pattern="CONFIRMAR" placeholder="Digite CONFIRMAR" /></label>
          <button className="button button-primary" type="submit" disabled={!data.eligibility.eligible_for_human_review}>Registrar e sincronizar</button>
          <p>A promoção nunca é automática. O Discord será atualizado pelo outbox.</p>
        </form>}
      </aside>
    </div>
  </>;
}
