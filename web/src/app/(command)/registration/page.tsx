import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

import { decideRegistrationGate, updateRegistrationGateConfiguration } from "../actions";

type Row = Record<string, unknown>;
type Resource = { resource_id: number; name: string };
type RegistrationData = {
  counts: Record<string, number>;
  records: Row[];
  findings: Row[];
  classifications: Row[];
  configuration: Record<string, unknown>;
  resources: { roles: Resource[]; channels: Resource[]; categories: Resource[] };
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
  return <form action={updateRegistrationGateConfiguration} className="setting-row">
    <div><strong>{title}</strong><span>Registry Discord</span></div>
    <input name="key" type="hidden" value={settingKey} />
    <input name="valueType" type="hidden" value="id" />
    <select defaultValue={String(current ?? "")} name="value" required>
      <option disabled value="">Selecione por ID</option>
      {resources.map((resource) => <option key={resource.resource_id} value={resource.resource_id}>{resource.name}</option>)}
    </select>
    <button className="button button-secondary compact" type="submit">Vincular</button>
  </form>;
}

export default async function RegistrationGatePage() {
  const data = await commandCenterFetch<RegistrationData>("/v1/registration-gate");
  const counts = data.counts;
  const config = data.configuration;
  const classificationCounts = Object.groupBy(data.classifications, (item) => String(item.access_class));
  return <>
    <PageHeader code="ADM / 02" title="Portaria Digital" description="Identidade, acesso mínimo e sincronização de cargos sem transformar cadastro em candidatura." />
    <MetricStrip items={[
      { label: "GATE", value: <Status value={config.registration_gate_enabled ? "ACTIVE" : "DISABLED"} />, tone: config.registration_gate_enabled ? "success" : "warning" },
      { label: "NÃO CADASTRADOS", value: counts.UNREGISTERED ?? 0, tone: counts.UNREGISTERED ? "warning" : "success" },
      { label: "PENDENTES", value: counts.PENDING ?? 0, tone: counts.PENDING ? "warning" : "success" },
      { label: "REVISÃO", value: counts.REQUIRES_REVIEW ?? 0, tone: counts.REQUIRES_REVIEW ? "danger" : "success" },
      { label: "CONCLUÍDOS / 24H", value: counts.COMPLETED_LAST_24H ?? 0 },
      { label: "ACHADOS", value: data.findings.length, tone: data.findings.length ? "danger" : "success" },
    ]} />

    <section className="command-section"><SectionHeader index="01" title="Cadastros para revisão" meta="Decisões humanas, transacionais e auditadas" />
      <DataTable rows={data.records} columns={[
        { key: "id", label: "PROTOCOLO", render: (row) => <strong>CAD-{String(row.id).padStart(4, "0")}</strong> },
        { key: "discord_id", label: "DISCORD", render: (row) => <code>{String(row.discord_id)}</code> },
        { key: "mta_nick", label: "NICK BGR" },
        { key: "bgr_id", label: "ID BGR", render: (row) => <code>{String(row.bgr_id ?? "—")}</code> },
        { key: "status", label: "SITUAÇÃO", render: (row) => <Status value={row.status} /> },
        { key: "conflict_code", label: "DIVERGÊNCIA", render: (row) => label(row.conflict_code ?? "NONE") },
        { key: "action", label: "DECISÃO", render: (row) => <form action={decideRegistrationGate} className="table-action-stack">
          <input name="registrationId" type="hidden" value={String(row.id)} />
          <select defaultValue={row.conflict_member_id ? "LINK_EXISTING" : "APPROVE"} name="action">
            <option value="APPROVE">Aprovar novo membro</option>
            <option value="LINK_EXISTING">Vincular perfil existente</option>
            <option value="CORRECT_ID">Corrigir ID</option>
            <option value="DENY">Negar cadastro</option>
          </select>
          <input name="memberId" placeholder="Member ID para vínculo" />
          <input name="bgrId" placeholder="Novo ID para correção" />
          <textarea minLength={3} name="reason" placeholder="Motivo obrigatório" required rows={2} />
          <button className="button button-primary compact" type="submit">Registrar decisão</button>
        </form> },
      ]} />
    </section>

    <section className="command-section settings-section"><SectionHeader index="02" title="Configuração de acesso" meta="Recursos localizados exclusivamente pelo registry de IDs" />
      <div className="settings-grid">
        <ResourceSetting title="Cargo não cadastrado" settingKey="unregistered_role_id" current={config.unregistered_role_id} resources={data.resources.roles} />
        <ResourceSetting title="Cargo de candidato" settingKey="candidate_role_id" current={config.candidate_role_id} resources={data.resources.roles} />
        <ResourceSetting title="Cargo base de membro" settingKey="member_role_id" current={config.member_role_id} resources={data.resources.roles} />
        <ResourceSetting title="Categoria de recepção" settingKey="registration_onboarding_category_id" current={config.registration_onboarding_category_id} resources={data.resources.categories} />
        <ResourceSetting title="Canal da Portaria" settingKey="registration_panel_channel_id" current={config.registration_panel_channel_id} resources={data.resources.channels} />
        <ResourceSetting title="Canal de suporte" settingKey="registration_support_channel_id" current={config.registration_support_channel_id} resources={data.resources.channels} />
        <form action={updateRegistrationGateConfiguration} className="setting-row"><div><strong>Cadastro obrigatório</strong><span>Ative apenas com zero achados bloqueadores</span></div><input name="key" type="hidden" value="registration_gate_enabled" /><input name="valueType" type="hidden" value="boolean" /><select defaultValue={String(Boolean(config.registration_gate_enabled))} name="value"><option value="true">Ativo</option><option value="false">Inativo</option></select><button className="button button-danger compact" type="submit">Aplicar</button></form>
        <form action={updateRegistrationGateConfiguration} className="setting-row"><div><strong>DM de boas-vindas</strong><span>Falha de DM nunca bloqueia o fluxo</span></div><input name="key" type="hidden" value="registration_dm_enabled" /><input name="valueType" type="hidden" value="boolean" /><select defaultValue={String(Boolean(config.registration_dm_enabled))} name="value"><option value="true">Ativa</option><option value="false">Inativa</option></select><button className="button button-secondary compact" type="submit">Salvar</button></form>
        <form action={updateRegistrationGateConfiguration} className="setting-row"><div><strong>Canais adicionais de onboarding</strong><span>IDs separados por vírgula</span></div><input name="key" type="hidden" value="registration_onboarding_channel_ids" /><input name="valueType" type="hidden" value="id_list" /><input defaultValue={(config.registration_onboarding_channel_ids as number[] ?? []).join(",")} name="value" /><button className="button button-secondary compact" type="submit">Salvar</button></form>
        <form action={updateRegistrationGateConfiguration} className="setting-row"><div><strong>Cargos de bypass</strong><span>Alteração de alto privilégio</span></div><input name="key" type="hidden" value="registration_bypass_role_ids" /><input name="valueType" type="hidden" value="id_list" /><input defaultValue={(config.registration_bypass_role_ids as number[] ?? []).join(",")} name="value" /><button className="button button-danger compact" type="submit">Auditar e salvar</button></form>
        <form action={updateRegistrationGateConfiguration} className="setting-row"><div><strong>Contas de bypass</strong><span>Discord IDs separados por vírgula</span></div><input name="key" type="hidden" value="registration_bypass_user_ids" /><input name="valueType" type="hidden" value="id_list" /><input defaultValue={(config.registration_bypass_user_ids as number[] ?? []).join(",")} name="value" /><button className="button button-danger compact" type="submit">Auditar e salvar</button></form>
      </div>
    </section>

    <section className="command-section"><SectionHeader index="03" title="Integridade das permissões" meta={`${classificationCounts.ONBOARDING_VISIBLE?.length ?? 0} recursos de entrada • ${classificationCounts.MEMBER_ONLY?.length ?? 0} internos • ${classificationCounts.STAFF_ONLY?.length ?? 0} staff`} />
      <DataTable rows={data.findings} columns={[
        { key: "finding_type", label: "ACHADO", render: (row) => <Status value={row.finding_type} /> },
        { key: "resource_id", label: "RECURSO", render: (row) => <code>{String(row.resource_id ?? "—")}</code> },
        { key: "discord_id", label: "USUÁRIO", render: (row) => <code>{String(row.discord_id ?? "—")}</code> },
        { key: "created_at", label: "DETECTADO", render: (row) => dateTime(Number(row.created_at)) },
        { key: "evidence_json", label: "EVIDÊNCIA", render: (row) => <code className="truncate-code">{String(row.evidence_json)}</code> },
      ]} />
    </section>
  </>;
}
