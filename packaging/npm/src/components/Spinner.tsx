import { Text } from "ink";
import { useEffect, useState } from "react";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function Spinner({ label = "Working", hint = "esc to interrupt" }: { label?: string; hint?: string }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 120);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.floor((tick * 120) / 1000);
  return (
    <Text>
      <Text color="cyan">{FRAMES[tick % FRAMES.length]}</Text> {label}… <Text dimColor>({seconds}s · {hint})</Text>
    </Text>
  );
}
