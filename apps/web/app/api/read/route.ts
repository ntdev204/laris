// Forwards an attached file to the server's reader (`POST /v1/laris/read`, T273): the browser cannot read a PDF.
import { maxRequestBytes } from "@/lib/config";

function reject(status: number) {
  return new Response(null, { status, headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request) {
  const configuredUrl = process.env.LARIS_SERVER_URL;
  if (!configuredUrl) return reject(503);
  const name = new URL(request.url).searchParams.get("name") ?? "";
  if (!name.trim()) return reject(400);

  let url: URL;
  try {
    url = new URL("/v1/laris/read", configuredUrl);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return reject(503);
    url.searchParams.set("name", name);
  } catch {
    return reject(503);
  }

  const advertised = request.headers.get("content-length");
  if (advertised && Number(advertised) > maxRequestBytes) return reject(413);
  const body = Buffer.from(await request.arrayBuffer());
  if (body.byteLength > maxRequestBytes) return reject(413);

  const headers = new Headers({
    "Content-Type": "application/octet-stream",
    "X-Laris-Protocol": "2",
  });
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("Authorization", authorization);
  try {
    const upstream = await fetch(url, {
      method: "POST", headers, body, cache: "no-store", redirect: "error", signal: request.signal,
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return reject(502);
  }
}
