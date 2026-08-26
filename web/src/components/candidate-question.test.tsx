import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { saveRecruitmentAnswer } from "@/app/recrutamento/actions";

import { CandidateQuestion, type ReadyQuestion } from "./candidate-question";

const recordIntegrity = vi.fn(async (input: unknown) => {
  void input;
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/app/recrutamento/actions", () => ({
  startRecruitmentQuestion: vi.fn(),
  saveRecruitmentAnswer: vi.fn(async () => ({ ok: true })),
  submitRecruitmentApplication: vi.fn(async () => ({ ok: true })),
  recordRecruitmentIntegrity: (input: unknown) => recordIntegrity(input),
}));

const active: ReadyQuestion = {
  complete: false,
  id: 31,
  ordinal: 4,
  total: 24,
  status: "ACTIVE",
  security_level: "STRICT",
  question: {
    id: 31,
    title: "Descreva sua conduta em uma situação operacional.",
    description: null,
    type: "LONG_TEXT",
    required: true,
    min_length: 20,
    max_length: 500,
    options: [],
    security_level: "STRICT",
    allow_back: false,
  },
  started_at: Date.now(),
  expires_at: Date.now() + 300_000,
  draft: "",
  question_token: "signed-question-token",
};

describe("candidate controlled question", () => {
  beforeEach(() => {
    recordIntegrity.mockClear();
    vi.mocked(saveRecruitmentAnswer).mockResolvedValue({ ok: true });
  });
  afterEach(() => cleanup());

  it("does not reveal the prompt before the server start", () => {
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={{
      complete: false,
      id: 31,
      ordinal: 4,
      total: 24,
      status: "NOT_STARTED",
      time_seconds: 300,
    }} />);
    expect(screen.getByText("Questão pronta")).toBeInTheDocument();
    expect(screen.queryByText(active.question!.title)).not.toBeInTheDocument();
  });

  it.each([
    ["paste", "PASTE_BLOCKED"],
    ["copy", "COPY_BLOCKED"],
    ["cut", "CUT_BLOCKED"],
    ["drop", "DROP_BLOCKED"],
  ] as const)("blocks %s without reading clipboard content", (eventName, eventType) => {
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={active} />);
    const textarea = screen.getByLabelText("SUA RESPOSTA");
    const event = new Event(eventName, { bubbles: true, cancelable: true });
    fireEvent(textarea, event);
    expect(event.defaultPrevented).toBe(true);
    expect(recordIntegrity).toHaveBeenCalledWith(expect.objectContaining({ eventType }));
  });

  it("tracks focus evidence without turning it into a decision", () => {
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={active} />);
    fireEvent.blur(window);
    fireEvent.focus(window);
    expect(recordIntegrity).toHaveBeenCalledWith(expect.objectContaining({ eventType: "WINDOW_BLURRED" }));
    expect(recordIntegrity).toHaveBeenCalledWith(expect.objectContaining({ eventType: "WINDOW_FOCUSED" }));
    expect(screen.queryByText(/reprov/i)).not.toBeInTheDocument();
  });

  it("blocks the long-press/context menu on controlled answers", () => {
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={active} />);
    const textarea = screen.getByLabelText("SUA RESPOSTA");
    const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    fireEvent(textarea, event);
    expect(event.defaultPrevented).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent("menu de colagem");
  });

  it("blocks beforeinput paste events used by mobile browsers", () => {
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={active} />);
    const textarea = screen.getByLabelText("SUA RESPOSTA");
    const event = new InputEvent("beforeinput", {
      bubbles: true,
      cancelable: true,
      inputType: "insertFromPaste",
    });
    fireEvent(textarea, event);
    expect(event.defaultPrevented).toBe(true);
    expect(recordIntegrity).toHaveBeenCalledWith(
      expect.objectContaining({ eventType: "PASTE_BLOCKED" }),
    );
  });

  it("advances with a single explicit action", () => {
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={active} />);
    expect(screen.getByRole("button", { name: "Salvar e próxima questão" })).toBeInTheDocument();
    expect(screen.queryByText("Confirmar resposta?")).not.toBeInTheDocument();
  });

  it("presents a single-choice question as keyboard-accessible option cards", async () => {
    const singleChoice: ReadyQuestion = {
      ...active,
      question: {
        ...active.question!,
        type: "SINGLE_SELECT",
        options: ["Manter comunicação", "Encerrar a abordagem"],
      },
    };
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={singleChoice} />);
    fireEvent.click(screen.getByRole("radio", { name: /Manter comunicação/ }));
    expect(screen.getByRole("radio", { name: /Manter comunicação/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Salvar e próxima questão" }));
    await waitFor(() => expect(saveRecruitmentAnswer).toHaveBeenCalledWith(
      expect.objectContaining({ answer: "Manter comunicação", submit: true }),
    ));
  });

  it("replaces the submitted question when the server returns the next one", async () => {
    const { rerender } = render(
      <CandidateQuestion applicationId={5} protocol="AL-00005" ready={active} />,
    );
    rerender(
      <CandidateQuestion applicationId={5} protocol="AL-00005" ready={{
        complete: false,
        id: 32,
        ordinal: 5,
        total: 24,
        status: "NOT_STARTED",
        time_seconds: 300,
      }} />,
    );
    await waitFor(() => expect(screen.getByText("Questão pronta")).toBeInTheDocument());
    expect(screen.getByText("QUESTÃO 05 DE 24")).toBeInTheDocument();
    expect(screen.queryByText(active.question!.title)).not.toBeInTheDocument();
  });

  it("locks the old question and reports progress after a successful confirmation", async () => {
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={active} />);
    fireEvent.click(screen.getByRole("button", { name: "Salvar e próxima questão" }));
    await waitFor(() => expect(saveRecruitmentAnswer).toHaveBeenCalledWith(
      expect.objectContaining({ questionId: 31, submit: true }),
    ));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Resposta confirmada. Preparando a próxima questão",
    );
    expect(screen.getByRole("button", { name: "Salvando..." })).toBeDisabled();
  });

  it("shows a server validation error and lets the candidate correct the answer", async () => {
    vi.mocked(saveRecruitmentAnswer).mockResolvedValueOnce({
      ok: false,
      error: "Resposta abaixo do mínimo configurado.",
    });
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={active} />);
    fireEvent.click(screen.getByRole("button", { name: "Salvar e próxima questão" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Resposta abaixo do mínimo");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Salvar e próxima questão" })).toBeEnabled();
    });
  });

  it("keeps clipboard available when an audited accessibility adaptation exists", () => {
    const adapted: ReadyQuestion = {
      ...active,
      question: { ...active.question!, clipboard_adapted: true },
    };
    render(<CandidateQuestion applicationId={5} protocol="AL-00005" ready={adapted} />);
    const event = new Event("paste", { bubbles: true, cancelable: true });
    fireEvent(screen.getByLabelText("SUA RESPOSTA"), event);
    expect(event.defaultPrevented).toBe(false);
  });
});
