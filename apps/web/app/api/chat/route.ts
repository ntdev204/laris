import { maxRequestBytes } from "@/lib/config";

function reject(status: number) {
  return new Response(null, { status, headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request) {
  if (request.headers.get("content-type")?.split(";")[0] !== "application/json") {
    return reject(415);
  }

  const configuredUrl = process.env.LARIS_SERVER_URL;
  if (!configuredUrl) return reject(503);

  let url: URL;
  try {
    url = new URL("/v1/laris/chat", configuredUrl);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) {
      return reject(503);
    }
  } catch {
    return reject(503);
  }

  // P1 requires Content-Length. Read with a hard limit before forwarding a fixed-size body.
  if (!request.body) return reject(400);
  const advertised = request.headers.get("content-length");
  if (advertised && Number(advertised) > maxRequestBytes) return reject(413);

  const chunks: Uint8Array<ArrayBufferLike>[] = [];
  const reader = request.body.getReader();
  let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maxRequestBytes) {
        await reader.cancel();
        return reject(413);
      }
      chunks.push(value);
    }
  } catch {
    return reject(400);
  } finally {
    reader.releaseLock();
  }

  const headers = new Headers({
    Accept: "text/event-stream",
    "Content-Type": "application/json",
    "X-Laris-Protocol": "2",
  });
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("Authorization", authorization);

  try {
    const upstream = await fetch(url, {
      method: "POST",
      headers,
      body: Buffer.concat(chunks, length),
      cache: "no-store",
      redirect: "error",
      signal: request.signal,
    });
    if (!upstream.ok) {
      await upstream.body?.cancel();
      return reject(upstream.status);
    }
    if (!upstream.headers.get("content-type")?.startsWith("text/event-stream")) {
      await upstream.body?.cancel();
      return reject(502);
    }
    return new Response(upstream.body, {
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-store, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return reject(502);
  }
}
