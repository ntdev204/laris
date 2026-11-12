// Prompt history (this session): Up and Down, and Ctrl+R search. Kept in memory on purpose: the
// front end holds no storage logic (SR-C7); the engine's saved conversation is the record.
export class History {
  private entries: string[] = [];
  private at: number | null = null;
  private draft = "";

  constructor(initial: string[] = []) { this.entries = [...initial]; }

  add(text: string): void {
    const value = text.trim();
    if (value && this.entries[this.entries.length - 1] !== text) this.entries.push(text);
    this.at = null;
    this.draft = "";
  }

  all(): readonly string[] { return this.entries; }

  /** Older entry; `current` is kept as the draft the first time. null when there is none. */
  previous(current: string): string | null {
    if (this.entries.length === 0) return null;
    if (this.at === null) {
      this.draft = current;
      this.at = this.entries.length - 1;
    } else if (this.at > 0) {
      this.at -= 1;
    } else {
      return null;
    }
    return this.entries[this.at] ?? null;
  }

  /** Newer entry, then the draft; null when already at the draft. */
  next(): string | null {
    if (this.at === null) return null;
    if (this.at >= this.entries.length - 1) {
      this.at = null;
      return this.draft;
    }
    this.at += 1;
    return this.entries[this.at] ?? null;
  }

  reset(): void { this.at = null; this.draft = ""; }

  /** Index of the newest entry containing `query` at or before `from` (default: the newest). */
  search(query: string, from: number = this.entries.length - 1): number {
    if (!query) return -1;
    const needle = query.toLowerCase();
    for (let i = Math.min(from, this.entries.length - 1); i >= 0; i--) {
      if ((this.entries[i] ?? "").toLowerCase().includes(needle)) return i;
    }
    return -1;
  }
}
