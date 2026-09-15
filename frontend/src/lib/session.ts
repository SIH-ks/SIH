/**
 * Session shape and cookie names, shared by the route handlers and the server
 * components. No React and no `next/headers` import here, so this module is safe
 * to pull into either side of the boundary.
 */

export const SESSION_COOKIE = "adhikar_session";
/** httpOnly. Holds the JWT. Never readable from client JavaScript — see
 * `app/api/session/route.ts` for why the token deliberately never reaches the
 * browser's script context. */

export const PROFILE_COOKIE = "adhikar_profile";
/** Readable by client JavaScript, and *only* carries display identity: the
 * signed-in user's name, role and district. Splitting it from the token is what
 * lets the UI grey out an action the current role cannot perform without the
 * bearer token ever entering the client bundle.
 *
 * It is presentation, not authorization: every gate this cookie drives in the UI
 * is also enforced by the API (`app/api/deps.py`). Tampering with it changes
 * which buttons are drawn and nothing else. */

export type UserRole = "auditor" | "operator" | "reviewer" | "admin";

export interface SessionProfile {
  id: string;
  username: string;
  full_name: string;
  designation?: string | null;
  role: UserRole;
  district?: string | null;
  state?: string | null;
}

const ROLE_RANK: Record<UserRole, number> = { auditor: 0, operator: 1, reviewer: 2, admin: 3 };

export const ROLE_LABEL: Record<UserRole, string> = {
  auditor: "Auditor",
  operator: "Data Entry Operator",
  reviewer: "Revenue Inspector",
  admin: "District Administrator",
};

/** Mirrors `UserRole.outranks_or_equals` on the backend. Kept as one function so
 * every "can this user…?" check in the UI reads from the same ordering. */
export function atLeast(role: UserRole | undefined, minimum: UserRole): boolean {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[minimum];
}

export const can = {
  write: (role?: UserRole) => atLeast(role, "operator"),
  approve: (role?: UserRole) => atLeast(role, "reviewer"),
  administer: (role?: UserRole) => atLeast(role, "admin"),
};
