import { Check, ExternalLink, LockKeyhole, Radio, ShieldAlert } from "lucide-react";

const completedPhases = [
  "Base transacional, RBAC e cadastro",
  "Bate-ponto e tempo mínimo em patrulha",
  "Hierarquia, carreira e cursos",
  "Operações inteligentes e comandante de patrulha",
  "Portaria Digital e recrutamento íntegro",
  "Tickets privados com operação completa",
  "Centro de Comando Web e hardening",
  "Recrutamento público e análise privada",
  "Patrulhas ao vivo e qualificações bidirecionais",
];

const publicationChecks = [
  { label: "Runtime único na Discloud Diamond", state: "done" },
  { label: "Banco íntegro na migration V27", state: "done" },
  { label: "Gateway Discord, painéis e outbox", state: "done" },
  { label: "Patrulhas ao vivo confirmadas pela API", state: "done" },
  { label: "Domínio próprio do portal", state: "blocked" },
  { label: "Provider protegido do Robô Analista", state: "blocked" },
  { label: "Rotação de credenciais e menor privilégio", state: "blocked" },
];

export default function ProjectStatusPage() {
  return (
    <main className="status-page-shell">
      <section className="status-command-header">
        <div className="status-insignia" aria-hidden="true">CB</div>
        <div>
          <span className="eyebrow">RELATÓRIO OPERACIONAL · SITUAÇÃO DO PROJETO</span>
          <h1>CHOQUE <strong>— BGR</strong></h1>
          <p>Implantação do Sistema Integrado de Gestão</p>
        </div>
        <div className="status-live-badge"><Radio size={14} /> OPERAÇÃO ONLINE</div>
      </section>

      <section className="status-metrics" aria-label="Resumo da implantação">
        <article><span>RUNTIME</span><strong>ONLINE</strong><small>Discloud Diamond · instância única</small></article>
        <article><span>TESTES AUTOMATIZADOS</span><strong>307+</strong><small>Python, UI e integração</small></article>
        <article><span>BANCO OPERACIONAL</span><strong>V27</strong><small>SQLite íntegro e transacional</small></article>
        <article><span>GATEWAY</span><strong>ATIVO</strong><small>Bot e painéis conectados ao Discord</small></article>
      </section>

      <div className="status-grid">
        <section className="status-panel">
          <header><span>01</span><h2>Capacidades entregues</h2></header>
          <div className="status-completed-list">
            {completedPhases.map((phase) => (
              <div key={phase}><Check size={16} /><span>{phase}</span><code>OPERACIONAL</code></div>
            ))}
          </div>
        </section>

        <section className="status-panel">
          <header><span>02</span><h2>Publicação segura</h2></header>
          <div className="status-deployment-list">
            {publicationChecks.map((item) => (
              <div key={item.label}>
                {item.state === "done" ? <Check size={16} /> : item.state === "blocked" ? <ShieldAlert size={16} /> : <LockKeyhole size={16} />}
                <span>{item.label}</span>
                <code data-state={item.state}>{item.state === "done" ? "CONCLUÍDO" : item.state === "blocked" ? "AÇÃO EXTERNA" : "AGUARDANDO"}</code>
              </div>
            ))}
          </div>
          <aside className="status-security-note">
            <ShieldAlert size={22} />
            <div><strong>Pendências externas preservadas</strong><p>O núcleo está em produção. Domínio próprio, provider do Robô Analista e rotação de credenciais continuam registrados e dependem de decisão ou ação protegida do proprietário; nenhum deles bloqueia o bot atual.</p></div>
          </aside>
        </section>
      </div>

      <footer className="status-page-footer">
        <span>CHOQUE - BGR · SISTEMA DE GESTÃO</span>
        <a href="https://github.com/EoPaiva/choque-bgr-gestao" target="_blank" rel="noreferrer">Repositório privado <ExternalLink size={13} /></a>
        <time dateTime="2026-08-23">Atualizado em 23 AGO 2026</time>
      </footer>
    </main>
  );
}
