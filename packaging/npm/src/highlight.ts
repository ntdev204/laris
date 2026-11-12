// A small syntax highlighter for fenced code (no dependency): comments, strings, numbers, keywords.
export type TokenKind = "plain" | "keyword" | "string" | "comment" | "number" | "literal";
export interface Token { text: string; kind: TokenKind }

const words = (s: string): Set<string> => new Set(s.split(/\s+/).filter(Boolean));

const KEYWORDS: Record<string, Set<string>> = {
  python: words("and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case"),
  js: words("async await break case catch class const continue debugger default delete do else export extends finally for from function if import in instanceof let new of return static super switch this throw try typeof var void while with yield interface type enum implements public private protected readonly namespace declare abstract as satisfies"),
  bash: words("if then else elif fi for while until do done case esac function in select time export local return exit cd echo"),
  rust: words("as async await break const continue crate dyn else enum extern fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait type unsafe use where while"),
  go: words("break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var"),
  c: words("auto break case char const continue default do double else enum extern float for goto if inline int long register return short signed sizeof static struct switch typedef union unsigned void volatile while class namespace template typename public private protected new delete using"),
  sql: words("select from where insert into values update set delete create table drop alter join left right inner outer on group by order having limit as and or not null primary key index distinct union"),
};
const LITERALS = words("True False None true false null undefined NaN nil");

const ALIASES: Record<string, string> = {
  py: "python", python3: "python", js: "js", javascript: "js", jsx: "js", ts: "js", tsx: "js", typescript: "js", mjs: "js",
  sh: "bash", shell: "bash", zsh: "bash", bash: "bash", rs: "rust", rust: "rust", go: "go", golang: "go",
  c: "c", h: "c", cpp: "c", "c++": "c", java: "c", cs: "c", sql: "sql", json: "json", yaml: "yaml", yml: "yaml", toml: "yaml",
};

export function languageOf(info: string): string | null {
  return ALIASES[info.trim().toLowerCase().split(/\s+/)[0] ?? ""] ?? null;
}

function lineComment(lang: string): string | null {
  if (lang === "python" || lang === "bash" || lang === "yaml") return "#";
  if (lang === "sql") return "--";
  if (lang === "json") return null;
  return "//";
}

/** Tokens of one line (code blocks are highlighted line by line, which is exact for what matters here). */
export function highlightLine(lang: string | null, line: string): Token[] {
  if (!lang) return [{ text: line, kind: "plain" }];
  const out: Token[] = [];
  const comment = lineComment(lang);
  const keywords = KEYWORDS[lang];
  let i = 0;
  let plain = "";
  const flush = () => {
    if (plain) out.push({ text: plain, kind: "plain" });
    plain = "";
  };
  while (i < line.length) {
    const rest = line.slice(i);
    if (comment && rest.startsWith(comment)) {
      flush();
      out.push({ text: rest, kind: "comment" });
      return out;
    }
    const ch = line[i] as string;
    if (ch === '"' || ch === "'" || (ch === "`" && lang === "js")) {
      let j = i + 1;
      while (j < line.length && line[j] !== ch) j += line[j] === "\\" ? 2 : 1;
      flush();
      out.push({ text: line.slice(i, Math.min(j + 1, line.length)), kind: lang === "json" && line.slice(j + 1).trimStart().startsWith(":") ? "keyword" : "string" });
      i = Math.min(j + 1, line.length);
      continue;
    }
    const num = /^(0x[\da-fA-F]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)/.exec(rest);
    if (num && !/\w/.test(line[i - 1] ?? "")) {
      flush();
      out.push({ text: num[1] as string, kind: "number" });
      i += (num[1] as string).length;
      continue;
    }
    const word = /^[A-Za-z_$][\w$]*/.exec(rest);
    if (word) {
      const w = word[0];
      if (LITERALS.has(w)) {
        flush();
        out.push({ text: w, kind: "literal" });
      } else if (keywords?.has(lang === "sql" ? w.toLowerCase() : w)) {
        flush();
        out.push({ text: w, kind: "keyword" });
      } else {
        plain += w;
      }
      i += w.length;
      continue;
    }
    plain += ch;
    i += 1;
  }
  flush();
  return out;
}
