"use client";

import { useActionState } from "react";

import {
  assignRecruitmentApplication,
  type RecruitmentActionState,
} from "./actions";

const INITIAL_STATE: RecruitmentActionState = {
  kind: "idle",
  message: "",
};

export function RecruitmentAssignmentForm({
  applicationId,
  expectedVersion,
}: {
  applicationId: number;
  expectedVersion: number;
}) {
  const [state, formAction, pending] = useActionState(
    assignRecruitmentApplication,
    INITIAL_STATE,
  );

  return (
    <form action={formAction} className="dossier-form">
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
      <button className="button button-secondary" disabled={pending} type="submit">
        {pending ? "Assumindo…" : "Assumir análise"}
      </button>
    </form>
  );
}
