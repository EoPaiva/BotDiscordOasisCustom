import { Clock3, Network, ShieldCheck, UserRound } from "lucide-react";

import { MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { getAccessContext } from "@/lib/api";
import { dateTime } from "@/lib/format";

export default async function ProfilePage() {
  const context = await getAccessContext();
  const { member, access } = context;

  return <>
    <PageHeader
      code="ID / ME"
      title="Minha identidade funcional"
      description="Projeção oficial dos seus cargos Discord, patente e nível de acesso no sistema CHOQUE - BGR."
    />
    <MetricStrip items={[
      { label: "PATENTE", value: member.rank?.name ?? member.rank_name ?? "Sem patente" },
      { label: "CARGO PRINCIPAL", value: member.primary_position?.name ?? "Sem função principal" },
      { label: "PERFIL DE ACESSO", value: access.profile_name },
      { label: "ESTADO DISCORD", value: <Status value={member.identity_sync_status} /> },
    ]} />
    <div className="identity-profile-grid">
      <section className="command-section">
        <SectionHeader index="01" title="Identidade militar" meta={`Autorização v${access.authorization_version}`} />
        <dl className="identity-document">
          <div><dt><UserRound size={15} aria-hidden="true" /> Militar</dt><dd>{member.mta_nick}</dd></div>
          <div><dt><ShieldCheck size={15} aria-hidden="true" /> Patente</dt><dd>{member.rank?.name ?? member.rank_name ?? "Não definida"}</dd></div>
          <div><dt><Network size={15} aria-hidden="true" /> Cargo funcional</dt><dd>{member.primary_position?.name ?? "Não definido"}</dd></div>
          <div><dt><Clock3 size={15} aria-hidden="true" /> Último sync</dt><dd>{member.discord_synced_at ? dateTime(member.discord_synced_at) : "Aguardando primeira sincronização"}</dd></div>
        </dl>
      </section>
      <section className="command-section">
        <SectionHeader index="02" title="Funções adicionais" meta={`${member.functions.length} vínculo(s) secundário(s)`} />
        {member.functions.length ? (
          <div className="function-badges">
            {member.functions.map((position) => (
              <span key={position.code ?? `${position.id}:${position.name}`}>
                <strong>{position.name}</strong>
                {position.code && <code>{position.code}</code>}
              </span>
            ))}
          </div>
        ) : <p className="identity-empty">Nenhuma função secundária vinculada pelos cargos atuais.</p>}
      </section>
      <section className="command-section identity-access-card">
        <SectionHeader index="03" title="Estado de acesso" />
        <div className="identity-access-body">
          <Status value={member.discord_present ? member.identity_sync_status : "DISCORD_ABSENT"} />
          <h2>{access.profile_name}</h2>
          <p>O nível é recalculado no servidor a partir dos cargos funcionais mapeados por ID. Mudanças no Discord aparecem aqui automaticamente.</p>
          <div><span>Discord ID</span><code>{member.discord_id}</code></div>
          <div><span>Versão de autorização</span><code>v{access.authorization_version}</code></div>
        </div>
      </section>
    </div>
  </>;
}
