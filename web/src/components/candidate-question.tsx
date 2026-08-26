"use client";

import clsx from "clsx";
import { Check, Clock3, LockKeyhole, Save, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import {
  type CandidateQuestionPayload,
  recordRecruitmentIntegrity,
  saveRecruitmentAnswer,
  startRecruitmentQuestion,
  submitRecruitmentApplication,
} from "@/app/recrutamento/actions";

export type ReadyQuestion = {
  complete: boolean;
  id?: number;
  ordinal?: number;
  total?: number;
  status?: string;
  security_level?: string;
  time_seconds?: number;
  question?: CandidateQuestionPayload["question"];
  started_at?: number;
  expires_at?: number | null;
  draft?: unknown;
  question_token?: string;
  application_version?: number;
};

function initialAnswer(payload: CandidateQuestionPayload | null): string | boolean | string[] {
  const value = payload?.draft;
  if (typeof value === "boolean" || typeof value === "string") return value;
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
  return "";
}

function payloadFromReady(ready: ReadyQuestion): CandidateQuestionPayload | null {
  if (!ready.question) return null;
  return {
    question: ready.question,
    started_at: ready.started_at!,
    expires_at: ready.expires_at ?? null,
    draft: ready.draft,
    question_token: ready.question_token!,
  };
}

function readyIdentity(ready: ReadyQuestion): string {
  if (ready.complete) return `complete:${ready.application_version ?? "current"}`;
  return [ready.id ?? "unknown", ready.status ?? "unknown", ready.started_at ?? "waiting"].join(":");
}

export function CandidateQuestion({
  applicationId,
  protocol,
  ready,
}: {
  applicationId: number;
  protocol: string;
  ready: ReadyQuestion;
}) {
  const router = useRouter();
  const initialPayload = payloadFromReady(ready);
  const [payload, setPayload] = useState<CandidateQuestionPayload | null>(initialPayload);
  const [answer, setAnswer] = useState<string | boolean | string[]>(initialAnswer(initialPayload));
  const [remaining, setRemaining] = useState<number | null>(null);
  const [notice, setNotice] = useState<string>("");
  const [advancing, setAdvancing] = useState(false);
  const [pending, startTransition] = useTransition();
  const savedRef = useRef<string>(JSON.stringify(initialAnswer(initialPayload)));
  const blurStarted = useRef<number | null>(null);
  const readyIdentityRef = useRef(readyIdentity(ready));
  const timeoutSubmissionRef = useRef<number | null>(null);
  const clipboardRestricted = Boolean(
    payload
    && payload.question.security_level !== "NORMAL"
    && !payload.question.clipboard_adapted
  );

  useEffect(() => {
    const nextIdentity = readyIdentity(ready);
    if (nextIdentity === readyIdentityRef.current) return;
    readyIdentityRef.current = nextIdentity;
    const nextPayload = payloadFromReady(ready);
    const nextAnswer = initialAnswer(nextPayload);
    setPayload(nextPayload);
    setAnswer(nextAnswer);
    savedRef.current = JSON.stringify(nextAnswer);
    timeoutSubmissionRef.current = null;
    setRemaining(null);
    setNotice("");
    setAdvancing(false);
  }, [ready]);

  useEffect(() => {
    if (!payload?.expires_at) return;
    const tick = () => setRemaining(Math.max(0, Math.ceil((payload.expires_at! - Date.now()) / 1000)));
    tick();
    const timer = window.setInterval(tick, 500);
    return () => window.clearInterval(timer);
  }, [payload?.expires_at]);

  useEffect(() => {
    if (!payload || pending || advancing) return;
    const serialized = JSON.stringify(answer);
    if (serialized === savedRef.current) return;
    const timer = window.setTimeout(async () => {
      const result = await saveRecruitmentAnswer({
        applicationId,
        questionId: payload.question.id,
        answer,
        questionToken: payload.question_token,
        submit: false,
      });
      if (result.ok) {
        savedRef.current = serialized;
        setNotice("Rascunho salvo com segurança.");
      } else {
        setNotice(result.error ?? "Rascunho pendente.");
      }
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [answer, applicationId, payload, pending, advancing]);

  useEffect(() => {
    if (!payload) return;
    const record = (eventType: string, durationMs?: number) => {
      void recordRecruitmentIntegrity({
        applicationId,
        questionId: payload.question.id,
        eventType,
        durationMs,
      });
    };
    const onVisibility = () => record(document.hidden ? "TAB_HIDDEN" : "TAB_VISIBLE");
    const onBlur = () => {
      blurStarted.current = Date.now();
      record("WINDOW_BLURRED");
    };
    const onFocus = () => {
      record("WINDOW_FOCUSED", blurStarted.current ? Date.now() - blurStarted.current : undefined);
      blurStarted.current = null;
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
    };
  }, [applicationId, payload]);

  useEffect(() => {
    if (!payload || !clipboardRestricted) return;
    const onBeforeInput = (event: InputEvent) => {
      const target = event.target;
      if (!(target instanceof Element) || !target.closest(".candidate-answer")) return;
      if (event.inputType !== "insertFromPaste") return;
      event.preventDefault();
      setNotice("Colagem e cópia estão desabilitadas nesta questão.");
      void recordRecruitmentIntegrity({
        applicationId,
        questionId: payload.question.id,
        eventType: "PASTE_BLOCKED",
      });
    };
    document.addEventListener("beforeinput", onBeforeInput as EventListener);
    return () => document.removeEventListener("beforeinput", onBeforeInput as EventListener);
  }, [applicationId, clipboardRestricted, payload]);

  useEffect(() => {
    if (
      remaining !== 0
      || !payload
      || advancing
      || timeoutSubmissionRef.current === payload.question.id
    ) return;
    timeoutSubmissionRef.current = payload.question.id;
    const timer = window.setTimeout(() => {
      void saveRecruitmentAnswer({
        applicationId,
        questionId: payload.question.id,
        answer,
        questionToken: payload.question_token,
        submit: true,
      }).then((result) => {
        if (result.ok) {
          setAdvancing(true);
          setNotice("Tempo encerrado. Preparando a próxima questão...");
          router.refresh();
        } else {
          timeoutSubmissionRef.current = null;
          setNotice(result.error ?? "Não foi possível finalizar a questão.");
        }
      });
    }, 5_200);
    return () => window.clearTimeout(timer);
  }, [remaining, payload, applicationId, answer, router, advancing]);

  const textLength = typeof answer === "string" ? answer.length : 0;
  const progress = useMemo(
    () => Math.round(((ready.ordinal ?? ready.total ?? 1) / (ready.total ?? 1)) * 100),
    [ready.ordinal, ready.total],
  );

  const blocked = (event: React.SyntheticEvent, type: string) => {
    if (!payload || !clipboardRestricted) return;
    event.preventDefault();
    setNotice("Colagem e cópia estão desabilitadas nesta questão.");
    void recordRecruitmentIntegrity({
      applicationId,
      questionId: payload.question.id,
      eventType: type,
    });
  };

  if (ready.complete) {
    return (
      <section className="candidate-card candidate-complete">
        <Check size={32} aria-hidden="true" />
        <h2>Avaliação concluída</h2>
        <p>Revise o protocolo e envie a candidatura para a fila do comando.</p>
        <button
          className="button button-primary"
          disabled={pending}
          onClick={() => startTransition(async () => {
            const result = await submitRecruitmentApplication(
              applicationId,
              Number(ready.application_version ?? 1),
            );
            if (result.ok) router.push("/minha-candidatura");
            else setNotice(result.error ?? "Não foi possível enviar.");
          })}
          type="button"
        >
          Confirmar e enviar candidatura
        </button>
        {notice && <p className="candidate-notice" role="status">{notice}</p>}
      </section>
    );
  }

  if (!payload) {
    return (
      <section className="candidate-card question-ready">
        <LockKeyhole size={30} aria-hidden="true" />
        <span className="eyebrow">QUESTÃO {String(ready.ordinal).padStart(2, "0")} DE {ready.total}</span>
        <h2>Questão pronta</h2>
        <p>O enunciado será liberado somente após o início. O cronômetro é controlado pelo servidor e não reinicia ao atualizar a página.</p>
        <div className="ready-time"><Clock3 size={18} /><strong>{Math.ceil((ready.time_seconds ?? 0) / 60)} min</strong><span>tempo estimado</span></div>
        <button
          className="button button-primary"
          disabled={pending}
          onClick={() => startTransition(async () => {
            const result = await startRecruitmentQuestion(applicationId, Number(ready.id));
            if (result.ok) {
              setPayload(result.data);
              setAnswer(initialAnswer(result.data));
            } else setNotice(result.error);
          })}
          type="button"
        >
          Iniciar questão
        </button>
        {notice && <p className="candidate-notice" role="status">{notice}</p>}
      </section>
    );
  }

  const question = payload.question;
  const expired = remaining === 0;
  const common = {
    disabled: pending || expired || advancing,
    onPaste: (event: React.ClipboardEvent) => blocked(event, "PASTE_BLOCKED"),
    onDrop: (event: React.DragEvent) => blocked(event, "DROP_BLOCKED"),
    onContextMenu: (event: React.MouseEvent) => {
      if (clipboardRestricted) {
        event.preventDefault();
        setNotice("O menu de colagem está desabilitado nesta questão.");
      }
    },
  };
  return (
    <section className={clsx("candidate-card", "question-active", question.security_level === "STRICT" && "strict-question")}>
      <header className="question-command-strip">
        <div><span>PROTOCOLO</span><strong>{protocol}</strong></div>
        <div><span>PROGRESSO</span><strong>{ready.ordinal} / {ready.total}</strong></div>
        <div className={clsx("timer-readout", remaining !== null && remaining <= 30 && "danger")}>
          <span>TEMPO RESTANTE</span>
          <strong>{remaining === null ? "—" : `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`}</strong>
        </div>
      </header>
      <progress
        aria-label={`${progress}% concluído`}
        className="candidate-progress"
        max={100}
        value={progress}
      />
      <div className="question-body" onCopy={(event) => blocked(event, "COPY_BLOCKED")} onCut={(event) => blocked(event, "CUT_BLOCKED")}>
        <span className="eyebrow">{question.security_level} / RESPOSTA INDIVIDUAL</span>
        <h2 className={clsx(question.security_level === "STRICT" && "no-select")}>{question.title}</h2>
        {question.description && <p>{question.description}</p>}
        {question.alternative_format && <p className="accessibility-adaptation"><strong>Adaptação ativa:</strong> {question.alternative_format}</p>}
        {question.type === "BOOLEAN" ? (
          <fieldset className="candidate-answer candidate-choice-field" disabled={common.disabled}>
            <legend>SUA RESPOSTA</legend>
            <div className="candidate-options candidate-options-single">
              {[["true", "Sim"], ["false", "Não"]].map(([value, label], index) => (
                <label className={clsx(answer === (value === "true") && "selected")} key={value}>
                  <input checked={answer === (value === "true")} name={`question-${question.id}`} onChange={() => setAnswer(value === "true")} type="radio" value={value} />
                  <span className="candidate-option-index">{String.fromCharCode(65 + index)}</span><span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : question.type === "SINGLE_SELECT" ? (
          <fieldset className="candidate-answer candidate-choice-field" disabled={common.disabled}>
            <legend>SUA RESPOSTA</legend>
            <div className="candidate-options candidate-options-single">
              {question.options.map((option, index) => (
                <label className={clsx(answer === option && "selected")} key={option}>
                  <input checked={answer === option} name={`question-${question.id}`} onChange={() => setAnswer(option)} type="radio" value={option} />
                  <span className="candidate-option-index">{String.fromCharCode(65 + index)}</span><span>{option}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : question.type === "MULTI_SELECT" ? (
          <fieldset className="candidate-answer candidate-choice-field" disabled={common.disabled}>
            <legend>SUA RESPOSTA</legend>
            <div className="candidate-options">{question.options.map((option, index) => <label className={clsx(Array.isArray(answer) && answer.includes(option) && "selected")} key={option}><input checked={Array.isArray(answer) && answer.includes(option)} type="checkbox" onChange={(event) => setAnswer((current) => {
              const list = Array.isArray(current) ? current : [];
              return event.target.checked ? [...list, option] : list.filter((item) => item !== option);
            })} /><span className="candidate-option-index">{String.fromCharCode(65 + index)}</span><span>{option}</span></label>)}</div>
          </fieldset>
        ) : (
          <label className="candidate-answer">
            <span>SUA RESPOSTA</span>
            {question.type === "NUMBER" ? (
              <input {...common} inputMode="numeric" type="number" value={String(answer)} onChange={(event) => setAnswer(event.target.value)} />
            ) : question.type === "DATE" ? (
              <input {...common} type="date" value={String(answer)} onChange={(event) => setAnswer(event.target.value)} />
            ) : question.type === "SHORT_TEXT" ? (
              <input {...common} maxLength={question.max_length ?? undefined} type="text" value={String(answer)} onChange={(event) => setAnswer(event.target.value)} />
            ) : (
              <textarea {...common} maxLength={question.max_length ?? undefined} rows={9} value={String(answer)} onChange={(event) => setAnswer(event.target.value)} />
            )}
          </label>
        )}
        <div className="answer-meta">
          {question.max_length && <span>{textLength} / {question.max_length} caracteres</span>}
          {question.min_length && <span>Mínimo: {question.min_length}</span>}
          {clipboardRestricted && <span><ShieldAlert size={13} /> Colagem não permitida</span>}
          {question.clipboard_adapted && <span><ShieldAlert size={13} /> Clipboard adaptado por acessibilidade</span>}
        </div>
        <footer className="question-actions">
          <span role="status"><Save size={13} /> {notice || "Autosave a cada 3 segundos"}</span>
          <button className="button button-primary" disabled={pending || expired || advancing} onClick={() => startTransition(async () => {
            const result = await saveRecruitmentAnswer({
              applicationId,
              questionId: question.id,
              answer,
              questionToken: payload.question_token,
              submit: true,
            });
            if (result.ok) {
              setAdvancing(true);
              setNotice("Resposta confirmada. Preparando a próxima questão...");
              router.refresh();
            }
            else {
              setNotice(result.error ?? "Não foi possível confirmar.");
            }
          })} type="button">{pending || advancing ? "Salvando..." : "Salvar e próxima questão"}</button>
        </footer>
      </div>
    </section>
  );
}
