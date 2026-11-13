import { Box, Text, useInput } from "ink";
import { useState } from "react";
import { diffKind, permissionTitle, toolTitle } from "../format.js";
import type { PermissionRequest, Scope } from "../protocol.js";
import { glyph, theme } from "../theme.js";

const LABEL: Record<Scope, string> = {
  once: "Yes",
  session: "Yes, and don't ask again this session",
  project: "Yes, and don't ask again in this project",
  everywhere: "Yes, and don't ask again anywhere",
};
const KEY: Record<string, Scope> = { y: "once", a: "session", p: "project", e: "everywhere" };
const DIFF_COLOR = { add: theme.add, del: theme.del, hunk: "cyan", meta: "gray", context: undefined } as const;
const MAX_DIFF = 40;

export interface PermissionProps {
  request: PermissionRequest;
  onAnswer: (decision: "allow" | "deny", scope: Scope) => void;
  /** Ctrl+C at the dialog: refuse and interrupt the turn */
  onInterrupt: () => void;
}

export function Permission({ request, onAnswer, onInterrupt }: PermissionProps) {
  const scopes = request.scopes.length ? request.scopes : (["once"] as Scope[]);
  const options: { label: string; decision: "allow" | "deny"; scope: Scope }[] = [
    ...scopes.map((scope) => ({ label: scope === "everywhere" && request.rule ? `${LABEL[scope]} (${request.rule})` : LABEL[scope], decision: "allow" as const, scope })),
    { label: "No (esc)", decision: "deny", scope: "once" },
  ];
  const [index, setIndex] = useState(0);

  useInput((input, key) => {
    if (key.ctrl && input === "c") return onInterrupt();
    if (key.escape) return onAnswer("deny", "once");
    if (key.upArrow) return setIndex((i) => (i + options.length - 1) % options.length);
    if (key.downArrow || key.tab) return setIndex((i) => (i + 1) % options.length);
    if (key.return) {
      const chosen = options[index];
      if (chosen) onAnswer(chosen.decision, chosen.scope);
      return;
    }
    const lower = input.toLowerCase();
    if (lower === "n") return onAnswer("deny", "once");
    const scope = KEY[lower];
    if (scope && scopes.includes(scope)) return onAnswer("allow", scope);
    const number = Number(input);
    const chosen = Number.isInteger(number) ? options[number - 1] : undefined;
    if (chosen) onAnswer(chosen.decision, chosen.scope);
  });

  const diff = request.diff ? request.diff.replace(/\n$/, "").split("\n") : [];
  const title = toolTitle(request.tool, request.arguments, 300);
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.permission} paddingX={1} marginTop={1}>
      <Text bold color={theme.permission}>{permissionTitle(request.tool)}</Text>
      <Box flexDirection="column" paddingLeft={2} marginTop={1}>
        <Text><Text bold>{title.name}</Text>{title.detail ? <Text>({title.detail})</Text> : null}</Text>
        {request.reason ? <Text dimColor>{request.reason}</Text> : null}
      </Box>
      {diff.length > 0 ? (
        <Box flexDirection="column" marginTop={1} paddingLeft={2}>
          {diff.slice(0, MAX_DIFF).map((line, n) => (
            <Text key={n} color={DIFF_COLOR[diffKind(line)]}>{line}</Text>
          ))}
          {diff.length > MAX_DIFF ? <Text dimColor>… {diff.length - MAX_DIFF} more lines</Text> : null}
        </Box>
      ) : null}
      <Box flexDirection="column" marginTop={1}>
        <Text>Do you want to proceed?</Text>
        {options.map((option, n) => (
          <Text key={n} color={n === index ? theme.permission : undefined}>{n === index ? `${glyph.pointer} ` : "  "}{n + 1}. {option.label}</Text>
        ))}
      </Box>
      <Text dimColor>↑↓ and Enter, or y / a / p / e / n</Text>
    </Box>
  );
}
