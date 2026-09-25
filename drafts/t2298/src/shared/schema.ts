// Zod schema for the tasks.table.columns preference payload. Shared between
// client and server so both sides validate identically.

import { z } from "zod";

export const CURRENT_VERSION = 1 as const;

export const TaskColumnsPref = z.object({
  version: z.literal(CURRENT_VERSION),
  visible: z.array(z.string()).min(1, { message: "visible must be non-empty" }),
  order: z.array(z.string()).default([]),
  widths: z.record(z.string(), z.number().positive()).default({}),
});

export type TaskColumnsPref = z.infer<typeof TaskColumnsPref>;

/**
 * Error codes the API returns as {"error": {"code": ...}} so tests and clients
 * can key on stable strings rather than English.
 */
export const ErrorCodes = {
  EMPTY_VISIBLE: "EMPTY_VISIBLE",
  VERSION_MISMATCH: "VERSION_MISMATCH",
  UNAUTHENTICATED: "UNAUTHENTICATED",
  INVALID_BODY: "INVALID_BODY",
  NOT_FOUND: "NOT_FOUND",
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];
