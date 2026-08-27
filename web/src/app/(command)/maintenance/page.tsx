import { PageHeader, SectionHeader, Status } from "@/components/ui";
import { commandCenterFetch } from "@/lib/api";
import { dateTime, isoDateTime } from "@/lib/format";

import { setMaintenance } from "../actions";

type Row = Record<string, unknown>;

const modules = ["POINT", "PATROLS", "TRAINING", "RECRUITMENT", "REGISTRATION", "REQUESTS", "CAREER", "DISCIPLINE", "ACTIVITY", "TICKETS"];

export default async function MaintenancePage() {
  const data = await commandCenterFetch<{ maintenance: Row[] }>("/v1/settings");
  const byModule = Object.fromEntries(data.maintenance.map((row) => [String(row.module_key), row]));
  return <>
    <PageHeader code="SYS / 02" title="Controle de módulos" description="Isolamento operacional com motivo, autoria e auditoria." />
    <section className="command-section"><SectionHeader index="01" title="Estado dos módulos" />
      <div className="module-register">{modules.map((moduleKey) => {
        const state = byModule[moduleKey]; const active = Boolean(state?.active);
        return <article key={moduleKey}><header><div><code>{moduleKey}</code><h3>{moduleKey.replaceAll("_", " ")}</h3></div><Status value={active ? "MAINTENANCE" : "OPERATIONAL"} /></header>{active && <dl><div><dt>Motivo</dt><dd>{String(state.reason ?? "Ajustes internos")}</dd></div><div><dt>Desde</dt><dd><time dateTime={isoDateTime(state.enabled_at)}>{dateTime(Number(state.enabled_at))}</time></dd></div></dl>}<form action={setMaintenance}><input type="hidden" name="moduleKey" value={moduleKey} /><input type="hidden" name="active" value={String(!active)} />{!active && <label>Motivo<input name="reason" minLength={3} required placeholder="Motivo da manutenção" /></label>}<button className={`button ${active ? "button-primary" : "button-danger"}`} type="submit">{active ? "Retornar à operação" : "Ativar manutenção"}</button></form></article>;
      })}</div>
    </section>
  </>;
}
