// What `laris <args>` should do: open the Ink interface, or hand the arguments to the engine
// program (scripts, subcommands, plain mode and headless runs never need Ink).

const VALUE_FLAGS = new Set(["--resume", "--workspace", "--chat-dir", "--model-api-url", "--model-name", "--api-key-env"]);
const BOOL_FLAGS = new Set(["--allow-write"]);
const PASSTHROUGH_FLAGS = new Set(["--plain", "-p", "--print", "-h", "--help", "-V", "--version"]);

export type Plan =
  | { kind: "passthrough"; args: string[]; reason: string }
  | { kind: "ink"; engineArgs: string[]; initialInput: string | null };

export interface Env { [key: string]: string | undefined }

export function plan(argv: string[], env: Env, tty: boolean): Plan {
  const pass = (reason: string): Plan => ({ kind: "passthrough", args: argv, reason });
  if (env["LARIS_UI"] === "plain") return pass("LARIS_UI=plain");
  if (!tty) return pass("not a terminal");
  const engineArgs = ["engine", "--stdio"];
  let initialInput: string | null = null;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i] as string;
    const name = arg.split("=", 1)[0] as string;
    if (PASSTHROUGH_FLAGS.has(name)) return pass(`${name} is handled by the engine program`);
    if (!arg.startsWith("-")) return pass(`${arg} is a command of the engine program`);
    if (arg === "-c" || arg === "--continue") {
      engineArgs.push("--continue");
    } else if (VALUE_FLAGS.has(name)) {
      const inline = arg.includes("=");
      const value = inline ? arg.slice(name.length + 1) : argv[i + 1];
      if (value === undefined || (!inline && value.startsWith("-"))) {
        if (name === "--resume") {
          initialInput = "/resume"; // no id: choose from the list inside the session
          continue;
        }
        return pass(`${name} needs a value`);
      }
      if (!inline) i += 1;
      engineArgs.push(name, value);
    } else if (BOOL_FLAGS.has(arg)) {
      engineArgs.push(arg);
    } else {
      return pass(`${name} is only available in plain mode`);
    }
  }
  return { kind: "ink", engineArgs, initialInput };
}
