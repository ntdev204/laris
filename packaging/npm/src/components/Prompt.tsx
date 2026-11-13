import { Box, Text, useInput, usePaste, useWindowSize } from "ink";
import { useEffect, useRef, useState } from "react";
import * as ed from "../input/editor.js";
import { applyCompletion, currentTrigger } from "../input/completion.js";
import { History } from "../input/history.js";
import type { CompletionItem } from "../protocol.js";
import { glyph, theme } from "../theme.js";

const PASTE_LINES = 6;
const PASTE_CHARS = 1000;
const PLACEHOLDER = /\[Pasted text #(\d+) \+\d+ lines\]/g;

export interface PromptProps {
  history: History;
  busy: boolean;
  /** disabled while a dialog has the keys */
  active: boolean;
  completion: { id: string; items: CompletionItem[] } | null;
  requestCompletion: (trigger: "/" | "@", text: string) => string;
  onSubmit: (text: string) => void;
  onInterrupt: () => void;
  onCycleMode: () => void;
  onCtrlC: () => void;
  onExit: () => void;
  /** a key other than Ctrl+C was pressed: the exit warning is over */
  onOtherKey: () => void;
  /** terminal width (tests); the real one otherwise */
  columns?: number;
}

const SHORTCUTS: string[][] = [
  ["! for shell mode", "/ for commands", "shift+tab to cycle modes"],
  ["# to save a note", "@ for file paths", "esc to interrupt"],
  ["\\⏎ or shift+⏎ for a new line", "ctrl+r to search history", "ctrl+c twice to exit"],
];

export function Prompt(p: PromptProps) {
  const [buffer, setBuffer] = useState<ed.Buffer>(ed.empty());
  const [menuId, setMenuId] = useState<string | null>(null);
  const [selected, setSelected] = useState(0);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [search, setSearch] = useState<{ query: string; at: number } | null>(null);
  const pastes = useRef(new Map<number, string>());
  const [help, setHelp] = useState(false);
  const size = useWindowSize();
  const columns = Math.max(20, p.columns ?? size.columns ?? 80);

  // Ask the engine for completions whenever the word under the cursor changes.
  useEffect(() => {
    const trigger = currentTrigger(buffer.text, buffer.cursor);
    if (!trigger || dismissed === buffer.text) {
      setMenuId(null);
      return;
    }
    setSelected(0);
    setMenuId(p.requestCompletion(trigger.trigger, trigger.text));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buffer.text, buffer.cursor, dismissed]);

  const served = menuId && p.completion?.id === menuId ? p.completion.items : [];
  const word = /^\/(\S*)$/.exec(buffer.text)?.[1];
  const local = word !== undefined && "copy".startsWith(word) && !served.some((i) => i.value === "copy");
  // `/copy` is the front end's own command (it talks to the terminal's clipboard)
  const items = (local ? [...served, { value: "copy", description: "copy the last answer as plain text" }] : served).slice(0, 8);
  const trigger = currentTrigger(buffer.text, buffer.cursor);

  const expand = (text: string): string =>
    text.replace(PLACEHOLDER, (whole, n: string) => pastes.current.get(Number(n)) ?? whole);

  const submit = (): void => {
    const text = expand(buffer.text).trim();
    if (!text) return;
    p.history.add(buffer.text.trim());
    pastes.current.clear();
    setBuffer(ed.empty());
    setDismissed(null);
    p.onSubmit(text);
  };

  usePaste((text) => {
    if (!p.active) return;
    const clean = text.replace(/\r\n?/g, "\n");
    const lines = clean.split("\n").length;
    if (lines > PASTE_LINES || clean.length > PASTE_CHARS) {
      const n = pastes.current.size + 1;
      pastes.current.set(n, clean);
      setBuffer((b) => ed.insert(b, `[Pasted text #${n} +${lines} lines]`));
    } else {
      setBuffer((b) => ed.insert(b, clean));
    }
  }, { isActive: p.active });

  useInput((input, key) => {
    if (!(key.ctrl && input === "c")) p.onOtherKey();
    if (input === "?" && !buffer.text && !search && !key.ctrl && !key.meta) return setHelp((shown) => !shown);
    if (help) setHelp(false);

    if (search) {
      if (key.escape || (key.ctrl && input === "c")) return setSearch(null);
      if (key.return) {
        const entry = p.history.all()[search.at];
        if (entry !== undefined) setBuffer(ed.fromText(entry));
        return setSearch(null);
      }
      if (key.ctrl && input === "r") {
        const at = p.history.search(search.query, search.at - 1);
        return setSearch({ query: search.query, at: at >= 0 ? at : search.at });
      }
      if (key.backspace || key.delete) {
        const query = search.query.slice(0, -1);
        return setSearch({ query, at: p.history.search(query) });
      }
      if (input && !key.ctrl && !key.meta) {
        const query = search.query + input;
        return setSearch({ query, at: p.history.search(query) });
      }
      return;
    }

    if (key.ctrl && input === "c") {
      if (buffer.text) {
        setBuffer(ed.empty());
        pastes.current.clear();
        p.history.reset();
      }
      return p.onCtrlC();
    }
    if (key.ctrl && input === "d") {
      if (!buffer.text) p.onExit();
      return;
    }
    if (key.ctrl && input === "r") return setSearch({ query: "", at: -1 });
    if (key.tab && key.shift) return p.onCycleMode();
    if (key.escape) {
      if (items.length) return setDismissed(buffer.text);
      if (p.busy) p.onInterrupt();
      return;
    }
    if (key.tab) {
      const chosen = items[selected];
      if (chosen && trigger) {
        const next = applyCompletion(buffer.text, buffer.cursor, trigger, chosen.value);
        setDismissed(next.text);
        setBuffer({ text: next.text, cursor: next.cursor });
      }
      return;
    }
    if (key.return || input === "\n") {
      if (key.shift || key.meta || input === "\n") return setBuffer((b) => ed.insert(b, "\n"));
      const before = buffer.text.slice(0, buffer.cursor);
      if (before.endsWith("\\")) {
        return setBuffer({ text: before.slice(0, -1) + "\n" + buffer.text.slice(buffer.cursor), cursor: buffer.cursor });
      }
      return submit();
    }
    if (key.upArrow) {
      if (items.length) return setSelected((s) => (s + items.length - 1) % items.length);
      if (!ed.onFirstLine(buffer)) return setBuffer(ed.up(buffer));
      const older = p.history.previous(buffer.text);
      return older === null ? undefined : setBuffer(ed.fromText(older));
    }
    if (key.downArrow) {
      if (items.length) return setSelected((s) => (s + 1) % items.length);
      if (!ed.onLastLine(buffer)) return setBuffer(ed.down(buffer));
      const newer = p.history.next();
      return newer === null ? undefined : setBuffer(ed.fromText(newer));
    }
    if (key.leftArrow) return setBuffer(key.ctrl || key.meta ? ed.wordLeft(buffer) : ed.left(buffer));
    if (key.rightArrow) return setBuffer(key.ctrl || key.meta ? ed.wordRight(buffer) : ed.right(buffer));
    if (key.home || (key.ctrl && input === "a")) return setBuffer(ed.home(buffer));
    if (key.end || (key.ctrl && input === "e")) return setBuffer(ed.end(buffer));
    if (key.backspace || (key.ctrl && input === "h")) return setBuffer(ed.backspace(buffer));
    if (key.delete) return setBuffer(ed.del(buffer));
    if (key.ctrl && input === "w") return setBuffer(ed.deleteWordBack(buffer));
    if (key.ctrl && input === "k") return setBuffer(ed.killToEnd(buffer));
    if (key.ctrl && input === "u") return setBuffer(ed.killToStart(buffer));
    if (key.ctrl || key.meta || !input) return;
    setBuffer(ed.insert(buffer, input.replace(/\r\n?/g, "\n")));
  }, { isActive: p.active });

  if (!p.active) return null; // a dialog has the screen; the draft is kept for when it closes
  const rule = "─".repeat(columns);
  if (search) {
    const match = search.at >= 0 ? p.history.all()[search.at] : undefined;
    return (
      <Box flexDirection="column">
        <Text dimColor>{rule}</Text>
        <Text><Text color={theme.accent}>search history: </Text><Text bold>{search.query}</Text>{match === undefined && search.query ? <Text color={theme.error}> no match</Text> : null}</Text>
        <Text dimColor>{match ?? " "}</Text>
        <Text dimColor>{rule}</Text>
        <Text dimColor>  Enter uses it · Ctrl+R older · Esc cancels</Text>
      </Box>
    );
  }

  const lines = buffer.text.split("\n");
  const at = ed.position(buffer);
  // `!` runs a shell command and `#` saves a note: the prompt says which one this line is
  const kind = buffer.text.startsWith("!") ? "shell" : buffer.text.startsWith("#") ? "note" : "chat";
  const tint = kind === "shell" ? theme.bash : kind === "note" ? theme.note : undefined;
  const mark = kind === "shell" ? "!" : kind === "note" ? "#" : ">";
  const placeholder = p.busy ? "Type the next message; it is sent when this turn ends" : 'Try "summarise the documents in this folder"';
  const widest = items.reduce((n, item) => Math.max(n, item.value.replace(/^[/@]/, "").length), 0);
  return (
    <Box flexDirection="column">
      <Text color={tint} dimColor={!tint}>{rule}</Text>
      {lines.map((line, row) => (
        <Text key={row}>
          <Text color={tint} dimColor={!tint}>{row === 0 ? `${mark} ` : "  "}</Text>
          {row === at.row ? (
            <>
              {line.slice(0, at.column)}
              <Text inverse>{line[at.column] ?? " "}</Text>
              {line.slice(at.column + 1)}
              {!buffer.text ? <Text dimColor>{placeholder}</Text> : null}
            </>
          ) : (
            line
          )}
        </Text>
      ))}
      <Text color={tint} dimColor={!tint}>{rule}</Text>
      {kind !== "chat" ? <Text color={tint}>  {kind === "shell" ? "! shell mode: the command runs in this folder" : "# note mode: the line is saved to memory"}</Text> : null}
      {items.length > 0 ? (
        <Box flexDirection="column" paddingLeft={2}>
          {items.map((item, n) => {
            const name = item.value.replace(/^[/@]/, "");
            return (
              <Text key={item.value} color={n === selected ? theme.accent : undefined}>
                {n === selected ? `${glyph.pointer} ` : "  "}{trigger?.trigger}{name}{item.description ? <Text dimColor>{" ".repeat(widest - name.length + 3)}{item.description}</Text> : null}
              </Text>
            );
          })}
          <Text dimColor>  Tab inserts · ↑↓ choose · Esc closes</Text>
        </Box>
      ) : null}
      {help && items.length === 0 ? (
        <Box flexDirection="column" paddingLeft={2}>
          {SHORTCUTS.map((row, n) => (
            <Box key={n}>
              {row.map((cell) => <Box key={cell} width={Math.max(24, Math.floor((columns - 4) / 3))}><Text dimColor>{cell}</Text></Box>)}
            </Box>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}
