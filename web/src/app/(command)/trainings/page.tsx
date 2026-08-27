import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, duration } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function TrainingsPage() {
  const data = await commandCenterFetch<{ catalog: Row[]; active: Row[]; history: Row[] }>("/v1/trainings");
  return <>
    <PageHeader code="EF / 05" title="Cursos e treinamentos" description="Catálogo institucional, requisitos, inscrições e histórico de turmas." />
    <MetricStrip items={[
      { label: "CURSOS ATIVOS", value: data.catalog.filter((row) => row.active).length },
      { label: "TURMAS EM ANDAMENTO", value: data.active.length, tone: "success" },
      { label: "HISTÓRICO", value: data.history.length },
    ]} />
    <div className="dashboard-grid">
      <section className="command-section"><SectionHeader index="01" title="Catálogo" />
        <div className="course-register">{data.catalog.map((course) => <article key={String(course.id)}><header><code>{String(course.internal_code)}</code><Status value={course.enrollment_status} /></header><h3>{String(course.name)}</h3><dl><div><dt>Patente mínima</dt><dd>{String(course.minimum_rank_level ?? "—")}</dd></div><div><dt>Horas mínimas</dt><dd>{duration(Number(course.minimum_valid_hours_ms))}</dd></div><div><dt>Tempo de casa</dt><dd>{String(course.minimum_tenure_days ?? 0)} dias</dd></div><div><dt>Pré-requisito</dt><dd>{String(course.prerequisite_course_name ?? "Nenhum")}</dd></div></dl></article>)}</div>
      </section>
      <section className="command-section"><SectionHeader index="02" title="Próximos treinamentos" />
        <DataTable caption="Próximos treinamentos" rows={data.active} columns={[
          { key: "name", label: "TREINAMENTO", render: (row) => <strong>{String(row.name)}</strong> },
          { key: "scheduled_at", label: "DATA", render: (row) => dateTime(Number(row.scheduled_at)) },
          { key: "status", label: "STATUS", render: (row) => <Status value={row.status} /> },
          { key: "capacity", label: "VAGAS" },
        ]} />
      </section>
    </div>
  </>;
}
