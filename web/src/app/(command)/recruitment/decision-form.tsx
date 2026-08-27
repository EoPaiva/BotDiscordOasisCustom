"use client";

import { useActionState } from "react";

import {
  decideRecruitmentApplication,
  type RecruitmentActionState,
} from "./actions";

const INITIAL_STATE: RecruitmentActionState = {
  kind: "idle",
  message: "",
};

export function RecruitmentDecisionForm({
  applicationId,
  expectedVersion,
}: {
  applicationId: number;
  expectedVersion: number;
}) {
  const [state, formAction, pending] = useActionState(
    decideRecruitmentApplication,
    INITIAL_STATE,
  );

  return (
    <form action={formAction} className="dossier-form decision-form">
      <input name="applicationId" type="hidden" value={String(applicationId)} />
      <input name="expectedVersion" type="hidden" value={String(expectedVersion)} />
      {state.message && (
        <p
          aria-live="polite"
          className="candidate-notice"
          role={state.kind === "error" ? "alert" : "status"}
        >
          {state.message}
          {state.reference ? ` Referência ${state.reference}.` : ""}
        </p>
      )}
      <label>
        Motivo interno
        <textarea maxLength={2000} minLength={3} name="internalReason" required rows={3} />
      </label>
      <label>
        Mensagem ao candidato
        <textarea maxLength={2000} minLength={3} name="candidateMessage" required rows={3} />
      </label>
      <label>
        Confirmação
        <input name="confirmation" placeholder="Digite CONFIRMAR" required />
      </label>
      <div>
        <button
          aria-busy={pending}
          className="button button-primary"
          disabled={pending}
          name="decision"
          type="submit"
          value="approve"
        >
          {pending ? "Processando…" : "Aprovar"}
        </button>
        <button
          aria-busy={pending}
          className="button button-danger"
          disabled={pending}
          name="decision"
          type="submit"
          value="reject"
        >
          {pending ? "Processando…" : "Reprovar"}
        </button>
      </div>
    </form>
  );
}
