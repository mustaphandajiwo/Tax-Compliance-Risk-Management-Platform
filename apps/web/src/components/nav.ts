/** Navigation is filtered by the permissions returned from /v1/auth/me. This is UX only — the API enforces access. */
export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  /** Visible if the user holds ANY of these permissions. */
  anyOf: string[];
  section: "Monitor" | "Investigate" | "Govern";
}

export type IconName = "overview" | "people" | "radar" | "folder" | "search" | "database" | "scale" | "shield" | "settings";

export const NAV: NavItem[] = [
  { href: "/", label: "Overview", icon: "overview", anyOf: ["metrics.read"], section: "Monitor" },
  { href: "/workbench", label: "Risk workbench", icon: "radar", anyOf: ["risk.read"], section: "Investigate" },
  { href: "/cases", label: "Cases", icon: "folder", anyOf: ["cases.read"], section: "Investigate" },
  { href: "/audit-referrals", label: "Audit referrals", icon: "search", anyOf: ["audits.decide"], section: "Investigate" },
  { href: "/taxpayers", label: "Taxpayers", icon: "people", anyOf: ["taxpayers.read"], section: "Investigate" },
  { href: "/data-quality", label: "Data quality", icon: "database", anyOf: ["imports.read", "data_quality.review"], section: "Govern" },
  { href: "/rules", label: "Rules & models", icon: "scale", anyOf: ["legal_rules.read", "risk.read"], section: "Govern" },
  { href: "/audit", label: "Audit log", icon: "shield", anyOf: ["audit_log.read"], section: "Govern" },
  { href: "/admin", label: "Administration", icon: "settings", anyOf: ["tenant.admin", "users.manage", "audit_log.read"], section: "Govern" },
];

export function visibleNav(perms: readonly string[]): NavItem[] {
  const set = new Set(perms);
  return NAV.filter((n) => n.anyOf.some((p) => set.has(p)));
}

export function isActive(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
