import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { normalizeAccessContext } from "@/lib/access";

const navigation = vi.hoisted(() => ({
  pathname: "/settings",
  refresh: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ refresh: navigation.refresh, replace: navigation.replace }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { children: ReactNode }) => (
    <a href={String(href)} {...props}>{children}</a>
  ),
}));

vi.mock("@/app/login/actions", () => ({ logout: vi.fn() }));

import { AppShell } from "./app-shell";

describe("AppShell live authorization", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    navigation.pathname = "/settings";
    navigation.refresh.mockReset();
    navigation.replace.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("revokes the open route when the Discord authorization is downgraded", async () => {
    const elevated = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: {
        profile: "ALTO_COMANDO",
        profile_name: "Alto Comando",
        permissions: ["settings.manage"],
        authorization_version: 7,
      },
    });
    const downgraded = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: {
        profile: "MEMBRO",
        profile_name: "Membro",
        permissions: [],
        authorization_version: 8,
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => downgraded,
    }));

    render(<AppShell context={elevated}><div>Configuração protegida</div></AppShell>);
    expect(screen.getByText("Configuração protegida")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(navigation.replace).toHaveBeenCalledWith("/access-denied?reason=permission-revoked");
    expect(screen.getByRole("alert")).toHaveTextContent("Acesso revogado");
  });

  it("refreshes the server tree when the authorization version changes on an allowed route", async () => {
    navigation.pathname = "/dashboard";
    const initial = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: { profile: "MEMBRO", permissions: ["patrol.view.self"], authorization_version: 2 },
    });
    const upgraded = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: {
        profile: "COMANDO",
        profile_name: "Comando",
        permissions: ["member.view", "patrol.view.self"],
        authorization_version: 3,
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => upgraded,
    }));

    render(<AppShell context={initial}><div>Centro</div></AppShell>);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(navigation.refresh).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("Comando").length).toBeGreaterThan(0);
  });

  it("announces only a degraded access check instead of every polling transition", async () => {
    const context = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: { profile: "MEMBRO", profile_name: "Membro", permissions: [], authorization_version: 2 },
    });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));

    const view = render(<AppShell context={context}><div>Centro</div></AppShell>);
    const liveRegion = view.container.querySelector('[aria-live="polite"]');
    expect(view.container.querySelector(".system-state")).not.toHaveAttribute("aria-live");
    expect(liveRegion).toHaveTextContent("");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(liveRegion).toHaveTextContent("Revalidação de acesso pendente.");
  });

  it("exposes an accessible mobile drawer and restores focus after Escape", () => {
    const context = normalizeAccessContext({
      member: { discord_id: 20, mta_nick: "Sentinela", status: "ACTIVE" },
      access: { profile: "MEMBRO", profile_name: "Membro", permissions: [], authorization_version: 2 },
    });

    const view = render(<AppShell context={context}><div>Centro</div></AppShell>);
    const shell = within(view.container);

    const trigger = shell.getByRole("button", { name: "Abrir menu" });
    expect(trigger).toHaveAttribute("aria-controls", "command-navigation-drawer");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(shell.queryByRole("dialog", { name: "Menu de navegação" })).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(shell.getByRole("dialog", { name: "Menu de navegação" })).toBeInTheDocument();
    expect(shell.getByRole("button", { name: "Fechar menu" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(shell.queryByRole("dialog", { name: "Menu de navegação" })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });
});
