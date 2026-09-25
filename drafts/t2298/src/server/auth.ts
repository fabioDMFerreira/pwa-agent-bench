// Trivial header-based auth for the reference implementation. The real PWA
// mounts a session/JWT middleware upstream; the router below only cares that
// `req.userId` is a string.

import type { NextFunction, Request, Response } from "express";

export interface AuthedRequest extends Request {
  userId?: string;
}

export function headerAuth(
  req: AuthedRequest,
  _res: Response,
  next: NextFunction,
): void {
  // Two entry points: an `x-user-id` header (tests, API scripts) and an
  // `x-demo-user` header (the /demo E2E page).
  const id =
    (req.header("x-user-id") ?? req.header("x-demo-user") ?? "").trim() || null;
  if (id) req.userId = id;
  next();
}

export function requireUser(
  req: AuthedRequest,
  res: Response,
  next: NextFunction,
): void {
  if (!req.userId) {
    res
      .status(401)
      .json({ error: { code: "UNAUTHENTICATED", message: "sign in required" } });
    return;
  }
  next();
}
