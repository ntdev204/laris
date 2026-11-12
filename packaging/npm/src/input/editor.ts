// A multi-line text buffer with a cursor: pure functions, tested without a terminal.
export interface Buffer { text: string; cursor: number }

export const empty = (): Buffer => ({ text: "", cursor: 0 });
export const fromText = (text: string): Buffer => ({ text, cursor: text.length });

export function insert(b: Buffer, s: string): Buffer {
  return { text: b.text.slice(0, b.cursor) + s + b.text.slice(b.cursor), cursor: b.cursor + s.length };
}

export function backspace(b: Buffer): Buffer {
  if (b.cursor === 0) return b;
  return { text: b.text.slice(0, b.cursor - 1) + b.text.slice(b.cursor), cursor: b.cursor - 1 };
}

export function del(b: Buffer): Buffer {
  if (b.cursor >= b.text.length) return b;
  return { text: b.text.slice(0, b.cursor) + b.text.slice(b.cursor + 1), cursor: b.cursor };
}

export const left = (b: Buffer): Buffer => ({ ...b, cursor: Math.max(0, b.cursor - 1) });
export const right = (b: Buffer): Buffer => ({ ...b, cursor: Math.min(b.text.length, b.cursor + 1) });

function lineStart(text: string, at: number): number {
  return text.lastIndexOf("\n", at - 1) + 1;
}
function lineEnd(text: string, at: number): number {
  const i = text.indexOf("\n", at);
  return i < 0 ? text.length : i;
}

export const home = (b: Buffer): Buffer => ({ ...b, cursor: lineStart(b.text, b.cursor) });
export const end = (b: Buffer): Buffer => ({ ...b, cursor: lineEnd(b.text, b.cursor) });

export function lineCount(b: Buffer): number {
  return b.text.split("\n").length;
}
export function onFirstLine(b: Buffer): boolean {
  return !b.text.slice(0, b.cursor).includes("\n");
}
export function onLastLine(b: Buffer): boolean {
  return !b.text.slice(b.cursor).includes("\n");
}

export function up(b: Buffer): Buffer {
  const start = lineStart(b.text, b.cursor);
  if (start === 0) return b;
  const column = b.cursor - start;
  const prevStart = lineStart(b.text, start - 1);
  return { ...b, cursor: Math.min(prevStart + column, start - 1) };
}

export function down(b: Buffer): Buffer {
  const finish = lineEnd(b.text, b.cursor);
  if (finish >= b.text.length) return b;
  const column = b.cursor - lineStart(b.text, b.cursor);
  const nextStart = finish + 1;
  return { ...b, cursor: Math.min(nextStart + column, lineEnd(b.text, nextStart)) };
}

const isWord = (c: string | undefined): boolean => c !== undefined && /\S/.test(c);

export function wordLeft(b: Buffer): Buffer {
  let i = b.cursor;
  while (i > 0 && !isWord(b.text[i - 1])) i--;
  while (i > 0 && isWord(b.text[i - 1])) i--;
  return { ...b, cursor: i };
}
export function wordRight(b: Buffer): Buffer {
  let i = b.cursor;
  while (i < b.text.length && !isWord(b.text[i])) i++;
  while (i < b.text.length && isWord(b.text[i])) i++;
  return { ...b, cursor: i };
}

export function deleteWordBack(b: Buffer): Buffer {
  const to = wordLeft(b).cursor;
  return { text: b.text.slice(0, to) + b.text.slice(b.cursor), cursor: to };
}
export function killToEnd(b: Buffer): Buffer {
  const finish = lineEnd(b.text, b.cursor);
  // at the end of a line, remove the line break instead
  const to = finish === b.cursor && finish < b.text.length ? finish + 1 : finish;
  return { text: b.text.slice(0, b.cursor) + b.text.slice(to), cursor: b.cursor };
}
export function killToStart(b: Buffer): Buffer {
  const from = lineStart(b.text, b.cursor);
  return { text: b.text.slice(0, from) + b.text.slice(b.cursor), cursor: from };
}

/** Where the cursor is, as (row, column) of the lines the buffer splits into. */
export function position(b: Buffer): { row: number; column: number } {
  const before = b.text.slice(0, b.cursor).split("\n");
  return { row: before.length - 1, column: (before[before.length - 1] ?? "").length };
}
