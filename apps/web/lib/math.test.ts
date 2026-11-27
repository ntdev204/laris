import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import { answerSource, rehypePlugins, remarkPlugins } from "./markdown.ts";
import { prepareMath } from "./math.ts";

const render = (text: string) =>
  renderToStaticMarkup(createElement(Markdown, { remarkPlugins, rehypePlugins, skipHtml: true }, answerSource(text)));

test("bracket delimiters and a bare boxed answer become dollar math", () => {
  assert.equal(prepareMath(String.raw`so \( v = gt \) holds`), String.raw`so $v = gt$ holds`);
  assert.equal(prepareMath(String.raw`\[t = \sqrt{9}\]`), "$$\nt = \\sqrt{9}\n$$");
  assert.equal(prepareMath(String.raw`so \[t\] here`), String.raw`so $$t$$ here`);
  assert.equal(prepareMath("$$h = \\frac{1}{2}gt^2$$\n"), "$$\nh = \\frac{1}{2}gt^2\n$$\n");
  assert.equal(prepareMath("- a\n  $$x$$"), "- a\n  $$\n  x\n  $$");
  assert.equal(prepareMath("\\[\nx^2\n\\]"), "$$\nx^2\n$$");
  assert.equal(
    prepareMath(String.raw`\boxed{t = 3 \, \text{s}, v = 30 \, \text{m/s}}`),
    String.raw`$\boxed{t = 3 \, \text{s}, v = 30 \, \text{m/s}}$`,
  );
});

test("code, dollar math and unclosed delimiters are left as written", () => {
  for (const text of [
    String.raw`$h = 45 \, \text{m}$ and $$\frac{1}{2}gt^2$$`,
    String.raw`$\boxed{3}$`,
    "`\\(x\\)` and ``\\boxed{1}``",
    "```latex\n\\[x\\]\n\\boxed{1}\n```",
    String.raw`\(open and \[open and \boxed{open`,
    String.raw`a \$5 price`,
  ]) {
    assert.equal(prepareMath(text), text);
  }
});

test("an answer's LaTeX is typeset and its backslashes survive Markdown", () => {
  const html = render(String.raw`Độ cao $h = 45 \, \text{m}$.

$$t = \sqrt{9} = 3 \, \text{s}$$

\[ v = \sqrt{2 \cdot 10 \cdot 45} = 30 \]

\boxed{t = 3 \, \text{s}}

**Answer: $t = 3 \, \text{s}$** (the model's draft)`);
  assert.match(html, /class="katex"/);
  assert.match(html, /class="katex-display"/);
  assert.match(html, /<annotation encoding="application\/x-tex">h = 45 \\, \\text\{m\}<\/annotation>/);
  assert.match(html, /\\boxed\{t = 3 \\, \\text\{s\}\}/);
  assert.doesNotMatch(html, /45 , /);
  assert.match(html, /<strong>Answer: <span class="katex">/);
  assert.doesNotMatch(html, / , \\text/);
});

test("KaTeX does not run untrusted commands or raw HTML", () => {
  const html = render(String.raw`$\href{javascript:alert(1)}{x}$ <img src=x onerror=alert(1)>`);
  assert.doesNotMatch(html, /href="javascript/);
  assert.doesNotMatch(html, /<img/);
});
