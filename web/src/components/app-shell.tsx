"use client";

import clsx from "clsx";
import {
  Activity,
  BookOpenCheck,
  BriefcaseBusiness,
  ChevronDown,
  ClipboardCheck,
  FileClock,
  Fingerprint,
  Gauge,
  GraduationCap,
  History,
  Inbox,
  LogOut,
  Menu,
  Network,
  Radio,
  ScrollText,
  Settings,
  ShieldCheck,
  ShieldAlert,
  Siren,
  SlidersHorizontal,
  TicketCheck,
  UserRound,
  Users,
  X,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { logout } from "@/app/login/actions";
import {
  accessFingerprint,
  can,
  canAccessPath,
  canAny,
  normalizeAccessContext,
  type AccessContext,
} from "@/lib/access";

type NavigationItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
  permission?: string;
  permissions?: readonly string[];
};

const groups: { label: string; items: NavigationItem[] }[] = [
  {
    label: "VISÃO GERAL",
    items: [
      { href: "/dashboard", label: "Centro de Comando", icon: Gauge },
      { href: "/profile", label: "Minha identidade", icon: UserRound },
    ],
  },
  {
    label: "OPERAÇÃO",
    items: [
      { href: "/readiness", label: "Prontidão", icon: Activity, permission: "operations.view" },
      { href: "/patrols", label: "Patrulhas", icon: Radio, permission: "patrol.view.all" },
      { href: "/shifts", label: "Controle de ponto", icon: FileClock, permission: "shift.view.all" },
    ],
  },
  {
    label: "EFETIVO",
    items: [
      { href: "/members", label: "Efetivo", icon: Users, permission: "member.view" },
      { href: "/recruitment", label: "Recrutamento", icon: ClipboardCheck, permission: "recruitment.view" },
      { href: "/recruits", label: "Recrutas", icon: ShieldCheck, permission: "recruitment.review" },
      { href: "/career", label: "Carreira", icon: BriefcaseBusiness, permission: "career.manage" },
      { href: "/officer-candidacies", label: "Oficialato", icon: ShieldCheck, permission: "officer.review" },
      { href: "/qualifications", label: "Qualificações", icon: BookOpenCheck, permission: "qualification.view.all" },
      { href: "/trainings", label: "Treinamentos", icon: GraduationCap, permission: "training.view.self" },
    ],
  },
  {
    label: "ADMINISTRAÇÃO",
    items: [
      { href: "/inbox", label: "Caixa de entrada", icon: Inbox, permission: "admin.inbox.view" },
      { href: "/registration", label: "Portaria Digital", icon: ShieldCheck, permission: "registration.view" },
      { href: "/tickets", label: "Atendimentos", icon: TicketCheck, permission: "ticket.view" },
      { href: "/discipline", label: "Disciplina", icon: Siren, permission: "discipline.manage" },
    ],
  },
  {
    label: "INTELIGÊNCIA",
    items: [
      { href: "/changes", label: "O que mudou", icon: History, permission: "changes.view" },
      { href: "/reports", label: "Relatórios", icon: ClipboardCheck, permission: "reports.view" },
      { href: "/audit", label: "Auditoria", icon: ScrollText, permission: "decisions.view" },
      { href: "/identity", label: "Integridade", icon: Fingerprint, permission: "integrity.view" },
    ],
  },
  {
    label: "SISTEMA",
    items: [
      {
        href: "/identity/discord",
        label: "Discord e identidade",
        icon: Network,
        permissions: ["identity.manage", "identity.configure", "identity.reconcile"],
      },
      { href: "/settings", label: "Configurações", icon: Settings, permission: "settings.manage" },
      { href: "/maintenance", label: "Manutenção", icon: SlidersHorizontal, permission: "maintenance.manage" },
      { href: "/security", label: "Segurança", icon: ShieldAlert, permission: "security.manage" },
    ],
  },
];

