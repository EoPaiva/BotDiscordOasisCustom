import { MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { duration, label } from "@/lib/format";

type Period = Record<string, unknown>;

export default async function ReportsPage() {
  const data = await commandCenterFetch<{ daily: Period; weekly: Period; monthly: Period; points: Record<string, number> }>("/v1/reports");
  const weeklyStatuses = (data.weekly.statuses ?? {}) as Record<string, number>;
  return <>
    <PageHeader code="INT / 02" title="Relatórios operacionais" description="Indicadores essenciais; gráficos somente quando agregarem leitura." />
    <MetricStrip items={[
      { label: "HORAS HOJE", value: duration(Number(data.daily.total_ms)) },
      { label: "HORAS NA SEMANA", value: duration(Number(data.weekly.total_ms)) },
      { label: "HORAS NO MÊS", value: duration(Number(data.monthly.total_ms)) },
      { label: "PONTOS ATIVOS", value: data.points.active ?? 0, tone: "success" },
      { label: "INVALIDADOS", value: data.points.invalidated ?? 0, tone: "danger" },
    ]} />
    <div className="dashboard-grid">
      <section className="command-section"><SectionHeader index="01" title="Cumprimento semanal" />
        <div className="compliance-bars">{Object.entries(weeklyStatuses).map(([key, value]) => {
          const total = Math.max(1, Object.values(weeklyStatuses).reduce((sum, item) => sum + item, 0));
          return <div key={key}><header><span>{label(key)}</span><strong>{value}</strong></header><progress aria-label={`${label(key)}: ${value}`} className="compliance-progress" max={total} value={value} /></div>;
        })}</div>
      </section>
      <section className="command-section"><SectionHeader index="02" title="Situação dos pontos" />
        <div className="status-register">{Object.entries(data.points).map(([key, value]) => <div key={key}><Status value={key} /><strong>{value}</strong></div>)}</div>
      </section>
    </div>
  </>;
}
