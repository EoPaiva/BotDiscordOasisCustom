import Link from "next/link";

import { DataTable, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { label } from "@/lib/format";

import {
  configureVoiceChannel,
  updateChannelSetting,
  updateGeneralSetting,
  updateRankSetting,
} from "../actions";

type Row = Record<string, unknown>;
type SettingsData = {
  general: { setting_key: string; value: unknown; source: string }[];
  ranks: Row[];
  voice_channels: Row[];
  patrol_channels: Row[];
  panels: Row[];
  maintenance: Row[];
  discord_resources: Row[];
};

const editableGeneral = [
  "timezone", "grace_period_seconds", "minimum_patrol_minutes", "minimum_patrol_members",
  "patrol_continue_until_empty", "weekly_goal_minutes", "weekly_near_threshold_percent",
  "low_activity_days", "no_activity_days", "auto_remove_old_rank_roles",
  "enforce_member_nickname", "missing_rank_role_policy", "promotion_min_rank_days",
  "promotion_min_valid_hours", "promotion_required_courses", "recruit_min_days",
  "recruit_min_valid_hours", "recruit_min_patrols", "recruit_min_evaluations",
  "recruit_required_courses",
  "recruitment_public_url", "recruitment_stale_warning_hours",
];

const channelKeys = [
  "audit_channel_id", "registration_approval_channel_id", "registration_history_channel_id",
  "registration_panel_channel_id", "point_panel_channel_id", "service_panel_channel_id",
  "hierarchy_channel_id", "config_panel_channel_id", "personnel_admin_channel_id",
  "absence_panel_channel_id", "requests_panel_channel_id", "career_panel_channel_id",
  "discipline_panel_channel_id", "training_panel_channel_id", "activity_panel_channel_id",
  "recruitment_panel_channel_id", "recruitment_queue_channel_id",
  "recruitment_notification_channel_id", "recruitment_approved_channel_id",
  "recruitment_rejected_channel_id", "ticket_panel_channel_id",
];

function typeOf(value: unknown): "string" | "number" | "boolean" | "list" {
  if (Array.isArray(value)) return "list";
  if (typeof value === "number") return "number";
  if (typeof value === "boolean") return "boolean";
  return "string";
}

function printable(value: unknown): string {
  return Array.isArray(value) ? value.join(", ") : String(value ?? "");
}

export default async function SettingsPage() {
  const data = await commandCenterFetch<SettingsData>("/v1/settings");
  const byKey = Object.fromEntries(data.general.map((item) => [item.setting_key, item.value]));
  const textChannels = data.discord_resources.filter((row) => row.resource_type === "TEXT_CHANNEL");
  const roles = data.discord_resources.filter((row) => row.resource_type === "ROLE");
  const voiceResources = data.discord_resources.filter((row) => row.resource_type === "VOICE_CHANNEL");
  return <>
    <PageHeader
      code="SYS / 01"
      title="Configurações"
      description="Parâmetros por registry de IDs. Nomes visuais nunca são usados como identificadores."
      actions={<Link className="button button-secondary" href="/identity/discord">Mapeamento Discord</Link>}
    />
    <section className="command-section settings-section"><SectionHeader index="01" title="Regras operacionais" meta="Valores padrão e persistidos" />
      <div className="settings-grid">{editableGeneral.map((key) => {
        const value = byKey[key]; const valueType = typeOf(value);
        return <form action={updateGeneralSetting} className="setting-row" key={key}><div><strong>{label(key)}</strong><span>{data.general.find((item) => item.setting_key === key)?.source}</span></div><input type="hidden" name="key" value={key} /><input type="hidden" name="valueType" value={valueType} />
          {valueType === "boolean" ? <select name="value" defaultValue={String(value)}><option value="true">Ativo</option><option value="false">Inativo</option></select> : <input name="value" defaultValue={printable(value)} type={valueType === "number" ? "number" : "text"} />}
          <button className="button button-secondary compact" type="submit">Salvar</button></form>;
      })}</div>
    </section>
    <section className="command-section settings-section"><SectionHeader index="02" title="Canais e painéis" meta={`${textChannels.length} canais sincronizados do Discord`} />
      <div className="settings-grid">{channelKeys.map((key) => <form action={updateChannelSetting} className="setting-row" key={key}><div><strong>{label(key)}</strong><span>Registry Discord</span></div><input type="hidden" name="key" value={key} /><select name="resourceId" defaultValue={String(byKey[key] ?? "")} required><option value="" disabled>Selecione um canal</option>{textChannels.map((channel) => <option key={String(channel.resource_id)} value={String(channel.resource_id)}>{String(channel.name)}</option>)}</select><button className="button button-secondary compact" type="submit">Vincular</button></form>)}</div>
    </section>
    <section className="command-section settings-section"><SectionHeader index="03" title="Patentes e RBAC" meta={`${data.ranks.length} níveis cadastrados`} />
      <div className="rank-settings">{data.ranks.map((rank) => <form action={updateRankSetting} className="rank-setting-row" key={String(rank.id)}><code>{String(rank.level).padStart(2, "0")}</code><input type="hidden" name="rankId" value={String(rank.id)} /><label>Patente<input name="name" defaultValue={String(rank.name)} required /></label><label>Sigla<input name="prefix" defaultValue={String(rank.prefix ?? "")} /></label><label>Nível<input name="level" type="number" defaultValue={String(rank.level)} required /></label><label>Cargo Discord<select name="discordRoleId" defaultValue={String(rank.discord_role_id ?? "")}><option value="">Sem vínculo</option>{roles.map((role) => <option value={String(role.resource_id)} key={String(role.resource_id)}>{String(role.name)}</option>)}</select></label><label>Perfil<select name="rbacProfile" defaultValue={String(rank.rbac_profile)}>{["CANDIDATO", "RECRUTA", "MEMBRO", "GRADUADO", "INSTRUTOR", "SUPERVISOR", "COMANDO", "ALTO_COMANDO", "ADMINISTRADOR"].map((profile) => <option key={profile}>{profile}</option>)}</select></label><input type="hidden" name="active" value={String(Boolean(rank.active))} /><button className="button button-secondary compact" type="submit">Atualizar</button></form>)}</div>
    </section>
    <section className="command-section settings-section"><SectionHeader index="04" title="Calls autorizadas" meta={`${voiceResources.length} calls disponíveis no snapshot`} />
      <form action={configureVoiceChannel} className="inline-config-form">
        <input name="operation" type="hidden" value="upsert" />
        <label>Call<select name="channelId" required><option value="">Selecione por ID</option>{voiceResources.map((channel) => <option key={String(channel.resource_id)} value={String(channel.resource_id)}>{String(channel.name)}</option>)}</select></label>
        <label>Label opcional<input name="label" placeholder="Usa o nome atual se vazio" /></label>
        <label>Conta para patrulha<select name="countsTowardPatrol" defaultValue="true"><option value="true">Sim</option><option value="false">Não</option></select></label>
        <button className="button button-primary" type="submit">Autorizar call</button>
      </form>
      <DataTable caption="Canais de voz configurados" rows={data.voice_channels} rowKey="channel_id" columns={[
        { key: "channel_id", label: "ID", render: (row) => <code>{String(row.channel_id)}</code> },
        { key: "label", label: "CALL" },
        { key: "service_allowed", label: "SERVIÇO", render: (row) => <Status value={row.service_allowed ? "ALLOWED" : "BLOCKED"} /> },
        { key: "counts_toward_patrol_minimum", label: "CONTA PATRULHA", render: (row) => <Status value={row.counts_toward_patrol_minimum ? "VALID" : "NO"} /> },
        { key: "action", label: "AÇÃO", render: (row) => <form action={configureVoiceChannel}><input name="operation" type="hidden" value="remove" /><input name="channelId" type="hidden" value={String(row.channel_id)} /><input name="countsTowardPatrol" type="hidden" value="true" /><button className="button button-danger compact" type="submit">Remover</button></form> },
      ]} />
    </section>
  </>;
}
