// One palette for the whole interface, so every screen reads as one program.
export const theme = {
  accent: "#D97757", // the LARIS mark, borders in focus, the prompt
  user: "gray",
  assistant: "white",
  tool: "#7AA2F7",
  success: "green",
  warn: "yellow",
  error: "red",
  dim: "gray",
  add: "green",
  del: "red",
  mode: { default: "gray", acceptEdits: "#B48EAD", plan: "#5FB3B3", bypass: "red" } as Record<string, string>,
} as const;
