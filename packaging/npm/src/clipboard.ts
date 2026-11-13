// Copy text to the user's clipboard, exactly as given. A terminal selection copies whatever
// characters are on the screen, so `/copy` hands over the original text instead: no frame, no
// gutter, no padding. Native tools first (they work with every terminal); OSC 52 when there is
// none, or over SSH where a native tool would fill the wrong machine's clipboard.
import { spawn } from "node:child_process";

export type Env = Record<string, string | undefined>;
export type Writer = { write(data: string): unknown };
export type Run = (cmd: string, args: string[], input: string) => Promise<boolean>;

/** The terminal escape that sets the clipboard (OSC 52), wrapped for tmux when needed. */
export function osc52(text: string, env: Env = process.env): string {
  const seq = `\x1b]52;c;${Buffer.from(text, "utf8").toString("base64")}\x07`;
  if (env["TMUX"]) return `\x1bPtmux;${seq.replace(/\x1b/g, "\x1b\x1b")}\x1b\\`;
  return seq;
}

export function nativeTools(platform: NodeJS.Platform, env: Env): Array<[string, string[]]> {
  if (platform === "darwin") return [["pbcopy", []]];
  if (platform === "win32") return [["clip.exe", []]];
  const tools: Array<[string, string[]]> = [];
  if (env["WAYLAND_DISPLAY"]) tools.push(["wl-copy", []]);
  if (env["DISPLAY"]) tools.push(["xclip", ["-selection", "clipboard"]], ["xsel", ["--clipboard", "--input"]]);
  tools.push(["clip.exe", []]); // WSL
  return tools;
}

const run: Run = (cmd, args, input) =>
  new Promise((resolve) => {
    try {
      const child = spawn(cmd, args, { stdio: ["pipe", "ignore", "ignore"] });
      child.on("error", () => resolve(false));
      child.on("close", (code) => resolve(code === 0));
      child.stdin.on("error", () => undefined);
      child.stdin.end(input);
    } catch {
      resolve(false);
    }
  });

export interface CopyOptions {
  env?: Env;
  platform?: NodeJS.Platform;
  out?: Writer;
  runner?: Run;
}

/** Returns how it was copied: "native", "osc52" or null when nothing could be done. */
export async function copyText(text: string, opts: CopyOptions = {}): Promise<"native" | "osc52" | null> {
  const env = opts.env ?? process.env;
  const remote = Boolean(env["SSH_CONNECTION"] || env["SSH_TTY"]);
  if (!remote) {
    for (const [cmd, args] of nativeTools(opts.platform ?? process.platform, env)) {
      if (await (opts.runner ?? run)(cmd, args, text)) return "native";
    }
  }
  const out = opts.out ?? (process.stdout.isTTY ? process.stdout : null);
  if (!out) return null;
  out.write(osc52(text, env));
  return "osc52";
}
