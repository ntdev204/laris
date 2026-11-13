// The screen before a session: what the engine still needs (a server address, a certificate a
// person has to confirm, an API key). The engine decides; this only asks and sends the answer.
import { Box, Text, useInput, usePaste } from "ink";
import { useEffect, useState } from "react";
import type { LoginRequired } from "../protocol.js";
import { glyph, theme } from "../theme.js";

export interface LoginProps {
  request: LoginRequired;
  /** an answer was sent and the engine is checking it */
  busy: boolean;
  onAnswer: (answer: { key?: string; server?: string; trust?: boolean }) => void;
  onExit: () => void;
}

const TITLE: Record<LoginRequired["reason"], string> = {
  no_server: "Connect to a LARIS server",
  untrusted_certificate: "Check the server's certificate",
  certificate_mismatch: "The server's certificate is not the expected one",
  no_key: "Sign in",
  rejected: "Sign in",
  invalid: "Sign in",
};

function Field({ label, value, secret, placeholder }: { label: string; value: string; secret?: boolean; placeholder: string }) {
  const shown = secret ? "•".repeat(value.length) : value;
  return (
    <Box>
      <Text color={theme.accent}>{label} </Text>
      {value ? <Text>{shown}</Text> : <Text dimColor>{placeholder}</Text>}
      <Text inverse> </Text>
    </Box>
  );
}

export function Login({ request, busy, onAnswer, onExit }: LoginProps) {
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState("");
  const kind = request.reason === "no_server" ? "server" : request.reason === "untrusted_certificate" ? "trust" : request.reason === "certificate_mismatch" ? "stop" : "key";

  // a new question from the engine starts with an empty field
  useEffect(() => { setValue(""); setProblem(""); }, [request]);

  usePaste((text) => {
    if (busy || kind === "trust" || kind === "stop") return;
    setValue((v) => v + text.replace(/[\r\n\t ]+/g, ""));
  });

  useInput((input, key) => {
    if ((key.ctrl && (input === "c" || input === "d")) || key.escape) return onExit();
    if (busy) return;
    if (kind === "stop") {
      if (key.return) onExit();
      return;
    }
    if (kind === "trust") {
      const lower = input.toLowerCase();
      if (lower === "y") return onAnswer({ trust: true });
      if (lower === "n" || key.return) return onExit();
      return;
    }
    if (key.return) {
      const text = value.trim();
      if (!text) return setProblem(kind === "key" ? "Paste or type your API key, then press Enter." : "Type the address of your LARIS server.");
      return onAnswer(kind === "key" ? { key: text } : { server: text });
    }
    if (key.backspace || key.delete) return setValue((v) => v.slice(0, -1));
    if (key.ctrl && input === "u") return setValue("");
    if (key.ctrl || key.meta || !input) return;
    setProblem("");
    setValue((v) => v + input.replace(/[\r\n\t ]+/g, ""));
  });

  const detail =
    request.reason === "rejected" ? `The server refused that key${request.message ? ` (${request.message})` : ""}. Try again.`
    : request.reason === "invalid" ? `That is not a valid key: ${request.message}`
    : request.message;

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={kind === "stop" ? theme.error : theme.accent} paddingX={2} paddingY={1}>
      <Text><Text color={theme.accent} bold>{glyph.mark} LARIS</Text></Text>
      <Box marginTop={1}><Text bold color={kind === "stop" ? theme.error : undefined}>{TITLE[request.reason]}</Text></Box>
      {request.server ? <Text dimColor>{request.server}</Text> : null}
      <Box flexDirection="column" marginTop={1}>
        {kind === "server" ? (
          <>
            <Text>This copy of LARIS has no server built in. Where is your server?</Text>
            <Box marginTop={1}><Field label="Server address:" value={value} placeholder="https://laris.example.com" /></Box>
          </>
        ) : null}
        {kind === "trust" ? (
          <>
            <Text>This server uses a private certificate that this computer does not know yet.</Text>
            <Text>Compare the fingerprint with the one the owner of the server gave you:</Text>
            <Box marginTop={1}><Text bold>{request.fingerprint}</Text></Box>
            <Box marginTop={1}><Text>Trust this server? <Text color={theme.accent}>y</Text> yes · <Text color={theme.accent}>n</Text> no</Text></Box>
          </>
        ) : null}
        {kind === "stop" ? (
          <>
            <Text>The certificate the server presents is not the one this program was built for.</Text>
            <Text>Someone may be intercepting the connection, or the server was reinstalled.</Text>
            <Box marginTop={1}><Text>It presents: <Text bold>{request.fingerprint}</Text></Text></Box>
            <Box marginTop={1}><Text dimColor>Nothing was sent. Update LARIS, or ask the owner of the server. Enter closes.</Text></Box>
          </>
        ) : null}
        {kind === "key" ? (
          <>
            <Text>Enter the API key the owner of the server gave you. It is saved on this computer only.</Text>
            <Box marginTop={1}><Field label="API key:" value={value} secret placeholder="paste it here" /></Box>
          </>
        ) : null}
      </Box>
      {detail && kind !== "stop" ? <Box marginTop={1}><Text color={theme.warn}>{detail}</Text></Box> : null}
      {problem ? <Box marginTop={1}><Text color={theme.warn}>{problem}</Text></Box> : null}
      <Box marginTop={1}>
        {busy ? <Text color={theme.accent}>Checking…</Text> : <Text dimColor>{kind === "trust" || kind === "stop" ? "Esc quits" : "Enter continues · Ctrl+U clears · Esc quits"}</Text>}
      </Box>
    </Box>
  );
}
