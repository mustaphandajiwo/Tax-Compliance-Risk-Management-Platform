"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { isActive, visibleNav, type NavItem } from "@/components/nav";
import { Loading } from "@/components/ui";
import { roleLabel, useAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: ReactNode }) {
  const { me, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !me) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, me, router, pathname]);

  if (loading || !me) {
    return (
      <main id="main" className="login-wrap">
        <Loading label="Checking your session…" />
      </main>
    );
  }

  const items = visibleNav(me.permissions);
  const sections: NavItem["section"][] = ["Monitor", "Investigate", "Govern"];

  return (
    <div className="shell">
      <nav className="sidenav" aria-label="Primary">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            TC
          </div>
          <div className="brand-text">
            <div className="brand-name">TaxCRIS</div>
            <div className="brand-sub">Compliance risk intelligence</div>
          </div>
        </div>
        {sections.map((s) => {
          const inSection = items.filter((i) => i.section === s);
          if (!inSection.length) return null;
          return (
            <div key={s}>
              <div className="nav-section">{s}</div>
              <ul>
                {inSection.map((item) => (
                  <li key={item.href}>
                    <Link href={item.href} aria-current={isActive(item.href, pathname) ? "page" : undefined} title={item.label}>
                      <Icon name={item.icon} />
                      <span className="nav-text">{item.label}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        <div className="nav-foot">
          Human oversight: the platform makes no autonomous adverse decisions. Every action is justified and audited.
        </div>
      </nav>
      <div className="main-col">
        <header className="topbar">
          <div>
            <div className="tenant-name">{me.tenant.name}</div>
            <div className="tenant-sub">
              State code {me.tenant.state_code} · config v{me.tenant.config_version}
            </div>
          </div>
          <div className="userbox">
            <div>
              <div className="user-name">{me.full_name}</div>
              <div className="user-role">{roleLabel(me.role)}</div>
            </div>
            <button type="button" className="btn btn-sm" onClick={logout}>
              Sign out
            </button>
          </div>
        </header>
        <main id="main" className="content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
