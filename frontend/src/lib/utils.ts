/**
 * Kept as a re-export so existing imports of `@/lib/utils` keep resolving while
 * the formatting helpers live in one place. New code should import from
 * `@/lib/format` directly.
 */
export { cn, formatArea, formatCount, formatDate, formatDateTime, toNumber } from "./format";