function Sidebar({ context, close }: { context: AccessContext; close?: () => void }) {
  const pathname = usePathname();
  return (
    <>
      <div className="sidebar-brand">
        <div className="brand-mark small brand-emblem" aria-hidden="true"><Image alt="" height={43} src="/choque-emblem.png" width={43} /></div>
        <div><strong>CHOQUE BGR</strong><span>CENTRO DE COMANDO</span></div>
      </div>
      <nav className="sidebar-nav" aria-label="Navegação principal">
        {groups.map((group) => {
          const items = group.items.filter((item) => (
            (!item.permission || can(context, item.permission))
            && (!item.permissions || canAny(context, item.permissions))
          ));
          if (!items.length) return null;
          return (
            <section className="nav-group" key={group.label}>
              <h2>{group.label}</h2>
              {items.map((item) => {
                const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                const Icon = item.icon;
                return (
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={clsx("nav-item", active && "active")}
                    href={item.href}
                    key={item.href}
                    onClick={close}
                  >
                    <Icon size={16} strokeWidth={1.7} aria-hidden="true" />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </section>
          );
        })}
      </nav>
      <div className="sidebar-clearance">
        <span>NÍVEL DE ACESSO · V{context.authorization_version}</span>
        <strong>{context.access.profile_name}</strong>
      </div>
    </>
  );
}

export function AppShell({ context, children }: { context: AccessContext; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [liveContext, setLiveContext] = useState(context);
  const [revalidationState, setRevalidationState] = useState<"CURRENT" | "CHECKING" | "DEGRADED">("CURRENT");
  const [accessRevoked, setAccessRevoked] = useState(false);
  const contextRef = useRef(context);
  const requestRunning = useRef(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const drawerWasOpenRef = useRef(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!open) {
      if (drawerWasOpenRef.current) {
        menuTriggerRef.current?.focus();
        drawerWasOpenRef.current = false;
      }
      return;
    }

    drawerWasOpenRef.current = true;
    drawerCloseRef.current?.focus();

    const handleDrawerKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        drawerRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleDrawerKeyDown);
    return () => document.removeEventListener("keydown", handleDrawerKeyDown);
  }, [open]);

  useEffect(() => {
    let disposed = false;
    const controllers = new Set<AbortController>();

    const refreshAccess = async () => {
      if (
        disposed
        || requestRunning.current
        || document.visibilityState !== "visible"
        || !navigator.onLine
      ) return;
      requestRunning.current = true;
      setRevalidationState("CHECKING");
      const controller = new AbortController();
      controllers.add(controller);
      try {
        const response = await fetch("/api/access-context", {
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (disposed) return;
        if (response.status === 401) {
          router.replace("/login");
          return;
        }
        if (response.status === 403) {
          setAccessRevoked(true);
          router.replace("/access-denied?reason=identity-revoked");
          return;
        }
        if (!response.ok) throw new Error(`Access context ${response.status}`);
        const nextContext = normalizeAccessContext(await response.json());
        if (!canAccessPath(nextContext, pathname)) {
          setAccessRevoked(true);
          contextRef.current = nextContext;
          setLiveContext(nextContext);
          router.replace("/access-denied?reason=permission-revoked");
          return;
        }
        const changed = accessFingerprint(nextContext) !== accessFingerprint(contextRef.current);
        contextRef.current = nextContext;
        setLiveContext(nextContext);
        setRevalidationState("CURRENT");
        if (changed) router.refresh();
      } catch (error) {
        if (!disposed && !(error instanceof DOMException && error.name === "AbortError")) {
          setRevalidationState("DEGRADED");
        }
      } finally {
        controllers.delete(controller);
        requestRunning.current = false;
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void refreshAccess();
    };
    const interval = window.setInterval(() => void refreshAccess(), 5_000);
    window.addEventListener("online", refreshAccess);
    window.addEventListener("focus", refreshAccess);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      disposed = true;
      controllers.forEach((controller) => controller.abort());
      window.clearInterval(interval);
      window.removeEventListener("online", refreshAccess);
      window.removeEventListener("focus", refreshAccess);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [pathname, router]);

  const identityLine = [
    liveContext.member.rank_name ?? "Sem patente",
    liveContext.member.primary_position?.name,
  ].filter(Boolean).join(" · ");

  return (
    <div className="app-shell">
      <aside className="sidebar"><Sidebar context={liveContext} /></aside>
      {open && (
        <>
          <div
            aria-label="Menu de navegação"
            aria-modal="true"
            className="mobile-drawer open"
            id="command-navigation-drawer"
            ref={drawerRef}
            role="dialog"
          >
            <button
              aria-label="Fechar menu"
              className="drawer-close"
              onClick={() => setOpen(false)}
              ref={drawerCloseRef}
            >
              <X />
            </button>
            <Sidebar context={liveContext} close={() => setOpen(false)} />
          </div>
          <button
            aria-label="Fechar menu ao tocar fora"
            className="drawer-scrim"
            onClick={() => setOpen(false)}
          />
        </>
      )}
      <div className="work-area">
        <header className="topbar">
          <button
            aria-controls="command-navigation-drawer"
            aria-expanded={open}
            aria-label="Abrir menu"
            className="menu-trigger"
            onClick={() => setOpen(true)}
            ref={menuTriggerRef}
          >
            <Menu />
          </button>
          <div className="system-state">
            <span><i className="state-dot operational" /> SISTEMA OPERACIONAL</span>
            <span>
              <i className={clsx("state-dot", revalidationState === "CURRENT" ? "operational" : revalidationState === "CHECKING" ? "checking" : "degraded")} />
              {revalidationState === "CURRENT" ? "IDENTIDADE SINCRONIZADA" : revalidationState === "CHECKING" ? "REVALIDANDO ACESSO" : "REVALIDAÇÃO PENDENTE"}
            </span>
          </div>
          <p aria-atomic="true" aria-live="polite" className="visually-hidden">
            {revalidationState === "DEGRADED" ? "Revalidação de acesso pendente." : ""}
          </p>
          <div className="member-control">
            <div><strong>{liveContext.member.mta_nick}</strong><span>{identityLine}</span></div>
            <ChevronDown className="member-chevron" size={15} aria-hidden="true" />
            <form action={logout}>
              <button className="account-exit" type="submit" aria-label="Sair do Centro de Comando"><LogOut size={15} aria-hidden="true" /></button>
            </form>
          </div>
        </header>
        <main className="command-content">
          {accessRevoked ? (
            <section className="access-revoked" role="alert">
              <ShieldAlert size={28} aria-hidden="true" />
              <div><strong>Acesso revogado</strong><p>Seu perfil Discord mudou e esta área deixou de estar disponível.</p></div>
            </section>
          ) : children}
        </main>
      </div>
    </div>
  );
}
