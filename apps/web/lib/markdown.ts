// The Markdown of an answer (T291): GitHub-flavoured Markdown with LaTeX math typeset by KaTeX. KaTeX runs without
// `trust`, so `\href`, `\url` and `\includegraphics` stay inert; a formula it cannot parse is shown as written.
import type { Options } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { prepareMath } from "./math.ts";

export const remarkPlugins: Options["remarkPlugins"] = [remarkGfm, remarkMath];
export const rehypePlugins: Options["rehypePlugins"] = [
  [rehypeKatex, { throwOnError: false, strict: "ignore", trust: false, output: "htmlAndMathml" }],
];

/** The text react-markdown is given for an answer. */
export function answerSource(text: string): string {
  return prepareMath(text);
}
