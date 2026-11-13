// The line under the prompt: what a key does on the left, the state of the session on the right.
import { Box, Text } from "ink";
import { statusLine } from "../format.js";
import type { State } from "../state.js";
import { MODE_HINT } from "../theme.js";

export function StatusLine({ state, columns = 100 }: { state: State; columns?: number }) {
  const { text } = statusLine(state.line, state.mode, state.sandbox, state.pending.length);
  const mode = MODE_HINT[state.mode];
  const left = mode ? (
    <Text color={mode.color}>{mode.text} <Text dimColor>(shift+tab to cycle)</Text></Text>
  ) : (
    <Text dimColor>? for shortcuts</Text>
  );
  return (
    <Box flexDirection={columns < 84 ? "column" : "row"} justifyContent="space-between" paddingX={2} width={columns}>
      {left}
      <Text dimColor wrap="wrap">{text}</Text>
    </Box>
  );
}
