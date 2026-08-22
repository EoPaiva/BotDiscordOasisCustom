import { PageHeader, SectionHeader } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";

type Row = Record<string, unknown>;

export default async function CareerPage() {
  const members = await commandCenterFetch<Row[]>("/v1/members?limit=250");
  return <>
    <PageHeader code="EF / 03" title="Gestão de carreira" description="A análise permanece humana; o sistema apresenta o quadro e executa decisões confirmadas." />
    <section className="command-section"><SectionHeader index="01" title="Quadro por patente" />
      <div className="rank-roster">{Object.entries(Object.groupBy(members, (row) => String(row.rank_name ?? "Sem patente"))).map(([rank, rows]) => <div key={rank}><span>{rank}</span><strong>{rows?.length ?? 0}</strong><p>{rows?.filter((row) => row.status === "ACTIVE").length ?? 0} ativos</p></div>)}</div>
    </section>
  </>;
}
