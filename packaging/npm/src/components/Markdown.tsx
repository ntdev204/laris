import { Box, Text } from "ink";
import type { ReactNode } from "react";
import { highlightLine, languageOf, type TokenKind } from "../highlight.js";
import { parseMarkdown, type Span } from "../markdown.js";

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
              <Box key={i} flexDirection="column" marginTop={i > 0 ? 1 : 0} borderStyle="round" borderColor="gray" paddingX={1}>
                {block.lang ? <Text dimColor>{block.lang}</Text> : null}
                {block.lines.map((line, n) => (
                  <Text key={n}>
                    {highlightLine(lang, line).map((t, k) => (
                      <Text key={k} color={TOKEN_COLOR[t.kind]}>{t.text}</Text>
                    ))}
                    {line === "" ? " " : ""}
                  </Text>
                ))}
              </Box>
            );
          }
          case "list":
            return (
              <Box key={i} flexDirection="column" marginTop={i > 0 ? 1 : 0}>
                {block.items.map((item, n) => (
                  <Box key={n} paddingLeft={item.depth * 2}>
                    <Text>{block.ordered ? `${item.number}. ` : "• "}</Text>
                    <Text wrap="wrap"><Spans spans={item.spans} /></Text>
                  </Box>
                ))}
              </Box>
            );
          case "quote":
            return (
              <Box key={i} marginTop={i > 0 ? 1 : 0}>
                <Text color="gray">▎ </Text>
                <Text italic color="gray" wrap="wrap"><Spans spans={block.spans} /></Text>
              </Box>
            );
          case "rule":
            return <Text key={i} dimColor>────────────────────</Text>;
          case "table": {
            const widths = block.rows[0]?.map((_, c) => Math.max(...block.rows.map((r) => (r[c] ?? "").length))) ?? [];
            return (
              <Box key={i} flexDirection="column" marginTop={i > 0 ? 1 : 0}>
                {block.rows.map((row, r) => (
                  <Text key={r} bold={r === 0}>{row.map((cell, c) => cell.padEnd(widths[c] ?? 0)).join("  ")}</Text>
                ))}
              </Box>
            );
          }
        }
      })}
    </Box>
  );
}
