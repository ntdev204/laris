import { Box, Static, Text, useApp, useWindowSize } from "ink";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { EngineClient } from "./engine-client.js";
import { History } from "./input/history.js";
import { ItemView, PlanView } from "./components/Items.js";
import { Login } from "./components/Login.js";
import { Permission } from "./components/Permission.js";
import { Prompt } from "./components/Prompt.js";
import { Spinner } from "./components/Spinner.js";
import { StatusLine } from "./components/StatusLine.js";
import { Welcome } from "./components/Welcome.js";
import { theme } from "./theme.js";
import type { Ready, Scope } from "./protocol.js";
import { initialState, isFinal, reduce, type Item, type State } from "./state.js";

type Row = { kind: "header"; ready: Ready } | Item;

export interface AppProps {
  client: EngineClient;
  /** called once with the final state when the session is over */
  onFinish: (state: State) => void;
  /** how long the "press Ctrl+C again" window stays open */
  exitWindowMs?: number;
  /** a first line to send once the engine is ready (for `laris --resume` without an id) */
  initialInput?: string | null;
  /** terminal width (tests); the real one otherwise */
  columns?: number;
}

export function App({ client, onFinish, exitWindowMs = 2000, initialInput = null, columns: fixedColumns }: AppProps) {
  const app = useApp();
  const size = useWindowSize();
  const columns = Math.max(20, fixedColumns ?? size.columns ?? 80);
  const [state, dispatch] = useReducer(reduce, undefined, initialState);
  const [armed, setArmed] = useState(false);
  const history = useRef(new History());
  const stopping = useRef(false);
  const counter = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finished = useRef(false);

  useEffect(() => {
    client.onEvent((event) => dispatch({ kind: "event", event }));
    client.onProblem((message) => dispatch({ kind: "note", level: "warn", text: `engine sent something unreadable: ${message}` }));
    client.onExit((code, stderrTail) => dispatch({ kind: "closed", code, stderrTail, clean: stopping.current || code === 0 }));
  }, [client]);

  // A version mismatch ends the session at once; the engine is stopped.
  useEffect(() => {
    if (state.phase !== "closed" || finished.current) return;
    finished.current = true;
    void client.stop(500).then(() => {
      onFinish(state);
      app.exit();
    });
  }, [state, client, app, onFinish]);

  const exit = useCallback(() => {
    stopping.current = true;
    void client.stop().then(() => undefined);
  }, [client]);

  const interrupt = useCallback(() => client.send({ type: "interrupt" }), [client]);

  const submit = useCallback(
    (text: string) => {
      if (text === "/") return dispatch({ kind: "note", level: "info", text: "Type /help for the list of commands." });
      dispatch({ kind: "sent", text });
      if (text.startsWith("/")) {
        const name = text.slice(1).split(/\s+/, 1)[0] ?? "";
        const args = text.slice(1 + name.length).trim();
        client.send({ type: "command", name, args });
      } else {
        client.send({ type: "user_message", text });
      }
    },
    [client],
  );

  const answer = useCallback(
    (decision: "allow" | "deny", scope: Scope) => {
      if (!state.permission) return;
      client.send({ type: "permission_response", id: state.permission.id, decision, scope });
      dispatch({ kind: "answered" });
    },
    [client, state.permission],
  );

  const ctrlC = useCallback(() => {
    if (armed) return exit();
    if (state.permission) answer("deny", "once");
    if (state.busy) interrupt();
    setArmed(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setArmed(false), exitWindowMs);
    timer.current.unref?.();
  }, [armed, state.permission, state.busy, answer, interrupt, exit, exitWindowMs]);

  const disarm = useCallback(() => setArmed((was) => (was ? false : was)), []);

  const requestCompletion = useCallback(
    (trigger: "/" | "@", text: string) => {
      const id = `c${++counter.current}`;
      client.send({ type: "complete", id, trigger, text });
      return id;
    },
    [client],
  );

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const sentFirst = useRef(false);
  useEffect(() => {
    if (state.phase === "running" && initialInput && !sentFirst.current) {
      sentFirst.current = true;
      submit(initialInput);
    }
  }, [state.phase, initialInput, submit]);

  const firstOpen = state.items.findIndex((item) => !isFinal(item));
  const cut = firstOpen < 0 ? state.items.length : firstOpen;
  const settled = state.items.slice(0, cut);
  const live = state.items.slice(cut);
  // Ink keeps one <Static>: the header and every finished item go through it, once each
  const rows: Row[] = [...(state.ready ? [{ kind: "header" as const, ready: state.ready }] : []), ...settled];

  if (state.phase === "starting") return <Text dimColor>Starting LARIS…</Text>;
  if (state.phase === "login" && state.login) {
    return (
      <>
        <Static items={settled}>{(row) => <ItemView key={row.id} item={row} />}</Static>
        <Login
          request={state.login}
          busy={state.loginBusy}
          onAnswer={(answer) => {
            dispatch({ kind: "login_sent" });
            client.send({ type: "login", ...answer });
          }}
          onExit={exit}
        />
      </>
    );
  }
  return (
    <>
      <Static items={rows}>
        {(row) => (row.kind === "header" ? <Welcome key="header" ready={row.ready} columns={columns} /> : <ItemView key={row.id} item={row} />)}
      </Static>
      <Box flexDirection="column" width={columns}>
        {live.map((item) => <ItemView key={item.id} item={item} />)}
        {state.plan ? <PlanView source={state.plan.source} steps={state.plan.steps} /> : null}
        {state.fatal ? <Text color={theme.error}>{state.fatal}</Text> : null}
        {state.busy && !state.permission && state.phase === "running" ? (
          <Box marginTop={1}><Spinner tokens={state.usage?.tokens ?? null} /></Box>
        ) : null}
        {state.pending.map((text, n) => <Text key={n} dimColor>  ⧗ queued: {text.slice(0, 100)}</Text>)}
        {state.permission ? <Permission request={state.permission} onAnswer={answer} onInterrupt={ctrlC} /> : null}
        {state.phase === "running" ? (
          <Box marginTop={1} flexDirection="column">
            <Prompt
              history={history.current}
              busy={state.busy}
              active={!state.permission}
              completion={state.completion}
              requestCompletion={requestCompletion}
              onSubmit={submit}
              onInterrupt={interrupt}
              onCycleMode={() => client.send({ type: "set_mode", mode: "next" })}
              onCtrlC={ctrlC}
              onExit={exit}
              onOtherKey={disarm}
              columns={columns}
            />
            {armed ? <Text color={theme.warn}>  Press Ctrl+C again to exit</Text> : null}
            {state.permission ? null : <StatusLine state={state} columns={columns} />}
          </Box>
        ) : null}
      </Box>
    </>
  );
}
