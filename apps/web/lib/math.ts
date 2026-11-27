// LaTeX in an answer, made readable for remark-math (T291). remark-math knows `$…$` and `$$…$$`; models also write
// `\(…\)`, `\[…\]` and a bare `\boxed{…}` outside any math. Those are rewritten to dollar math so KaTeX typesets them
// and CommonMark does not eat their backslashes (`\,` would become `,`). Code, fenced or inline, and existing dollar
// math are left exactly as written; a delimiter with no closing partner stays as it is.

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const BOXED = ["\\boxed{", "\\fbox{"];

/** The text with every math span in dollar form; everything else unchanged. */
export function prepareMath(text: string): string {
  const out: string[] = [];
  let prose: string[] = [];
  let fence: string | null = null;
  const flush = () => {
    if (prose.length) out.push(rewrite(prose.join("\n")));
    prose = [];
  };
  for (const line of text.split("\n")) {
    const mark = FENCE.exec(line)?.[1];
    if (fence) {
      out.push(line);
      if (mark && mark[0] === fence[0] && mark.length >= fence.length && !line.trim().slice(mark.length)) fence = null;
    } else if (mark) {
      flush();
      out.push(line);
      fence = mark;
    } else {
      prose.push(line);
    }
  }
  flush();
  return out.join("\n");
}

/** Where `close` first occurs at or after `from`, stepping over escaped characters; -1 when it never does. */
function closing(text: string, from: number, close: string): number {
  for (let j = from; j + close.length <= text.length; j += text[j] === "\\" && !text.startsWith(close, j) ? 2 : 1) {
    if (text.startsWith(close, j)) return j;
  }
  return -1;
}

/** The index just after the brace that closes the one before `from`; -1 when it never closes. */
function braceEnd(text: string, from: number): number {
  let depth = 1;
  for (let j = from; j < text.length; j++) {
    const c = text[j];
    if (c === "\\") j++;
    else if (c === "{") depth++;
    else if (c === "}" && --depth === 0) return j + 1;
  }
  return -1;
}

/** Display math: a block of its own when it stands alone on its line(s), so it is centred; otherwise `$$…$$` in the
 *  line, which remark-math sets inline. `before` is the text written so far, `after` where the source goes on. */
function display(before: string, inner: string, text: string, after: number): string {
  const indent = /(?:^|\n)([ \t]*)$/.exec(before);
  const rest = text.slice(after);
  if (!indent || !/^[ \t]*(?:\n|$)/.test(rest)) return `$$${inner}$$`;
  const pad = indent[1];
  return `$$\n${pad}${inner.trim().split("\n").map((l) => l.trim()).join(`\n${pad}`)}\n${pad}$$`;
}

function rewrite(text: string): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === "`") {
      const ticks = /^`+/.exec(text.slice(i))![0];
      const end = text.indexOf(ticks, i + ticks.length);
      const stop = end < 0 ? i + ticks.length : end + ticks.length;
      out += text.slice(i, stop);
      i = stop;
      continue;
    }
    if (c === "\\" && text[i + 1] === "$") {
      out += "\\$";
      i += 2;
      continue;
    }
    if (c === "$") {
      const marker = text[i + 1] === "$" ? "$$" : "$";
      const end = closing(text, i + marker.length, marker);
      if (end > i + marker.length) {
        const inner = text.slice(i + marker.length, end);
        out += marker === "$$" ? display(out, inner, text, end + 2) : `$${inner}$`;
        i = end + marker.length;
        continue;
      }
    }
    if (c === "\\" && (text[i + 1] === "(" || text[i + 1] === "[")) {
      const close = text[i + 1] === "(" ? "\\)" : "\\]";
      const end = closing(text, i + 2, close);
      if (end > i + 2) {
        const inner = text.slice(i + 2, end);
        out += close === "\\)" ? `$${inner.trim()}$` : display(out, inner, text, end + 2);
        i = end + 2;
        continue;
      }
    }
    const boxed = BOXED.find((b) => text.startsWith(b, i));
    if (boxed) {
      const end = braceEnd(text, i + boxed.length);
      if (end > 0) {
        out += "$" + text.slice(i, end) + "$";
        i = end;
        continue;
      }
    }
    out += c;
    i++;
  }
  return out;
}
