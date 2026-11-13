// One palette and one set of glyphs for the whole interface, so every screen reads as one program.
export const theme = {
  accent: "#D97757", // the LARIS mark, focus, the welcome frame
  tool: "#7AA2F7",
  permission: "#7AA2F7",
  bash: "#E06C9F", // `!` shell mode
  note: "#5FB3B3", // `#` note mode
  success: "green",
  warn: "yellow",
  error: "red",
  dim: "gray",
  add: "green",
  del: "red",
} as const;

export const glyph = {
  mark: "✻",
  bullet: "●",
  branch: "⎿",
  pointer: "❯",
  todo: { pending: "☐", in_progress: "◐", done: "☒", failed: "✗", skipped: "⊘" } as Record<string, string>,
  spinner: ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"],
} as const;

/** What the footer says about a permission mode other than the default one. */
export const MODE_HINT: Record<string, { text: string; color: string }> = {
  acceptEdits: { text: "⏵⏵ accept edits on", color: "#B48EAD" },
  plan: { text: "⏸ plan mode on", color: "#5FB3B3" },
  bypass: { text: "⚠ bypass permissions on", color: "red" },
};
