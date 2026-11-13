// The frame a session opens with: the mark, where it runs, and how to begin.
import os from "node:os";
import { Box, Text } from "ink";
import { hostOf, shortPath } from "../format.js";
import type { Ready } from "../protocol.js";
import { glyph, theme } from "../theme.js";

const LOGO = ["▐▌    ", "▐▌    ", "▐▙▄▄▖ "];

export function Welcome({ ready, columns }: { ready: Ready; columns: number }) {
  const wide = columns >= 84;
  const width = Math.max(40, Math.min(columns, 108));
  const where = shortPath(ready.cwd, os.homedir(), wide ? 34 : width - 8);
  const server = ready.server ? hostOf(ready.server) : "no server configured";
  const identity = (
    <Box flexDirection="column" alignItems={wide ? "center" : "flex-start"} width={wide ? 40 : undefined}>
      <Text bold>Welcome back!</Text>
      <Box flexDirection="column" marginY={1}>
        {LOGO.map((line, n) => <Text key={n} color={theme.accent}>{line}</Text>)}
      </Box>
      <Text dimColor>{server}</Text>
      <Text dimColor>{where}</Text>
    </Box>
  );
  const tips = (
    <Box flexDirection="column" flexGrow={1}>
      <Text bold color={theme.accent}>Tips for getting started</Text>
      <Text>Ask about your documents, or describe a task</Text>
      <Text><Text color={theme.accent}>/help</Text> lists the commands · <Text color={theme.accent}>@</Text> mentions a file</Text>
      <Text><Text color={theme.accent}>!</Text> runs a shell command · <Text color={theme.accent}>#</Text> saves a note</Text>
      <Box marginTop={1} flexDirection="column">
        <Text bold color={theme.accent}>This session</Text>
        <Text dimColor>session {ready.session.slice(0, 8)} · {ready.mode} mode</Text>
      </Box>
    </Box>
  );
  return (
    <Box flexDirection="column" width={width} borderStyle="round" borderColor={theme.accent} paddingX={1}>
      <Text><Text color={theme.accent} bold>{glyph.mark} LARIS</Text> <Text dimColor>v{ready.engine}</Text></Text>
      <Box flexDirection={wide ? "row" : "column"} marginTop={1}>
        {identity}
        {wide ? (
          <Box borderStyle="single" borderColor={theme.accent} borderTop={false} borderBottom={false} borderRight={false} paddingLeft={2} flexGrow={1}>
            {tips}
          </Box>
        ) : (
          <Box marginTop={1}>{tips}</Box>
        )}
      </Box>
    </Box>
  );
}
