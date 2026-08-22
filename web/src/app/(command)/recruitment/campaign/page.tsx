import { PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";

import { updateRecruitmentCampaign } from "../actions";

type Row = Record<string, unknown>;

export default async function RecruitmentCampaignPage() {
  const [campaign, resources] = await Promise.all([
    commandCenterFetch<Row>("/v1/admin/recruitment/campaign"),
    commandCenterFetch<{ ranks: Row[]; roles: Row[]; voice_channels: Row[] }>("/v1/admin/recruitment/resources"),
  ]);
  const local = (value: unknown) => value ? new Date(Number(value)).toISOString().slice(0,16) : "";
  return <>
    <PageHeader code="REC / 02" title="Processo seletivo" description="Janela de ingresso, critérios mínimos e destinos Discord por registry." />
    <section className="command-section"><SectionHeader index="01" title="Campanha atual" meta="Alterações auditadas" /><div className="campaign-admin-state"><StatusLabel label={String(campaign.status)} tone={campaign.status === "OPEN" ? "success" : "warning"} /><strong>{String(campaign.name)}</strong><code>{String(campaign.public_id)}</code></div><form action={updateRecruitmentCampaign} className="campaign-form"><input name="campaignId" type="hidden" value={String(campaign.id)} /><label>Nome<input defaultValue={String(campaign.name)} name="name" required /></label><label>Status<select defaultValue={String(campaign.status)} name="status">{["DRAFT","SCHEDULED","OPEN","PAUSED","CLOSED","ARCHIVED"].map((status) => <option key={status}>{status}</option>)}</select></label><label>Abertura<input defaultValue={local(campaign.opens_at)} name="opensAt" type="datetime-local" /></label><label>Encerramento<input defaultValue={local(campaign.closes_at)} name="closesAt" type="datetime-local" /></label><label>Idade mínima<input defaultValue={String(campaign.minimum_age)} min={13} name="minimumAge" type="number" /></label><label>Cooldown em dias<input defaultValue={String(campaign.cooldown_days)} min={0} name="cooldownDays" type="number" /></label><label>Limite de candidaturas<input defaultValue={String(campaign.maximum_applications ?? "")} min={1} name="maximumApplications" type="number" /></label><label>Patente inicial<select defaultValue={String(campaign.initial_rank_id ?? "")} name="initialRankId"><option value="">Selecione</option>{resources.ranks.map((rank) => <option key={String(rank.id)} value={String(rank.id)}>{String(rank.name)}</option>)}</select></label><label>Cargo temporário<select defaultValue={String(campaign.candidate_role_id ?? "")} name="candidateRoleId"><option value="">Sem cargo</option>{resources.roles.map((role) => <option key={String(role.resource_id)} value={String(role.resource_id)}>{String(role.name)}</option>)}</select></label><label>Call de entrevista<select defaultValue={String(campaign.interview_channel_id ?? "")} name="interviewChannelId"><option value="">Sem call</option>{resources.voice_channels.map((channel) => <option key={String(channel.resource_id)} value={String(channel.resource_id)}>{String(channel.name)}</option>)}</select></label><button className="button button-primary" type="submit">Salvar processo seletivo</button></form></section>
  </>;
}
