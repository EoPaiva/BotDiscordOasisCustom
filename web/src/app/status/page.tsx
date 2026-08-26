import { Check, ExternalLink, Radio, ShieldAlert } from "lucide-react";
import Image from "next/image";

type HealthState = {
  online: boolean;
  checkedAt: number;
};

const deliveredCapabilities = [
  "Cadastro, identidade e controle de acesso",
  "Bate-ponto, patrulhas e prontidão operacional",
  "Hierarquia, carreira, cursos e qualificações",
  "Portaria Digital e recrutamento íntegro",
  "Tickets privados e Mesa de Análise",
  "Centro de Comando Web com autenticação Discord",
  "Central Financeira, PIX local e honrarias",
  "Operação paralela do recrutamento no REC CHOQUE",
];

async function platformHealth(): Promise<HealthState> {
  const apiUrl = process.env.COMMAND_CENTER_API_URL?.replace(/\/$/, "");
  const checkedAt = Date.now();
  if (!apiUrl) return { online: false, checkedAt };
  try {
    const response = await fetch(`${apiUrl}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) return { online: false, checkedAt };
    const payload = await response.json() as { status?: string };
    return { online: payload.status === "ok", checkedAt };
  } catch {
    return { online: false, checkedAt };
  }
}

export default async function ProjectStatusPage() {
  const health = await platformHealth();
  const operationalLabel = health.online ? "OPERAÇÃO ONLINE" : "VERIFICAÇÃO INDISPONÍVEL";
  return (
    <main className="status-page-shell">
      <section className="status-command-header">
        <div className="status-insignia status-emblem" aria-hidden="true"><Image alt="" height={60} priority src="/choque-emblem.png" width={60} /></div>
        <div>
          <span className="eyebrow">RELATÓRIO OPERACIONAL · SITUAÇÃO DO SISTEMA</span>
          <h1>CHOQUE <strong>— BGR</strong></h1>
          <p>Estado factual do Sistema Integrado de Gestão</p>
        </div>
        <div className={`status-live-badge ${health.online ? "online" : "degraded"}`}><Radio size={14} /> {operationalLabel}</div>
      </section>

      <section className="status-metrics" aria-label="Resumo da operação">
        <article><span>PORTAL</span><strong>ONLINE</strong><small>Esta página respondeu normalmente</small></article>
        <article><span>API</span><strong>{health.online ? "ONLINE" : "SEM RESPOSTA"}</strong><small>Healthcheck direto, sem valor simulado</small></article>
        <article><span>DOMÍNIO</span><strong>ATIVO</strong><small>choquebgr.online</small></article>
        <article><span>ÚLTIMA VERIFICAÇÃO</span><strong>{new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "America/Sao_Paulo" }).format(new Date(health.checkedAt))}</strong><small>Atualizado ao abrir esta página</small></article>
      </section>

      <div className="status-grid">
        <section className="status-panel">
          <header><span>01</span><h2>Capacidades entregues</h2></header>
          <div className="status-completed-list">
            {deliveredCapabilities.map((capability) => (
              <div key={capability}><Check size={16} /><span>{capability}</span><code>ENTREGUE</code></div>
            ))}
          </div>
        </section>

        <section className="status-panel">
          <header><span>02</span><h2>Como interpretar</h2></header>
          <aside className="status-security-note">
            <ShieldAlert size={22} />
            <div><strong>Sem números demonstrativos</strong><p>Esta tela não inventa contagens de membros, testes, migrações ou disponibilidade do Discord. Quando uma fonte não responde, o sistema mostra a indisponibilidade em vez de preencher um valor fictício.</p></div>
          </aside>
          <aside className="status-security-note">
            <Radio size={22} />
            <div><strong>Comunicados operacionais</strong><p>Manutenções programadas, serviços temporariamente desativados e entregas concluídas continuam publicados no canal Atualizações do Bot.</p></div>
          </aside>
        </section>
      </div>

      <footer className="status-page-footer">
        <span>CHOQUE - BGR · SISTEMA DE GESTÃO</span>
        <a href="https://choquebgr.online/discord" target="_blank" rel="noreferrer">Servidor oficial <ExternalLink size={13} /></a>
        <time dateTime={new Date(health.checkedAt).toISOString()}>Verificado agora</time>
      </footer>
    </main>
  );
}
