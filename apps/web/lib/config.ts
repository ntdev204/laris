// Match the Rust gateway default unless the deployment sets a lower limit.
export const maxRequestBytes = Number(process.env.LARIS_WEB_MAX_REQUEST_BYTES ?? 1_048_576);
if (!Number.isSafeInteger(maxRequestBytes) || maxRequestBytes <= 0) {
  throw new Error("LARIS_WEB_MAX_REQUEST_BYTES must be a positive integer");
}
