import { Text } from "ink";
import { useEffect, useState } from "react";
import { compactNumber } from "../format.js";
import { glyph, theme } from "../theme.js";

/** `✻ Working… (12s · ↑ 1.2k tokens · esc to interrupt)` while a turn runs. */
export function Spinner({ label = "Working", hint = "esc to interrupt", tokens = null }: { label?: string; hint?: string; tokens?: number | null }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 120);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.floor((tick * 120) / 1000);
  return (
    <Text>
      <Text color={theme.accent}>{glyph.spinner[tick % glyph.spinner.length]} {label}…</Text>
      <Text dimColor> ({seconds}s{tokens ? ` · ${compactNumber(tokens)} tokens` : ""} · {hint})</Text>
    </Text>
  );
}
