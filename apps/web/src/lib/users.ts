"use client";

import { useEffect, useState } from "react";
import { apiGet } from "./api";
import type { UserOut } from "./types";

/** id → user map for showing assignee names. Only fetched when the role holds users.read. */
export function useUserDirectory(enabled: boolean): Map<string, UserOut> {
  const [map, setMap] = useState<Map<string, UserOut>>(new Map());
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    apiGet("/v1/users")
      .then((users) => live && setMap(new Map(users.map((u) => [u.id, u]))))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [enabled]);
  return map;
}

export function userName(map: Map<string, UserOut>, id: string | null | undefined, meId?: string, meName?: string): string {
  if (!id) return "Unassigned";
  if (id === meId) return `${meName ?? "You"} (you)`;
  return map.get(id)?.full_name ?? `User ${id.slice(0, 8)}`;
}
