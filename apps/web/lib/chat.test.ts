import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { makeRequest, readAttachment, streamReply, type Chat } from "./chat.ts";

function splitStream(content: string) {
  const bytes = new TextEncoder().encode(content);
  let offset = 0;
  return new Response(new ReadableStream({
    pull(controller) {
      if (offset === bytes.length) controller.close();
      else controller.enqueue(bytes.subarray(offset, ++offset));
    },
  }));
}

const fixtures = new URL("../../../crates/laris-protocol/tests/fixtures/p1/", import.meta.url);

test("reads the committed P1 chat fixture across arbitrary network boundaries", async () => {
  const sse = await readFile(new URL("chat_text.response.sse", fixtures), "utf8");
  const captured: string[] = [];
  await streamReply(splitStream(sse), (text) => captured.push(text));
  assert.equal(captured.join(""), "Perovskite is stable under encapsulation.");
});

test("handles CRLF and Unicode split across network chunks", async () => {
  const captured: string[] = [];
  const content = ': keep-alive\r\n\r\ndata: {"choices":[{"index":0,"delta":{"content":"Tóm tắt"}}]}\r\n\r\ndata: [DONE]\r\n\r\n';
  await streamReply(splitStream(content), (text) => captured.push(text));
  assert.deepEqual(captured, ["Tóm tắt"]);
});

test("reports an incomplete stream or an upstream error with partial text preserved", async () => {
  const sse = await readFile(new URL("chat_midstream_error.response.sse", fixtures), "utf8");
  let partial = "";
  await assert.rejects(streamReply(splitStream(sse), (text) => { partial += text; }), /gặp lỗi/);
  assert.match(partial, /^Perovskite films/);
  await assert.rejects(streamReply(new Response(": ping\n\n"), () => {}), /kết nối bị ngắt/i);
});

test("sends text file contents and excludes an interrupted assistant turn", async () => {
  const file = await readAttachment(new File(["Hàng,Cột\n1,2"], "dữ liệu.csv"), 1024);
  const chat: Chat = {
    id: "session-1",
    title: "Tài liệu",
    updatedAt: 0,
    messages: [
      { id: "1", role: "user", text: "Đọc tài liệu", attachments: [file] },
      { id: "2", role: "assistant", text: "Dở dang", interrupted: true },
    ],
  };
  assert.deepEqual(JSON.parse(makeRequest(chat)), {
    messages: [{ role: "user", content: 'Đọc tài liệu\n\nTệp đính kèm "dữ liệu.csv":\nHàng,Cột\n1,2' }],
    stream: true,
    laris: { kind: "turn", session_id: "session-1" },
  });
});

test("rejects unsupported, binary, oversized and invalid UTF-8 files", async () => {
  await assert.rejects(readAttachment(new File(["mock"], "file.pdf"), 100), /văn bản UTF-8/);
  await assert.rejects(readAttachment(new File(["\0"], "file.txt"), 100), /nhị phân/);
  await assert.rejects(readAttachment(new File(["mock"], "file.txt"), 2), /dung lượng/);
  await assert.rejects(readAttachment(new File([Uint8Array.of(0xff)], "file.txt"), 100), TypeError);
});
