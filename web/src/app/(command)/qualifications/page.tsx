import { Check, Minus } from "lucide-react";

import { PageHeader, SectionHeader, Status } from "@/components/ui";
import { can } from "@/lib/access";
import { commandCenterFetch, getAccessContext } from "@/lib/api";

import { setMemberQualification } from "./actions";

type Course = { id: number; internal_code: string; name: string };
type MatrixMember = {
  member: {
    discord_id: string;
    mta_nick: string;
    rank_name?: string | null;
  };
  courses: Record<string, unknown>;
};

function qualificationNotice(value: unknown): string | null {
  if (value === "member-not-found") {
    return "Este militar não está mais cadastrado no efetivo. Atualize a matriz e reconcilie a identidade antes de alterar a qualificação.";
  }
  if (value === "course-not-found") {
    return "Este curso não está mais ativo. Atualize a matriz antes de tentar novamente.";
  }
  return null;
}

export default async function QualificationsPage({ searchParams }: PageProps<"/qualifications">) {
  const [data, context, query] = await Promise.all([
    commandCenterFetch<{ courses: Course[]; members: MatrixMember[] }>("/v1/qualifications"),
    getAccessContext(),
    searchParams,
  ]);
  const canManage = can(context, "qualification.manage");
  const notice = qualificationNotice(query.notice);
  return <>
    <PageHeader code="EF / 04" title="Matriz de qualificação" description={canManage ? "Clique em uma célula para conceder ou revogar o curso; o cargo correspondente será sincronizado no Discord." : "Cobertura de formação do efetivo por curso ativo."} />
    {notice && <section className="command-section" role="status"><div className="empty-state"><div><strong>Atualização necessária</strong><p>{notice}</p></div></div></section>}
    <section className="command-section"><SectionHeader index="01" title="Cobertura operacional" meta={`${data.courses.length} cursos ativos${canManage ? " · edição Alto Comando" : ""}`} />
      <div className="table-scroll"><table className="data-table qualification-table"><thead><tr><th>MEMBRO</th>{data.courses.map((course) => <th title={course.name} key={course.internal_code}>{course.internal_code}</th>)}</tr></thead><tbody>
        {data.members.map((entry) => <tr key={entry.member.discord_id}><td><strong>{entry.member.mta_nick}</strong><span>{String(entry.member.rank_name ?? "—")}</span></td>{data.courses.map((course) => {
          const granted = Boolean(entry.courses[course.internal_code]);
          return <td key={course.internal_code}>{canManage ? <form action={setMemberQualification}>
            <input name="discordId" type="hidden" value={entry.member.discord_id} />
            <input name="courseId" type="hidden" value={String(course.id)} />
            <input name="granted" type="hidden" value={String(!granted)} />
            <button className={granted ? "matrix-yes matrix-action" : "matrix-no matrix-action"} title={`${granted ? "Revogar" : "Conceder"} ${course.name} de ${entry.member.mta_nick}`} type="submit">
              {granted ? <Check size={16} /> : <Minus size={16} />}
            </button>
          </form> : granted ? <span className="matrix-yes" title="Qualificado"><Check size={16} /></span> : <span className="matrix-no" title="Não qualificado"><Minus size={16} /></span>}</td>;
        })}</tr>)}
      </tbody></table></div>
      {!data.members.length && <Status value="SEM REGISTROS" />}
    </section>
  </>;
}
