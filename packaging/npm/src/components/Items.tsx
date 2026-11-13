import { Box, Text } from "ink";
import { summarise, toolTitle } from "../format.js";
import type { Item } from "../state.js";
import { glyph, theme } from "../theme.js";
import { Markdown } from "./Markdown.js";

type Step = { text?: string; status?: string };

/** The task list, drawn like a checklist: done items struck out, the current one bold. */
export function PlanView({ source, steps }: { source: string; steps: Step[] }) {
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text><Text color={theme.tool}>{glyph.bullet} </Text><Text bold>Update Todos</Text>{source ? <Text dimColor> ({source})</Text> : null}</Text>
      {steps.map((step, n) => {
        const status = step.status ?? "pending";
        const done = status === "done" || status === "skipped";
        return (
          <Text key={n}>
            <Text dimColor>{n === 0 ? `  ${glyph.branch}  ` : "     "}</Text>
            <Text color={status === "failed" ? theme.error : status === "in_progress" ? theme.accent : undefined} dimColor={done} strikethrough={done} bold={status === "in_progress"}>
              {glyph.todo[status] ?? glyph.todo["pending"]} {step.text ?? ""}
            </Text>
          </Text>
        );
      })}
    </Box>
  );
}

const NOTE_COLOR = { info: undefined, warn: theme.warn, error: theme.error, dim: theme.dim } as const;

function failed(result: unknown): boolean {
  return Boolean(result && typeof result === "object" && "error" in (result as Record<string, unknown>));
}

export function ItemView({ item }: { item: Item }) {
  switch (item.kind) {
    case "user":
      return (
        <Box marginTop={1}>
          <Text dimColor>{"> "}</Text>
          <Text wrap="wrap" color="gray">{item.text}</Text>
        </Box>
      );
    case "assistant":
      return (
        <Box marginTop={1}>
          <Text>{glyph.bullet} </Text>
          <Box flexDirection="column" flexGrow={1}><Markdown text={item.text} /></Box>
        </Box>
      );
    case "tool": {
      const title = toolTitle(item.name, item.arguments);
      const bad = item.done && failed(item.result);
      return (
        <Box flexDirection="column" marginTop={1}>
          <Text>
            <Text color={!item.done ? theme.dim : bad ? theme.error : theme.success}>{glyph.bullet} </Text>
            <Text bold>{title.name}</Text>
            {title.detail ? <Text>({title.detail})</Text> : null}
          </Text>
          <Text color={bad ? theme.error : undefined} dimColor={!bad}>  {glyph.branch}  {item.done ? summarise(item.result) : "Running…"}</Text>
        </Box>
      );
    }
    case "plan":
      return <PlanView source={item.source} steps={item.steps} />;
    case "note":
      return <Text color={NOTE_COLOR[item.level]} dimColor={item.level === "dim"}>  {glyph.branch}  {item.text}</Text>;
  }
}
