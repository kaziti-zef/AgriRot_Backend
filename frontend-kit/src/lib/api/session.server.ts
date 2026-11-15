import "server-only";
/**
 * Côté SERVEUR uniquement : jetons dans des cookies httpOnly (guide §6 : jamais dans localStorage,
 * jamais dans une variable NEXT_PUBLIC_*).
 */
import { cookies } from "next/headers";

export const API_URL = (process.env.AGROROT_API_URL ?? "http://localhost:8000/api/v1").replace(/\/$/, "");
const SECURE = process.env.NODE_ENV === "production";
const ACCESS = "agr_at";
const REFRESH = "agr_rt";
const REFRESH_MAX_AGE = 60 * 60 * 24 * Number(process.env.AGROROT_REFRESH_DAYS ?? 7); // = REFRESH_TOKEN_DAYS du backend

export interface Jetons { access_token: string; refresh_token?: string; expires_in: number }

export async function lireJetons() {
  const c = await cookies();
  return { access: c.get(ACCESS)?.value ?? null, refresh: c.get(REFRESH)?.value ?? null };
}

export async function ecrireJetons(j: Jetons) {
  const c = await cookies();
  const base = { httpOnly: true, secure: SECURE, sameSite: "lax" as const, path: "/" };
  c.set(ACCESS, j.access_token, { ...base, maxAge: j.expires_in });
  if (j.refresh_token) c.set(REFRESH, j.refresh_token, { ...base, path: "/api/v1", maxAge: REFRESH_MAX_AGE });
}

export async function effacerJetons() {
  const c = await cookies();
  c.delete(ACCESS);
  c.delete({ name: REFRESH, path: "/api/v1" });
}

/** Un seul renouvellement (guide §6). Renvoie le nouveau jeton d'accès ou null. */
export async function renouveler(refresh: string | null, lang: string): Promise<string | null> {
  if (!refresh) return null;
  const r = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json", "Accept-Language": lang },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!r.ok) return null;
  const j = (await r.json()) as Jetons;
  await ecrireJetons(j);
  return j.access_token;
}
