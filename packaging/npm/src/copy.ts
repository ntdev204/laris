// What `/copy` puts on the clipboard: the original Markdown of the last answer, or one of its
// code blocks, never the drawn screen.
import { parseMarkdown } from "./markdown.js";
import type { Item } from "./state.js";

export type CopyChoice = { text: string; what: string } | { error: string };

export const COPY_USAGE = "/copy [code]  copies the last answer (or its last code block) as plain text";

/** The assistant's text since the last thing the user said: one answer can be several items
 *  because tool calls fall between its parts. */
function lastAnswer(items: Item[]): string {
  let from = 0;
  items.forEach((item, n) => { if (item.kind === "user") from = n + 1; });
  const parts = items.slice(from).flatMap((i) => (i.kind === "assistant" && i.text.trim() !== "" ? [i.text.trim()] : []));
  if (parts.length) return parts.join("\n\n");
  // the user has already typed again (queued) or sent a command: fall back to the one before
  const older = items.slice(0, from).reverse().find((i) => i.kind === "assistant" && i.text.trim() !== "");
  return older && older.kind === "assistant" ? older.text.trim() : "";
}

export function copyTarget(items: Item[], arg: string): CopyChoice {
  const text = lastAnswer(items);
  if (!text) return { error: "There is no answer to copy yet." };
  const word = arg.trim().toLowerCase();
  if (word === "") return { text, what: "the last answer" };
  if (word === "code") {
    const blocks = parseMarkdown(text).filter((b) => b.kind === "code");
    const block = blocks[blocks.length - 1];
    if (!block || block.kind !== "code") return { error: "The last answer has no code block." };
    return { text: block.lines.join("\n"), what: "the last code block" };
  }
  return { error: COPY_USAGE };
}
