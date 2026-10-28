"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { humanize } from "@/lib/format";

interface NavItem {
  href: string;
  label: string;
  perms: string[];
}

const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Operations",
    items: [
      { href: "/dashboard", label: "Compliance Overview", perms: ["dashboard:read"] },
      { href: "/taxpayers", label: "Taxpayer Intelligence", perms: ["taxpayers:read"] },
      { href: "/risks", label: "Risk Register", perms: ["risks:read"] },
      { href: "/cases", label: "Intervention Queue", perms: ["cases:read"] },
      { href: "/programmes", label: "Compliance Programmes", perms: ["programmes:read"] },
      { href: "/imports", label: "Data Imports", perms: ["imports:read", "quality:read"] },
      { href: "/reports", label: "Management Reports", perms: ["reports:read"] },
    ],
  },
  {
    group: "Administration",
    items: [
      { href: "/admin/rules", label: "Rule Configuration", perms: ["rules:read"] },
      { href: "/admin/legal", label: "Legal Rules Library", perms: ["legal:read"] },
      { href: "/admin/audit", label: "Audit Log", perms: ["audit:read"] },
    ],
  },
];

export function SyntheticBanner({ environment, synthetic }: { environment?: string; synthetic?: boolean }) {
  return (
    <div className="synthetic-banner" role="note" aria-label="Data notice">
      <strong>{synthetic === false ? `Environment: ${environment}` : "SYNTHETIC DATA"}</strong>
      <span>
        {synthetic === false
          ? "Check the data classification before acting."
          : `${environment ? `${humanize(environment)} environment. ` : ""}All taxpayers, amounts, identifiers and legal parameters are synthetic. No taxpayer messages are sent.`}
      </span>
    </div>
  );
}

export function Wordmark() {
  return (
    <div className="wordmark">
      <span className="wordmark__name">NGSIRS Compliance Risk Management Platform</span>
      <span className="wordmark__owner">Niger State Internal Revenue Service</span>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { me, can, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => setMenuOpen(false), [pathname]);

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      <SyntheticBanner environment={me?.environment} synthetic={me?.synthetic_data} />
      <header className="topbar">
        <Wordmark />
        <div className="topbar__user">
          <span className="topbar__who">
            <span className="topbar__name">{me?.display_name}</span>
            <span className="topbar__roles">
              {me?.roles.map(humanize).join(", ")}
              {me && me.lga_scope.length > 0 && ` · LGA scope: ${me.lga_scope.join(", ")}`}
              {me && ` · Mode: ${humanize(me.operating_mode)}`}
            </span>
          </span>
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() => {
              signOut();
              router.push("/login");
            }}
          >
            Sign out
          </button>
          <button
            type="button"
            className="btn btn-quiet menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="primary-nav"
            onClick={() => setMenuOpen((o) => !o)}
          >
            Menu
          </button>
        </div>
      </header>
      <div className="shell__body">
        <nav id="primary-nav" className={`sidenav${menuOpen ? " is-open" : ""}`} aria-label="Primary">
          {NAV.map((g) => {
            const items = g.items.filter((i) => i.perms.some((p) => can(p)));
            if (items.length === 0) return null;
            return (
              <div key={g.group} className="sidenav__group">
                <p className="sidenav__heading">{g.group}</p>
                <ul>
                  {items.map((i) => {
                    const current = pathname === i.href || pathname.startsWith(`${i.href}/`);
                    return (
                      <li key={i.href}>
                        <Link href={i.href} aria-current={current ? "page" : undefined}>
                          {i.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </nav>
        <main id="main" tabIndex={-1} className="main">
          {children}
        </main>
      </div>
      <footer className="footer">
        Operations console for internal NGSIRS use. Outputs are risk indicators for human review, never tax
        assessments or enforcement decisions.
      </footer>
    </div>
  );
}
