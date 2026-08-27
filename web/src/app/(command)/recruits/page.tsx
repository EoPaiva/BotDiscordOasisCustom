import Link from "next/link";

import { DataTable, EmptyState, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { duration } from "@/lib/format";

type Recruit = {
  member: Record<string, unknown>;
  days_in_corporation: number;
  valid_hours_ms: number;
  patrols: number;
  evaluations: number;
  missing_courses: string[];
  requirements: Record<string, boolean>;
  eligible_for_effective_review: boolean;
};

export default async function RecruitsPage() {
  const recruits = await commandCenterFetch<Recruit[]>("/v1/recruits");
  const rows = recruits.map((item) => ({ ...item, ...item.member }));
  return <>
    <PageHeader code="EF / 02" title="Acompanhamento de recrutas" description="Evolução mensurável sem aprovação automática." />
    <MetricStrip items={[
      { label: "EM FORMAÇÃO", value: recruits.length },
      { label: "APTOS PARA ANÁLISE", value: recruits.filter((item) => item.eligible_for_effective_review).length, tone: "success" },
      { label: "PENDENTES", value: recruits.filter((item) => !item.eligible_for_effective_review).length, tone: "warning" },
    ]} />
    <section className="command-section"><SectionHeader index="01" title="Quadro de formação" meta={recruits.length ? "Selecione um recruta para abrir o dossiê" : "Leitura direta do efetivo cadastrado"} />
      {rows.length ? <DataTable caption="Quadro de formação" rows={rows} rowKey="discord_id" columns={[
        { key: "mta_nick", label: "RECRUTA", render: (row) => <Link className="member-link" href={`/members/${String(row.discord_id)}`}><strong>{String(row.mta_nick)}</strong><code>{String(row.discord_id)}</code></Link> },
        { key: "days_in_corporation", label: "DIAS" },
        { key: "valid_hours_ms", label: "HORAS", render: (row) => duration(Number(row.valid_hours_ms)) },
        { key: "patrols", label: "PATRULHAS" },
        { key: "evaluations", label: "AVALIAÇÕES" },
        { key: "requirements", label: "REQUISITOS", render: (row) => {
          const requirements = row.requirements as Record<string, boolean>;
          const passed = Object.values(requirements).filter(Boolean).length;
          return <span>{passed}/{Object.keys(requirements).length} atendidos</span>;
        } },
        { key: "eligible_for_effective_review", label: "SITUAÇÃO", render: (row) => <Status value={row.eligible_for_effective_review ? "APTO PARA ANÁLISE" : "EM FORMAÇÃO"} /> },
        { key: "discord_id", label: "AÇÃO", render: (row) => <Link className="text-link inline" href={`/members/${String(row.discord_id)}`}>Abrir dossiê</Link> },
      ]} /> : <EmptyState title="Nenhum recruta em formação" detail="O painel acompanha somente membros cadastrados cuja patente atual é Recruta. Novos aprovados aparecerão aqui depois da sincronização do cargo." />}
      <div className="section-actions"><Link className="text-link" href="/recruitment">Abrir processos de recrutamento</Link><Link className="text-link" href="/members">Conferir efetivo cadastrado</Link></div>
    </section>
  </>;
}
