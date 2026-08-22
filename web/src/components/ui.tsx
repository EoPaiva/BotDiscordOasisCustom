import clsx from "clsx";

export function PageHeader({
  code,
  title,
  description,
  actions,
}: {
  code: string;
  title: string;
  description?: string;
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

export function Status({ value }: { value: unknown }) {
  const text = String(value ?? "UNKNOWN").toUpperCase();
  const tone = /ACTIVE|ATIVO|VALID|OPERATIONAL|AVAILABLE|APPROVED|COMPLETED|FULFILLED|SYNCED/.test(text)
    ? "success"
    : /PENDING|GRACE|WAITING|NEAR|REVIEW|FORMING|SCHEDULED/.test(text)
      ? "warning"
      : /ERROR|FAILED|INVALID|SUSPENDED|DISMISSED|DENIED|REJECTED|NEEDS_ATTENTION/.test(text)
        ? "danger"
        : "neutral";
  return <span className={clsx("status-label", tone)}><i />{text.replaceAll("_", " ")}</span>;
}

export function StatusLabel({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  return <span className={clsx("status-label", tone)}><i />{label}</span>;
}

export function MetricStrip({ items }: { items: { label: string; value: React.ReactNode; tone?: string }[] }) {
  return (
    <div className="metric-strip">
      {items.map((item) => <div className={clsx("metric", item.tone)} key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>)}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><span>—</span><div><strong>{title}</strong><p>{detail}</p></div></div>;
}

export function DataTable({
  columns,
  rows,
  rowKey = "id",
}: {
  columns: { key: string; label: string; render?: (row: Record<string, unknown>) => React.ReactNode }[];
  rows: Record<string, unknown>[];
  rowKey?: string;
}) {
  if (!rows.length) return <EmptyState title="Nenhum registro" detail="Não há dados para os filtros atuais." />;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => (
          <tr key={String(row[rowKey] ?? index)}>
            {columns.map((column) => <td data-label={column.label} key={column.key}>{column.render ? column.render(row) : String(row[column.key] ?? "—")}</td>)}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
