import { Check, ExternalLink, LockKeyhole, Radio, ShieldAlert } from "lucide-react";

const completedPhases = [
  "Base transacional, RBAC e cadastro",
  "Bate-ponto e tempo mínimo em patrulha",
  "Hierarquia, carreira, cursos e medalhas",
  "Operações inteligentes e comandante de patrulha",
  "Portaria Digital e recrutamento íntegro",
  "Tickets privados com operação completa",
  "Centro de Comando Web e hardening",
];

const publicationChecks = [
  { label: "Código privado publicado sem histórico legado", state: "done" },
  { label: "Scanner de segredos e dependências", state: "done" },
  { label: "Runtime Railway unificado para SQLite", state: "done" },
  { label: "Publicação da migration V23 na Railway", state: "blocked" },
  { label: "Reconciliação Discord, identidade e RBAC", state: "pending" },
  { label: "Rotação de credenciais e permissões mínimas", state: "blocked" },
  { label: "Login Discord em validação final", state: "pending" },
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
        <div className="status-live-badge"><Radio size={14} /> MANUTENÇÃO DE DEPLOY</div>
      </section>

      <section className="status-metrics" aria-label="Resumo da implantação">
        <article><span>FASES CONCLUÍDAS</span><strong>21 / 24</strong><small>Fase 19 em validação final</small></article>
        <article><span>TESTES AUTOMATIZADOS</span><strong>300+</strong><small>Python, UI e integração</small></article>
        <article><span>MIGRATION PREPARADA</span><strong>V23</strong><small>Produção preservada em V22</small></article>
        <article className="warning"><span>RUNTIME</span><strong>PAUSADO</strong><small>Railway bloqueou deploy no horário de pico</small></article>
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
            <div><strong>Publicação temporariamente retida</strong><p>O código e a migration V23 passaram nos testes, mas o plano Railway recusou novos deployments durante a janela de pico. Serviço, volume e backup permanecem preservados; o bot está offline até a retomada segura.</p></div>
          </aside>
        </section>
      </div>

      <footer className="status-page-footer">
        <span>CHOQUE - BGR · SISTEMA DE GESTÃO</span>
        <a href="https://github.com/EoPaiva/choque-bgr-gestao" target="_blank" rel="noreferrer">Repositório privado <ExternalLink size={13} /></a>
        <time dateTime="2026-08-22">Atualizado em 22 AGO 2026</time>
      </footer>
    </main>
  );
}
