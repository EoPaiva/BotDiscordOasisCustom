import clsx from "clsx";
import { CircleAlert, Info, ShieldAlert, TriangleAlert } from "lucide-react";

export { LoadingState } from "./loading-state";

type CommandStateTone = "neutral" | "info" | "warning" | "danger";
type StatusTone = "neutral" | "success" | "warning" | "danger";

function inferStatusTone(text: string): StatusTone {
  const tokens = new Set(text.split(/[^A-Z0-9]+/).filter(Boolean));
  const hasAny = (values: string[]) => values.some((value) => tokens.has(value));

  if (hasAny(["ERROR", "FAILED", "FAILURE", "INVALID", "INVALIDATED", "UNAVAILABLE", "SUSPENDED", "DISMISSED", "DENIED", "REJECTED", "ATTENTION", "BLOCKED", "OFFLINE"])) return "danger";
  if (hasAny(["PENDING", "GRACE", "WAITING", "NEAR", "REVIEW", "FORMING", "SCHEDULED", "PAUSED", "MAINTENANCE", "DRAFT", "SUBMITTED"])) return "warning";
  if (hasAny(["ACTIVE", "ATIVO", "ATIVA", "VALID", "OPERATIONAL", "AVAILABLE", "APPROVED", "COMPLETED", "FULFILLED", "SYNCED", "ONLINE", "OPEN", "CURRENT", "RESOLVED", "SUCCESS"])) return "success";
  return "neutral";
}

export function CommandState({
  code,
  title,
  happened,
  next,
  reference,
  actions,
  tone = "neutral",
  className,
}: {
  code: string;
  title: string;
  happened: React.ReactNode;
  next: React.ReactNode;
  reference?: string;
  actions?: React.ReactNode;
  tone?: CommandStateTone;
  className?: string;
}) {
  const Icon = tone === "danger"
    ? ShieldAlert
    : tone === "warning"
      ? TriangleAlert
      : tone === "info"
        ? Info
        : CircleAlert;

  return (
    <section
      className={clsx("command-state", `command-state-${tone}`, className)}
      role={tone === "danger" ? "alert" : undefined}
    >
      <div className="command-state-index">
        <Icon aria-hidden="true" size={22} strokeWidth={1.7} />
        <span className="technical-index">{code}</span>
      </div>
      <h1>{title}</h1>
      <dl className="command-state-guidance">
        <div><dt>O que aconteceu</dt><dd>{happened}</dd></div>
        <div><dt>Próxima ação</dt><dd>{next}</dd></div>
      </dl>
      {reference && <code className="command-state-reference">Referência {reference}</code>}
      {actions && <div className="command-state-actions">{actions}</div>}
    </section>
  );
}

export function PageHeader({
  code,
  title,
  description,
  actions,
}: {
  code: string;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div><span className="technical-index">{code}</span><h1>{title}</h1>{description && <p>{description}</p>}</div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function SectionHeader({ index, title, meta }: { index: string; title: string; meta?: string }) {
  return (
    <header className="section-header">
      <span>{index}</span><h2>{title}</h2>{meta && <p>{meta}</p>}
    </header>
  );
}

export function Status({ value, tone }: { value: unknown; tone?: StatusTone }) {
  const text = String(value ?? "UNKNOWN").toUpperCase();
  return <span className={clsx("status-label", tone ?? inferStatusTone(text))}><i />{text.replaceAll("_", " ")}</span>;
}

export function StatusLabel({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: StatusTone;
}) {
  return <span className={clsx("status-label", tone)}><i />{label}</span>;
}

export function MetricStrip({ items }: { items: { label: string; value: React.ReactNode; tone?: string }[] }) {
  return (
    <dl className="metric-strip">
      {items.map((item) => (
        <div className={clsx("metric", item.tone)} key={item.label}>
          <dt><span>{item.label}</span></dt>
          <dd><strong>{item.value}</strong></dd>
        </div>
      ))}
    </dl>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state" role="status"><span aria-hidden="true">—</span><div><strong>{title}</strong><p>{detail}</p></div></div>;
}

export function DataTable({
  columns,
  rows,
  rowKey = "id",
  caption,
  emptyTitle = "Nenhum registro",
  emptyDetail = "Não há dados para os filtros atuais.",
}: {
  columns: { key: string; label: string; render?: (row: Record<string, unknown>) => React.ReactNode }[];
  rows: Record<string, unknown>[];
  rowKey?: string;
  caption: string;
  emptyTitle?: string;
  emptyDetail?: string;
}) {
  if (!rows.length) return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  return (
    <div aria-label={caption} className="table-scroll" role="region" tabIndex={0}>
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => (
          <tr key={String(row[rowKey] ?? index)}>
            {columns.map((column) => <td data-label={column.label} key={column.key}>{column.render ? column.render(row) : String(row[column.key] ?? "—")}</td>)}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
