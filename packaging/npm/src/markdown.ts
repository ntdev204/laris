// Markdown for a terminal: blocks and inline spans, tolerant of text that is still streaming
// (an unclosed code fence is an open code block, a lone `**` stays literal).
export interface Span { text: string; bold?: boolean; italic?: boolean; code?: boolean; link?: string }

export type Block =
  | { kind: "heading"; level: number; spans: Span[] }
  | { kind: "paragraph"; spans: Span[] }
  | { kind: "code"; lang: string; lines: string[]; closed: boolean }
  | { kind: "list"; ordered: boolean; items: { depth: number; spans: Span[]; number: number }[] }
  | { kind: "quote"; spans: Span[] }
  | { kind: "rule" }
  | { kind: "table"; rows: string[][] };

export function parseInline(text: string): Span[] {
  const spans: Span[] = [];
  let plain = "";
  const flush = () => {
    if (plain) spans.push({ text: plain });
    plain = "";
  };
  let i = 0;
  while (i < text.length) {
    const rest = text.slice(i);
    let m: RegExpExecArray | null;
    if ((m = /^`([^`\n]+)`/.exec(rest))) {
      flush();
      spans.push({ text: m[1] as string, code: true });
    } else if ((m = /^\*\*([^\n]+?)\*\*/.exec(rest)) || (m = /^__([^\n]+?)__/.exec(rest))) {
      flush();
      for (const inner of parseInline(m[1] as string)) spans.push({ ...inner, bold: true });
    } else if ((m = /^\*([^*\s][^*\n]*?)\*/.exec(rest)) || (m = /^_([^_\s][^_\n]*?)_(?!\w)/.exec(rest))) {
      if (i > 0 && /\w/.test(text[i - 1] as string) && rest.startsWith("_")) {
        plain += rest[0];
        i += 1;
        continue;
      }
      flush();
      for (const inner of parseInline(m[1] as string)) spans.push({ ...inner, italic: true });
    } else if ((m = /^\[([^\]\n]+)\]\(([^)\s]+)\)/.exec(rest))) {
      flush();
      spans.push({ text: m[1] as string, link: m[2] as string });
    } else {
      plain += rest[0];
      i += 1;
      continue;
    }
    i += m[0].length;
  }
  flush();
  return spans;
}

const FENCE = /^\s{0,3}(```+|~~~+)\s*([^`\s]*)/;

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  const flushPara = () => {
    if (para.length) blocks.push({ kind: "paragraph", spans: parseInline(para.join(" ")) });
    para = [];
  };
  for (let n = 0; n < lines.length; n++) {
    const line = lines[n] as string;
    const fence = FENCE.exec(line);
    if (fence) {
      flushPara();
      const marker = (fence[1] as string)[0] as string;
      const code: string[] = [];
      let closed = false;
      for (n++; n < lines.length; n++) {
        const inner = lines[n] as string;
        if (new RegExp(`^\\s{0,3}${marker}{3,}\\s*$`).test(inner)) {
          closed = true;
          break;
        }
        code.push(inner);
      }
      blocks.push({ kind: "code", lang: fence[2] as string, lines: code, closed });
      continue;
    }
    if (!line.trim()) { flushPara(); continue; }
    let m: RegExpExecArray | null;
    if ((m = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line))) {
      flushPara();
      blocks.push({ kind: "heading", level: (m[1] as string).length, spans: parseInline(m[2] as string) });
    } else if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flushPara();
      blocks.push({ kind: "rule" });
    } else if ((m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line))) {
      flushPara();
      const ordered = /\d/.test(m[2] as string);
      const item = { depth: Math.floor((m[1] as string).length / 2), spans: parseInline(m[3] as string), number: ordered ? parseInt(m[2] as string, 10) : 0 };
      const last = blocks[blocks.length - 1];
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(item);
      else blocks.push({ kind: "list", ordered, items: [item] });
    } else if ((m = /^\s{0,3}>\s?(.*)$/.exec(line))) {
      flushPara();
      const last = blocks[blocks.length - 1];
      if (last?.kind === "quote") last.spans.push({ text: " " }, ...parseInline(m[1] as string));
      else blocks.push({ kind: "quote", spans: parseInline(m[1] as string) });
    } else if (line.includes("|") && /^\s*\|.*\|\s*$/.test(line)) {
      flushPara();
      const cells = line.trim().slice(1, -1).split("|").map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue; // the header separator
      const last = blocks[blocks.length - 1];
      if (last?.kind === "table") last.rows.push(cells);
      else blocks.push({ kind: "table", rows: [cells] });
    } else {
      para.push(line.trim());
    }
  }
  flushPara();
  return blocks;
}
