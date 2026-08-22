import { AlertTriangle, CheckCircle2, KeyRound, Network, RefreshCcw, ScanSearch, ShieldCheck } from "lucide-react";
import { redirect } from "next/navigation";

import { DataTable, MetricStrip, PageHeader, SectionHeader, Status, StatusLabel } from "@/components/ui";
import { ReconciliationJobWatcher } from "@/components/reconciliation-job-watcher";
import { can } from "@/lib/access";
import { commandCenterFetch, getAccessContext } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

import {
  applyDiscordReconciliation,
  previewDiscordReconciliation,
  removeDiscordPermission,
  syncDiscordIdentity,
  upsertDiscordPermission,
  upsertDiscordRoleMapping,
} from "./actions";
import {
  normalizePermissionMatrix,
  permissionSubjectValue,
} from "./permissions";
import permissionStyles from "./permissions.module.css";

type Row = Record<string, unknown>;
type MappingPayload = {
  mappings: Row[];
  roles: Row[];
  ranks: Row[];
  positions: Row[];
  access_profiles: Row[];
  summary?: Row;
};

function asRow(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function asSnapshot(value: unknown): Row {
  if (typeof value === "string") {
    try {
      return asRow(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return asRow(value);
}

function rows(value: unknown): Row[] {
  return Array.isArray(value) ? value.map(asRow) : [];
}

function count(source: Row, ...keys: string[]): number {
  for (const key of keys) {
    const value = Number(source[key]);
    if (Number.isFinite(value)) return value;
  }
  return 0;
}

function rowId(row: Row): string {
  return String(row.id ?? row.resource_id ?? row.discord_role_id ?? "");
}

function rowName(row: Row): string {
  return String(row.name ?? row.display_name ?? row.label ?? row.code ?? rowId(row));
}

function optionLabel(row: Row): string {
  const code = row.code ?? row.internal_code;
  return code ? `${rowName(row)} · ${String(code)}` : rowName(row);
}

function optionalValue(value: unknown): string {
  return value == null ? "" : String(value);
}

function mappingForm(
  mapping: Row | null,
  resources: MappingPayload,
  roleNames: Record<string, string>,
) {
  const roleId = optionalValue(mapping?.discord_role_id);
  return (
    <form action={upsertDiscordRoleMapping} className="discord-mapping-form">
      <label>Cargo Discord
        <input
          defaultValue={roleId}
          list="discord-role-registry"
          name="discordRoleId"
          placeholder="ID numérico do cargo"
          required
        />
        {roleId && <small>{roleNames[roleId] ?? "Cargo fora do snapshot atual"}</small>}
      </label>
      <label>Tipo
        <select defaultValue={String(mapping?.mapping_type ?? "POSITION")} name="mappingType">
          {['RANK', 'POSITION', 'QUALIFICATION', 'SYSTEM', 'COSMETIC', 'ACCESS'].map((type) => <option key={type}>{type}</option>)}
        </select>
      </label>
      <label>Identificador interno
        <input defaultValue={String(mapping?.internal_code ?? "")} name="internalCode" placeholder="COMMANDER_GENERAL" required />
      </label>
      <label>Nome de apresentação
        <input defaultValue={String(mapping?.display_name ?? "")} name="displayName" placeholder="Comandante Geral" required />
      </label>
      <label>Prioridade
        <input defaultValue={String(mapping?.priority ?? 0)} name="priority" type="number" required />
      </label>
      <label>Patente vinculada
        <select defaultValue={optionalValue(mapping?.rank_id)} name="rankId">
          <option value="">Não se aplica</option>
          {resources.ranks.map((rank) => <option key={rowId(rank)} value={rowId(rank)}>{optionLabel(rank)}</option>)}
        </select>
      </label>
      <label>Função vinculada
        <select defaultValue={optionalValue(mapping?.position_id)} name="positionId">
          <option value="">Não se aplica</option>
          {resources.positions.map((position) => <option key={rowId(position)} value={rowId(position)}>{optionLabel(position)}</option>)}
        </select>
      </label>
      <label>Perfil concedido
        <select defaultValue={optionalValue(mapping?.access_profile_id)} name="accessProfileId">
          <option value="">Sem perfil direto</option>
          {resources.access_profiles.map((profile) => <option key={rowId(profile)} value={rowId(profile)}>{optionLabel(profile)}</option>)}
        </select>
      </label>
      <label>Candidato a cargo principal
        <select defaultValue={String(Boolean(mapping?.is_primary_position_candidate ?? false))} name="isPrimaryPositionCandidate">
          <option value="true">Sim</option><option value="false">Não</option>
        </select>
      </label>
      <label>Estado
        <select defaultValue={String(Boolean(mapping?.enabled ?? true))} name="enabled">
          <option value="true">Ativo</option><option value="false">Desativado</option>
        </select>
      </label>
      <button className="button button-primary" type="submit">{mapping ? "Salvar mapping" : "Criar mapping"}</button>
    </form>
  );
}

export default async function DiscordIdentityPage({
  searchParams,
}: {
  searchParams: Promise<{ previewJob?: string; job?: string; permissionAction?: string; permissionBumped?: string }>;
}) {
  const context = await getAccessContext();
  const canConfigure = can(context, "identity.configure");
  const canReconcile = can(context, "identity.reconcile");
  const canView = canConfigure || canReconcile || can(context, "identity.manage");
  if (!canView) redirect("/access-denied?reason=permission-revoked");

  const query = await searchParams;
  const selectedJobId = /^\d+$/.test(query.previewJob ?? "")
    ? Number(query.previewJob)
    : /^\d+$/.test(query.job ?? "") ? Number(query.job) : 0;
  const [mappingData, statusData, selectedJob, permissionPayload] = await Promise.all([
    canConfigure
      ? commandCenterFetch<MappingPayload>("/v1/discord/role-mappings")
      : Promise.resolve<MappingPayload>({ mappings: [], roles: [], ranks: [], positions: [], access_profiles: [] }),
    canReconcile
      ? commandCenterFetch<unknown>("/v1/discord/identity/status")
      : Promise.resolve({}),
    canReconcile && selectedJobId
      ? commandCenterFetch<unknown>(`/v1/discord/identity/reconciliations/${selectedJobId}`)
      : Promise.resolve(null),
    canConfigure
      ? commandCenterFetch<unknown>("/v1/discord/permissions")
      : Promise.resolve({}),
  ]);
  const permissionData = normalizePermissionMatrix(permissionPayload);
  const status = asRow(statusData);
  const statusSummary = asRow(status.summary ?? status);
  const syncStatusCounts = Object.fromEntries(
    rows(status.sync_status_counts).map((item) => [String(item.status ?? "UNKNOWN"), count(item, "total")]),
  );
  const jobs = rows(status.jobs ?? status.recent_jobs);
  const selectedJobPayload = asRow(selectedJob);
  const job = asRow(selectedJobPayload.job ?? selectedJobPayload);
  const jobItems = rows(selectedJobPayload.items ?? job.items);
  const roleNames = Object.fromEntries(
    mappingData.roles.map((role) => [String(role.resource_id ?? role.discord_role_id ?? role.id), rowName(role)]),
  );
  const permissionSubjects = permissionData.profiles.length
    + permissionData.ranks.length
    + permissionData.positions.length
    + permissionData.members.length;
  const permissionConfirmation = query.permissionAction === "saved"
    ? "Regra de permissão salva com sucesso."
    : query.permissionAction === "removed"
      ? "Regra de permissão removida com sucesso."
      : null;
  const authorizationVersionsBumped = /^\d+$/.test(query.permissionBumped ?? "")
    ? Number(query.permissionBumped)
    : 0;

  return <>
    <PageHeader
      code="SYS / DISCORD"
      title="Central de Identidade Discord"
      description="Mapeamento por role ID, identidade funcional e reconciliação auditável. O backend continua sendo a autoridade final de cada ação."
      actions={<div className="discord-page-links"><a className="button button-secondary" href="#mapeamentos">Mapeamentos</a>{canConfigure && <a className="button button-secondary" href="#permissoes">Permissões</a>}{canReconcile && <a className="button button-secondary" href="#sincronizacao">Sincronização</a>}</div>}
    />
    <MetricStrip items={[
      { label: "MAPPINGS ATIVOS", value: count(asRow(mappingData.summary), "active", "active_mappings") || mappingData.mappings.filter((item) => Boolean(item.enabled)).length },
      { label: "MEMBROS SINCRONIZADOS", value: syncStatusCounts.SYNCED ?? 0 },
      { label: "DIVERGÊNCIAS", value: syncStatusCounts.REVIEW_REQUIRED ?? 0, tone: syncStatusCounts.REVIEW_REQUIRED ? "warning" : undefined },
      { label: "FALHAS", value: syncStatusCounts.ERROR ?? 0, tone: syncStatusCounts.ERROR ? "danger" : undefined },
      { label: "FILA PENDENTE", value: count(status, "pending_actions") },
    ]} />

    {permissionConfirmation && <div className={permissionStyles.confirmation} role="status">
      <CheckCircle2 size={18} aria-hidden="true" />
      <div><strong>Alteração confirmada</strong><p>{permissionConfirmation} {authorizationVersionsBumped} versão(ões) de autorização atualizada(s).</p></div>
    </div>}

    {canConfigure && <section className="command-section discord-section" id="mapeamentos">
      <SectionHeader index="01" title="Mapeamento de cargos" meta={`${mappingData.mappings.length} regra(s) por ID`} />
      <datalist id="discord-role-registry">
        {mappingData.roles.map((role) => <option key={rowId(role)} value={String(role.resource_id ?? role.discord_role_id ?? role.id)}>{rowName(role)}</option>)}
      </datalist>
      <details className="discord-new-mapping">
        <summary><Network size={16} aria-hidden="true" /> Adicionar cargo mapeado</summary>
        {mappingForm(null, mappingData, roleNames)}
      </details>
      <div className="discord-mapping-list">
        {mappingData.mappings.map((mapping) => (
          <details key={`${String(mapping.discord_role_id)}:${String(mapping.mapping_type)}`}>
            <summary>
              <span><strong>{String(mapping.display_name ?? roleNames[String(mapping.discord_role_id)] ?? "Cargo Discord")}</strong><code>{String(mapping.discord_role_id)}</code></span>
              <span><Status value={mapping.mapping_type} /><code>{String(mapping.internal_code)}</code></span>
              <span><Status value={mapping.enabled ? "ACTIVE" : "DISABLED"} /><strong>{String(mapping.priority ?? 0)}</strong></span>
            </summary>
            {mappingForm(mapping, mappingData, roleNames)}
          </details>
        ))}
        {!mappingData.mappings.length && <p className="identity-empty">Nenhum mapping disponível para esta guild.</p>}
      </div>
    </section>}

    {canConfigure && <section className="command-section discord-section" id="permissoes">
      <SectionHeader index="02" title="Matriz de permissões" meta="GRANT e DENY por identificador interno" />
      <div className={permissionStyles.summary}>
        <div><span>Regras explícitas</span><strong>{permissionData.summary.total}</strong></div>
        <div><span>Concessões</span><strong>{permissionData.summary.grants}</strong></div>
        <div><span>Negações</span><strong>{permissionData.summary.denies}</strong></div>
      </div>
      <form action={upsertDiscordPermission} className={permissionStyles.editor}>
        <label>Sujeito da regra
          <select name="subject" defaultValue="" required>
            <option value="" disabled>Selecione por ID interno</option>
            <optgroup label="Perfis de acesso">
              {permissionData.profiles.map((profile) => <option key={`PROFILE:${rowId(profile)}`} value={permissionSubjectValue("PROFILE", profile.id)}>{optionLabel(profile)} · ID {rowId(profile)}</option>)}
            </optgroup>
            <optgroup label="Patentes">
              {permissionData.ranks.map((rank) => <option key={`RANK:${rowId(rank)}`} value={permissionSubjectValue("RANK", rank.id)}>{optionLabel(rank)} · ID {rowId(rank)}</option>)}
            </optgroup>
            <optgroup label="Funções">
              {permissionData.positions.map((position) => <option key={`POSITION:${rowId(position)}`} value={permissionSubjectValue("POSITION", position.id)}>{optionLabel(position)} · ID {rowId(position)}</option>)}
            </optgroup>
            <optgroup label="Membros">
              {permissionData.members.map((member) => <option key={`MEMBER:${rowId(member)}`} value={permissionSubjectValue("MEMBER", member.id)}>{String(member.mta_nick ?? "Membro")} · Discord {String(member.discord_id ?? "—")} · ID {rowId(member)}</option>)}
            </optgroup>
          </select>
        </label>
        <label>Permissão
          <select name="permission" defaultValue="" required>
            <option value="" disabled>Selecione do catálogo</option>
            {permissionData.catalog.map((permission) => <option key={permission} value={permission}>{permission}</option>)}
          </select>
        </label>
        <label>Efeito
          <select name="effect" defaultValue="GRANT"><option value="GRANT">Conceder</option><option value="DENY">Negar</option></select>
        </label>
        <label>Motivo
          <input name="reason" type="text" maxLength={500} placeholder="Justificativa auditável" />
        </label>
        <label className={permissionStyles.confirmCheck}>
          <input name="confirmation" type="checkbox" value="CONFIRMAR" required />
          Confirmo a alteração desta regra de autorização.
        </label>
        <button className="button button-primary" type="submit" disabled={!permissionData.catalog.length || !permissionSubjects}><KeyRound size={15} aria-hidden="true" /> Salvar regra</button>
      </form>
      <DataTable rows={permissionData.rules} rowKey="_key" columns={[
        { key: "subject_name", label: "SUJEITO", render: (item) => <span className={permissionStyles.subject}><strong>{String(item.subject_name)}</strong><code>{String(item.subject_type)}:{String(item.subject_id)}</code></span> },
        { key: "permission", label: "PERMISSÃO", render: (item) => <code className={permissionStyles.permissionCode}>{String(item.permission)}</code> },
        { key: "effect", label: "EFEITO", render: (item) => <StatusLabel label={String(item.effect)} tone={item.effect === "DENY" ? "danger" : "success"} /> },
        { key: "reason", label: "MOTIVO", render: (item) => <span className={permissionStyles.reason}>{String(item.reason ?? "Sem justificativa registrada")}</span> },
        { key: "updated_at", label: "ATUALIZAÇÃO", render: (item) => dateTime(Number(item.updated_at)) },
        { key: "action", label: "AÇÃO", render: (item) => <details className={permissionStyles.remove}><summary>Remover regra</summary><form action={removeDiscordPermission}><input name="subjectType" type="hidden" value={String(item.subject_type)} /><input name="subjectId" type="hidden" value={String(item.subject_id)} /><input name="permission" type="hidden" value={String(item.permission)} /><label><input name="confirmation" type="checkbox" value="CONFIRMAR" required /> Confirmar remoção</label><button className="button button-danger compact" type="submit">Remover</button></form></details> },
      ]} />
    </section>}

    {canReconcile && <section className="command-section discord-section" id="sincronizacao">
      <SectionHeader index={canConfigure ? "03" : "01"} title="Sincronização e reconciliação" meta="Preview obrigatório antes da aplicação em lote" />
      <div className="discord-sync-controls">
        <form action={syncDiscordIdentity}>
          <div><RefreshCcw size={19} aria-hidden="true" /><span><strong>Reparar um membro</strong><small>Lê os cargos atuais do Discord e aplica a pipeline central.</small></span></div>
          <label>Discord ID<input name="discordId" inputMode="numeric" pattern="\d+" required /></label>
          <button className="button button-secondary" type="submit">Reconciliar membro</button>
        </form>
        <form action={previewDiscordReconciliation}>
          <div><ScanSearch size={19} aria-hidden="true" /><span><strong>Reconciliação em lote</strong><small>Gera diagnóstico sem alterar identidades.</small></span></div>
          <button className="button button-primary" type="submit">Gerar preview</button>
        </form>
      </div>
      <div className="discord-sync-status">
        <div><span>Última execução</span><strong>{Number(statusSummary.last_sync_at ?? statusSummary.last_completed_at ?? 0) ? dateTime(Number(statusSummary.last_sync_at ?? statusSummary.last_completed_at)) : "Sem execução registrada"}</strong></div>
        <div><span>Casos em revisão</span><strong>{syncStatusCounts.REVIEW_REQUIRED ?? 0}</strong></div>
        <div><span>Membros ausentes</span><strong>{syncStatusCounts.DISCORD_ABSENT ?? 0}</strong></div>
        <div><span>Job em processamento</span><Status value={statusSummary.running_job_id ? "PROCESSING" : "IDLE"} /></div>
      </div>
    </section>}

    {canReconcile && selectedJobId > 0 && <section className="command-section discord-section">
      <SectionHeader index={canConfigure ? "04" : "02"} title={`Job de reconciliação #${selectedJobId}`} meta={String(job.correlation_id ?? "correlação indisponível")} />
      <ReconciliationJobWatcher jobId={selectedJobId} initialStatus={String(job.status ?? "PENDING")} />
      <div className="reconciliation-verdict">
        <div><Status value={job.status ?? "PENDING"} /><strong>{label(job.mode ?? "PREVIEW")}</strong></div>
        <div><span>Sem alteração</span><strong>{count(job, "unchanged_members")}</strong></div>
        <div><span>Posições divergentes</span><strong>{count(job, "divergent_positions")}</strong></div>
        <div><span>Patentes divergentes</span><strong>{count(job, "divergent_ranks")}</strong></div>
        <div><span>Revisão</span><strong>{count(job, "review_required")}</strong></div>
        <div><span>Falhas</span><strong>{count(job, "failed_members")}</strong></div>
      </div>
      {String(job.mode ?? "").toUpperCase() === "PREVIEW" && String(job.status ?? "").toUpperCase() === "COMPLETED" && (
        <form action={applyDiscordReconciliation} className="reconciliation-apply">
          <AlertTriangle size={18} aria-hidden="true" />
          <div><strong>Aplicar este preview</strong><p>O job de aplicação reutilizará exatamente este diagnóstico e manterá auditoria por membro.</p></div>
          <input name="previewJobId" type="hidden" value={selectedJobId} />
          <button className="button button-primary" type="submit">Aplicar reconciliação</button>
        </form>
      )}
      <DataTable rows={jobItems} columns={[
        { key: "discord_id", label: "MEMBRO", render: (item) => <code>{String(item.discord_id)}</code> },
        { key: "result", label: "RESULTADO", render: (item) => <Status value={item.result} /> },
        { key: "rank", label: "PATENTE", render: (item) => String(asSnapshot(item.after ?? item.after_json).rank_name ?? asSnapshot(item.after ?? item.after_json).rank ?? "—") },
        { key: "position", label: "CARGO", render: (item) => String(asSnapshot(item.after ?? item.after_json).primary_position_name ?? asSnapshot(item.after ?? item.after_json).primary_position ?? "—") },
        { key: "error", label: "OBSERVAÇÃO" },
      ]} />
    </section>}

    {canReconcile && jobs.length > 0 && <section className="command-section discord-section">
      <SectionHeader index={canConfigure ? "05" : "03"} title="Execuções recentes" />
      <DataTable rows={jobs} columns={[
        { key: "id", label: "JOB", render: (item) => <a className="text-link inline" href={`/discord?job=${String(item.id)}`}>#{String(item.id)}</a> },
        { key: "mode", label: "MODO", render: (item) => label(item.mode) },
        { key: "status", label: "STATUS", render: (item) => <Status value={item.status} /> },
        { key: "total_members", label: "PROCESSADOS" },
        { key: "created_at", label: "CRIADO", render: (item) => dateTime(Number(item.created_at)) },
      ]} />
    </section>}

    <div className="discord-authority-note"><ShieldCheck size={18} aria-hidden="true" /><p>Os controles desta página não concedem autorização no navegador. Toda leitura e mutação é revalidada pela API com o PermissionService.</p></div>
  </>;
}
