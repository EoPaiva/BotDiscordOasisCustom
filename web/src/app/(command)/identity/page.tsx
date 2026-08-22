import { DataTable, MetricStrip, PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, label } from "@/lib/format";

type Row = Record<string, unknown>;

export default async function IdentityPage() {
  const data = await commandCenterFetch<{ summary: Row[]; findings: Row[] }>("/v1/integrity");
  const safe = data.findings.filter((row) => row.fix_class === "AUTO_FIX_SAFE").length;
  const review = data.findings.filter((row) => row.fix_class === "REQUIRES_REVIEW").length;
  return <>
    <PageHeader code="INT / 04" title="Integridade de identidade" description="Divergências entre cadastro, patente, cargo e nickname; nenhuma correção sensível é automática." />
    <MetricStrip items={[
      { label: "ACHADOS ABERTOS", value: data.findings.length, tone: data.findings.length ? "warning" : "success" },
      { label: "CORREÇÕES SEGURAS", value: safe },
      { label: "EXIGEM REVISÃO", value: review, tone: review ? "danger" : undefined },
    ]} />
    <section className="command-section"><SectionHeader index="01" title="Achados para análise" />
      <DataTable rows={data.findings} columns={[
        { key: "id", label: "ACHADO", render: (row) => <code>INT-{String(row.id).padStart(4, "0")}</code> },
        { key: "mta_nick", label: "MEMBRO" },
        { key: "finding_type", label: "TIPO", render: (row) => label(row.finding_type) },
        { key: "fix_class", label: "TRATAMENTO", render: (row) => <Status value={row.fix_class} /> },
        { key: "detected_at", label: "DETECTADO", render: (row) => dateTime(Number(row.detected_at)) },
      ]} />
    </section>
  </>;
}

