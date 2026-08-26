import { Ban, ShieldOff } from "lucide-react";

import { PageHeader, SectionHeader, StatusLabel } from "@/components/ui";
import { recruitmentAdminFetch } from "@/lib/api";

import { createRecruitmentBlock, revokeRecruitmentBlock } from "../actions";

type Block = Record<string, unknown>;

export default async function RecruitmentBlocksPage() {
  const blocks = await recruitmentAdminFetch<Block[]>("/v1/admin/recruitment/blocks");
  return <>
    <PageHeader code="REC / 04" title="Bloqueios administrativos" description="Impedimentos explícitos, justificados e integralmente auditados." />
    <section className="command-section"><SectionHeader index="01" title="Registrar bloqueio" meta="Discord ID ou ID BGR" /><form action={createRecruitmentBlock} className="campaign-form"><label>Discord ID<input inputMode="numeric" name="discordId" /></label><label>ID BGR<input name="bgrId" /></label><label className="wide">Justificativa<textarea name="reason" required rows={3} /></label><button className="button button-danger" type="submit"><Ban size={14} /> Bloquear candidatura</button></form></section>
    <section className="command-section"><SectionHeader index="02" title="Histórico de bloqueios" meta="Revogação preserva o registro" /><div className="table-scroll"><table className="data-table"><thead><tr><th>Identificador</th><th>Motivo</th><th>Registro</th><th>Status</th><th>Ação</th></tr></thead><tbody>{blocks.map((block) => <tr key={String(block.id)}><td data-label="IDENTIFICADOR">{block.discord_id ? <code>Discord {String(block.discord_id)}</code> : <code>BGR {String(block.bgr_id)}</code>}</td><td data-label="MOTIVO">{String(block.reason)}</td><td data-label="REGISTRO">{new Date(Number(block.created_at)).toLocaleString("pt-BR")}</td><td data-label="STATUS"><StatusLabel label={block.active ? "ATIVO" : "REVOGADO"} tone={block.active ? "danger" : "success"} /></td><td data-label="AÇÃO">{Boolean(block.active) && <form action={revokeRecruitmentBlock}><input name="blockId" type="hidden" value={String(block.id)} /><button className="button button-secondary compact" type="submit"><ShieldOff size={13} /> Revogar</button></form>}</td></tr>)}</tbody></table></div></section>
  </>;
}
