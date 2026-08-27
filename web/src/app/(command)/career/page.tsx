import Link from "next/link";

import { DataTable, EmptyState, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, duration, label } from "@/lib/format";

type Row = Record<string, unknown>;
type CareerData = { generated_at: number; members: Row[]; movements: Row[]; officer_applications: Record<string, number> };

export default async function CareerPage() {
  const data = await commandCenterFetch<CareerData>("/v1/career");
  const members = data.members;
  const ranks = Object.entries(Object.groupBy(members, (row) => String(row.rank_name ?? "Sem patente")));
  const active = members.filter((row) => row.status === "ACTIVE").length;
  const attention = members.filter((row) => Number(row.active_warnings ?? 0) > 0 || ["SUSPENDED", "AWAY"].includes(String(row.status))).length;
  return <>
    <PageHeader code="EF / 03" title="Gestão de carreira" description="A análise permanece humana; o sistema apresenta o quadro e executa decisões confirmadas." />
    <MetricStrip items={[
      { label: "EFETIVO EM CARREIRA", value: members.length },
      { label: "ATIVOS", value: active, tone: "success" },
      { label: "EXIGEM ATENÇÃO", value: attention, tone: attention ? "warning" : undefined },
      { label: "MOVIMENTAÇÕES", value: data.movements.length },
      { label: "OFICIALATO NA FILA", value: (data.officer_applications.SUBMITTED ?? 0) + (data.officer_applications.IN_REVIEW ?? 0) + (data.officer_applications.INTERVIEW_REQUIRED ?? 0) },
    ]} />
    <section className="command-section"><SectionHeader index="01" title="Quadro por patente" meta={`${ranks.length} faixas ocupadas`} />
      {ranks.length ? <div className="rank-roster">{ranks.map(([rank, rows]) => <div key={rank}><span>{rank}</span><strong>{rows?.length ?? 0}</strong><p>{rows?.filter((row) => row.status === "ACTIVE").length ?? 0} ativos</p></div>)}</div> : <EmptyState title="Nenhum membro em carreira" detail="Cadastros aprovados com vínculo funcional aparecerão neste quadro." />}
    </section>
    <section className="command-section"><SectionHeader index="02" title="Efetivo e elegibilidade" meta="Abra o dossiê para revisar e confirmar uma movimentação" />
      {members.length ? <DataTable caption="Efetivo e elegibilidade" rows={members} rowKey="discord_id" columns={[
        { key: "mta_nick", label: "MILITAR", render: (row) => <Link className="member-link" href={`/members/${String(row.discord_id)}`}><strong>{String(row.rank_prefix ?? "")} {String(row.mta_nick)}</strong><code>ID {String(row.character_id ?? "—")}</code></Link> },
        { key: "rank_name", label: "PATENTE" },
        { key: "status", label: "STATUS", render: (row) => <Status value={row.status} /> },
        { key: "rank_since", label: "NA PATENTE DESDE", render: (row) => dateTime(Number(row.rank_since)) },
        { key: "valid_hours_ms", label: "HORAS VÁLIDAS", render: (row) => duration(Number(row.valid_hours_ms)) },
        { key: "progression_next_rank_name", label: "PRÓXIMO OBJETIVO", render: (row) => row.progression_next_rank_name ? <span><strong>{String(row.progression_next_rank_name)}</strong><br /><code>{duration(Number(row.valid_hours_ms))} / {duration(Number(row.progression_target_ms))}</code></span> : "Carreira humana" },
        { key: "merit_count", label: "MÉRITOS", render: (row) => <span>{String(row.merit_count)}<br /><code>+{String(row.positive_merit_weight)} / -{String(row.negative_merit_weight)}</code></span> },
        { key: "patrols", label: "PATRULHAS" },
        { key: "active_warnings", label: "ADVERTÊNCIAS", render: (row) => <Status value={Number(row.active_warnings) ? `${String(row.active_warnings)} ATIVA(S)` : "REGULAR"} /> },
        { key: "discord_id", label: "AÇÃO", render: (row) => <Link className="text-link inline" href={`/members/${String(row.discord_id)}`}>Analisar dossiê</Link> },
      ]} /> : <EmptyState title="Quadro funcional vazio" detail="Não existe membro cadastrado elegível para gestão de carreira." />}
    </section>
    <section className="command-section"><SectionHeader index="03" title="Movimentações recentes" meta={`${data.movements.length} registros`} />
      {data.movements.length ? <DataTable caption="Movimentações recentes" rows={data.movements} columns={[
        { key: "created_at", label: "DATA", render: (row) => dateTime(Number(row.created_at)) },
        { key: "mta_nick", label: "MILITAR", render: (row) => <Link className="member-link" href={`/members/${String(row.discord_id)}`}><strong>{String(row.mta_nick)}</strong><code>{String(row.discord_id)}</code></Link> },
        { key: "action_type", label: "MOVIMENTO", render: (row) => <strong>{label(row.action_type)}</strong> },
        { key: "from_rank_name", label: "ORIGEM" },
        { key: "to_rank_name", label: "DESTINO" },
        { key: "reason", label: "MOTIVO" },
      ]} /> : <EmptyState title="Nenhuma movimentação registrada" detail="O quadro está correto; promoções e rebaixamentos confirmados passarão a compor esta trilha." />}
    </section>
  </>;
}
