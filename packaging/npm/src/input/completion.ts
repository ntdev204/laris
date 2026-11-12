// What the cursor is completing: `/command` at the start of the line, `@path` anywhere.
export interface Trigger { trigger: "/" | "@"; text: string; start: number }

export function currentTrigger(text: string, cursor: number): Trigger | null {
  const before = text.slice(0, cursor);
  const slash = /^\/([^\s/]*)$/.exec(before);
  if (slash) return { trigger: "/", text: slash[1] ?? "", start: 0 };
  const at = /(?:^|\s)@(\S*)$/.exec(before);
  if (at) {
    const token = at[1] ?? "";
    return { trigger: "@", text: token, start: cursor - token.length - 1 };
  }
  return null;
}

/** The buffer with the trigger word replaced by the chosen value (a space follows a file). */
export function applyCompletion(text: string, cursor: number, t: Trigger, value: string): { text: string; cursor: number } {
  const isDir = value.endsWith("/");
  const head = text.slice(0, t.start);
  const inserted = t.trigger === "/" ? `/${value.replace(/^\//, "")} ` : `@${value.replace(/^@/, "")}${isDir ? "" : " "}`;
  const tail = text.slice(cursor);
  return { text: head + inserted + tail, cursor: head.length + inserted.length };
}
