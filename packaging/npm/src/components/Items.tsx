import { Box, Text } from "ink";
import { argsPreview, summarise } from "../format.js";
import type { Item } from "../state.js";
import { Markdown } from "./Markdown.js";

const MARKS: Record<string, string> = { pending: " ", in_progress: "~", done: "x", failed: "!", skipped: "-" };

export function PlanView({ source, steps }: { source: string; steps: { text?: string; status?: string }[] }) {
  return (
    <Box flexDirection="column">
      <Text dimColor>☰ plan{source ? ` (${source})` : ""}</Text>
      {steps.map((step, n) => (
        <Text key={n}>  {n + 1}. [{MARKS[step.status ?? ""] ?? " "}] {step.text ?? ""}</Text>
      ))}
    </Box>
  );
}

const NOTE_COLOR = { info: undefined, warn: "yellow", error: "red", dim: "gray" } as const;

export function ItemView({ item }: { item: Item }) {
  switch (item.kind) {
    case "user":
      return (
        <Box marginTop={1}>
          <Text color="cyan" bold>{"> "}</Text>
          <Text wrap="wrap">{item.text}</Text>
        </Box>
      );
    case "assistant":
      return (
        <Box marginTop={1}>
          <Text color="green">● </Text>
          <Box flexDirection="column" flexGrow={1}><Markdown text={item.text} /></Box>
        </Box>
      );
    case "tool":
      return (
        <Box flexDirection="column">
          <Text><Text color="magenta">● </Text><Text bold>{item.name}</Text> <Text dimColor>{argsPreview(item.arguments)}</Text></Text>
          {item.done ? <Text dimColor>  ⎿ {summarise(item.result)}</Text> : <Text dimColor>  ⎿ running…</Text>}
        </Box>
      );
    case "plan":
      return <PlanView source={item.source} steps={item.steps} />;
    case "note":
      return <Text color={NOTE_COLOR[item.level]} dimColor={item.level === "dim"}>  {item.text}</Text>;
  }
}
