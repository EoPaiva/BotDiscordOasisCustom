import { Check, Minus } from "lucide-react";

import { PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";

type Course = { internal_code: string; name: string };
type MatrixMember = { member: Record<string, unknown>; courses: Record<string, unknown> };

export default async function QualificationsPage() {
  const data = await commandCenterFetch<{ courses: Course[]; members: MatrixMember[] }>("/v1/qualifications");
  return <>
    <PageHeader code="EF / 04" title="Matriz de qualificação" description="Cobertura de formação do efetivo por curso ativo." />
    <section className="command-section"><SectionHeader index="01" title="Cobertura operacional" meta={`${data.courses.length} cursos ativos`} />
      <div className="table-scroll"><table className="data-table qualification-table"><thead><tr><th>MEMBRO</th>{data.courses.map((course) => <th title={course.name} key={course.internal_code}>{course.internal_code}</th>)}</tr></thead><tbody>
        {data.members.map((entry) => <tr key={String(entry.member.discord_id)}><td><strong>{String(entry.member.mta_nick)}</strong><span>{String(entry.member.rank_name ?? "—")}</span></td>{data.courses.map((course) => <td key={course.internal_code}>{entry.courses[course.internal_code] ? <span className="matrix-yes" title="Qualificado"><Check size={16} /></span> : <span className="matrix-no" title="Não qualificado"><Minus size={16} /></span>}</td>)}</tr>)}
      </tbody></table></div>
      {!data.members.length && <Status value="SEM REGISTROS" />}
    </section>
  </>;
}

