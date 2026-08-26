"use client";

import clsx from "clsx";
import Link from "next/link";
import { useId, useMemo, useState } from "react";

import { decideInboxItem } from "@/app/(command)/actions";
import { Status } from "@/components/ui";
import { dateTime, label } from "@/lib/format";

export type InboxItem = { type: string; id: number; data: Record<string, unknown> };

function visibleFields(data: Record<string, unknown>) {
  const hidden = new Set(["payload_json", "evidence_json", "guild_id", "member_id"]);
  return Object.entries(data).filter(([key, value]) => !hidden.has(key) && value != null).slice(0, 10);
}

function isoDateTime(value: unknown): string | undefined {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return undefined;
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

export function InboxWorkspace({ items }: { items: InboxItem[] }) {
  const [selectedId, setSelectedId] = useState(items[0] ? `${items[0].type}:${items[0].id}` : "");
  const selected = useMemo(
    () => items.find((item) => `${item.type}:${item.id}` === selectedId) ?? items[0],
    [items, selectedId],
  );
  const decisionPanelId = useId();
  const decisionTitleId = useId();
  if (!selected) return <div className="empty-state"><span>—</span><div><strong>Caixa regular</strong><p>Nenhuma decisão aguarda análise.</p></div></div>;
  return (
    <div className="inbox-workspace">
      <ul className="inbox-list" aria-label="Pendências administrativas">
        {items.map((item) => {
          const active = `${item.type}:${item.id}` === `${selected.type}:${selected.id}`;
          return <li key={`${item.type}:${item.id}`}>
            <button aria-controls={decisionPanelId} aria-current={active ? "true" : undefined} className={clsx(active && "active")} onClick={() => setSelectedId(`${item.type}:${item.id}`)}>
              <code>#{item.type.slice(0, 3)}-{String(item.id).padStart(4, "0")}</code>
              <strong>{label(item.type)}</strong>
              <span>{String(item.data.mta_nick ?? item.data.discord_id ?? "Solicitante")}</span>
              <footer><Status value={item.data.status ?? "PENDING"} /><time dateTime={isoDateTime(item.data.inbox_time)}>{dateTime(Number(item.data.inbox_time))}</time></footer>
            </button>
          </li>;
        })}
      </ul>
      <article aria-labelledby={decisionTitleId} className="decision-panel" id={decisionPanelId}>
        <header><div><span className="technical-index">PROCESSO / {selected.id}</span><h2 id={decisionTitleId}>{label(selected.type)}</h2></div><Status value={selected.data.status ?? "PENDING"} /></header>
        <dl className="decision-fields">{visibleFields(selected.data).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof value === "number" && /_at$/.test(key) ? dateTime(value) : String(value)}</dd></div>)}</dl>
        {selected.type === "RECRUITMENT_APPLICATION" ? <div className="decision-form"><p>A candidatura exige leitura do dossiê, integridade, entrevista e confirmação humana separada.</p><Link className="button button-primary" href={`/recruitment/${selected.id}`}>Abrir dossiê de recrutamento</Link></div> : <form action={decideInboxItem} className="decision-form">
          <input type="hidden" name="itemId" value={selected.id} /><input type="hidden" name="itemType" value={selected.type} />
          <label>Fundamentação da decisão<textarea name="reason" minLength={3} maxLength={500} required placeholder="Registre uma justificativa objetiva e auditável." /></label>
          <div className="decision-actions">
            <button className="button button-primary" name="decision" value="approve" type="submit">{selected.type === "SHIFT_REVIEW" ? "Confirmar encerramento" : "Aprovar"}</button>
            {selected.type !== "SHIFT_REVIEW" && <button className="button button-danger" name="decision" value="deny" type="submit">Negar / arquivar</button>}
          </div>
        </form>}
      </article>
    </div>
  );
}
