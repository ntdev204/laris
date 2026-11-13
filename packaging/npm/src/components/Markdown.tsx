import { Box, Text } from "ink";
import type { ReactNode } from "react";
import { highlightLine, languageOf, type TokenKind } from "../highlight.js";
import { parseMarkdown, type Span } from "../markdown.js";

// no `lang` label line either: it would be copied with the code
const CODE_BG = "#262626";
const TOKEN_COLOR: Record<TokenKind, string | undefined> = {
  plain: undefined, keyword: "magenta", string: "green", comment: "gray", number: "yellow", literal: "cyan",
};

function Spans({ spans }: { spans: Span[] }): ReactNode {
  return spans.map((s, i) => (
    <Text key={i} bold={s.bold} italic={s.italic} color={s.code ? "cyan" : s.link ? "blue" : undefined} underline={Boolean(s.link)}>
      {s.text}
      {s.link ? ` (${s.link})` : ""}
    </Text>
  ));
}

export function Markdown({ text }: { text: string }) {
  const blocks = parseMarkdown(text);
  return (
    <Box flexDirection="column">
      {blocks.map((block, i) => {
        switch (block.kind) {
          case "heading":
            return (
              <Box key={i} marginTop={i > 0 ? 1 : 0}>
                <Text bold color={block.level <= 2 ? "cyan" : undefined}><Spans spans={block.spans} /></Text>
              </Box>
            );
          case "paragraph":
            return <Box key={i} marginTop={i > 0 ? 1 : 0}><Text wrap="wrap"><Spans spans={block.spans} /></Text></Box>;
          case "code": {
            const lang = languageOf(block.lang);
            return (
              // No frame, no indent, no padding: a selection copies exactly the code. The block is
              // told apart by its background, which a copy does not carry.
              <Box key={i} flexDirection="column" marginTop={i > 0 ? 1 : 0}>
                {block.lines.map((line, n) =>
                  line === "" ? (
                    <Box key={n} height={1} />
                  ) : (
                    <Text key={n}>
                      {highlightLine(lang, line).map((t, k) => (
                        <Text key={k} color={TOKEN_COLOR[t.kind]} backgroundColor={CODE_BG}>{t.text}</Text>
                      ))}
                    </Text>
                  ),
                )}
              </Box>
            );
          }
          case "list":
            return (
              <Box key={i} flexDirection="column" marginTop={i > 0 ? 1 : 0}>
                {block.items.map((item, n) => (
                  <Text key={n} wrap="wrap">
                    {" ".repeat(item.depth * 2)}{block.ordered ? `${item.number}. ` : "- "}<Spans spans={item.spans} />
                  </Text>
                ))}
              </Box>
            );
          case "quote":
            return (
              <Box key={i} marginTop={i > 0 ? 1 : 0}>
                <Text italic color="gray" wrap="wrap">{"> "}<Spans spans={block.spans} /></Text>
              </Box>
            );
          case "rule":
            return <Text key={i} dimColor>---</Text>;
          case "table": {
            const widths = block.rows[0]?.map((_, c) => Math.max(...block.rows.map((r) => (r[c] ?? "").length))) ?? [];
            return (
              <Box key={i} flexDirection="column" marginTop={i > 0 ? 1 : 0}>
                {block.rows.map((row, r) => (
                  // pipes at both ends: aligned on screen, valid Markdown when pasted, no trailing blanks
                  <Text key={r} bold={r === 0}>{"| " + row.map((cell, c) => cell.padEnd(widths[c] ?? 0)).join(" | ") + " |"}</Text>
                ))}
              </Box>
            );
          }
        }
      })}
    </Box>
  );
}
