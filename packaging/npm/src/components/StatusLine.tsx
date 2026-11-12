import { Text } from "ink";
import { statusLine } from "../format.js";
import type { State } from "../state.js";

export function StatusLine({ state }: { state: State }) {
  const { text } = statusLine(state.line, state.mode, state.sandbox, state.pending.length);
  const hint = state.mode === "plan" ? "plan mode (read-only)" : "";
  return (
    <Text dimColor>
      {text}
      {hint ? ` · ${hint}` : ""}
      {" · shift+tab mode"}
    </Text>
  );
}
