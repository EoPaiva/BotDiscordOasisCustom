import { InboxWorkspace, type InboxItem } from "@/components/inbox-workspace";
import { MetricStrip, PageHeader, SectionHeader } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { label } from "@/lib/format";

export default async function InboxPage() {
  const items = await commandCenterFetch<InboxItem[]>("/v1/inbox");
  const counts = Object.entries(Object.groupBy(items, (item) => item.type));
  return <>
    <PageHeader code="ADM / 01" title="Caixa de entrada administrativa" description="Processos reunidos por prioridade, origem e tempo de espera." />
    <MetricStrip items={[
      { label: "PENDÊNCIAS", value: items.length, tone: items.length ? "warning" : "success" },
      ...counts.slice(0, 5).map(([type, rows]) => ({ label: label(type), value: rows?.length ?? 0 })),
    ]} />
    <section className="command-section inbox-section"><SectionHeader index="01" title="Processos para decisão" meta="Toda decisão gera auditoria" /><InboxWorkspace items={items} /></section>
  </>;
}

