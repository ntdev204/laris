export type Attachment = { id: string; name: string; text: string; readBy?: string };
/** One tool the server ran for this answer (T273), as the server reports it: no page text, only what was done. */
export type ToolRecord = {
  name: string;
  input: string;
  ok: boolean;
  error?: string;
  paper_id?: string;
  sources: { title: string; url: string; year?: number | null }[];
};
/** One step of the server's STEM profile (T284) as it ended: its code (step and outcome, never text) and time. */
export type StemStep = { code: string; ms: number; outcome: string };
export type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  attachments?: Attachment[];
  interrupted?: boolean;
  tools?: ToolRecord[];
  report?: string;
  stem?: StemStep[];
};
export type Meta = { tools?: ToolRecord[]; report?: string; stem?: StemStep[] };
export type Chat = { id: string; title: string; updatedAt: number; messages: Message[] };

export const textExtensions = [
  ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".log", ".tex", ".xml", ".yaml", ".yml",
];
export const fileAccept = [...textExtensions, ".pdf"].join(",");

/** A PDF is read by the server (`/v1/laris/read`): the browser has no PDF reader. */
async function readPdf(file: File, maxBytes: number, apiKey: string): Promise<Attachment> {
  if (file.size > maxBytes) throw new Error("Tệp vượt quá giới hạn dung lượng của máy chủ.");
  const headers = new Headers({ "Content-Type": "application/pdf" });
  if (apiKey) headers.set("Authorization", `Bearer ${apiKey}`);
  const response = await fetch(`/api/read?name=${encodeURIComponent(file.name)}`, {
    method: "POST", headers, body: file,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    const message = detail?.error?.message ?? detail?.message ?? "";
    throw new Error(response.status === 400 && /pdf_unreadable/.test(message)
      ? `Không đọc được ${file.name}: tệp có thể là bản quét (máy chủ chưa có OCR).`
      : errors[response.status] ?? `Không đọc được ${file.name} (HTTP ${response.status}).`);
  }
  const read = await response.json();
  if (!read.text?.trim()) throw new Error(`${file.name} không có chữ để đọc.`);
  return { id: crypto.randomUUID(), name: file.name, text: read.text, readBy: read.read_by };
}

export async function readAttachment(file: File, maxBytes: number, apiKey = ""): Promise<Attachment> {
  if (file.name.toLowerCase().endsWith(".pdf")) return readPdf(file, maxBytes, apiKey);
  if (!textExtensions.some((extension) => file.name.toLowerCase().endsWith(extension))) {
    throw new Error("Hãy chọn tệp PDF hoặc tệp văn bản UTF-8, ví dụ TXT, Markdown, CSV hoặc JSON.");
  }
  if (file.size > maxBytes) throw new Error("Tệp vượt quá giới hạn dung lượng của máy chủ.");
  const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
  if (text.includes("\0")) throw new Error("Tệp này chứa dữ liệu nhị phân.");
  if (!text.trim()) throw new Error("Tệp văn bản đang trống.");
  return { id: crypto.randomUUID(), name: file.name, text };
}

export function makeRequest(chat: Chat) {
  // the files of the latest question are also sent apart, so the server can register them as papers (T273)
  const latest = [...chat.messages].reverse().find((message) => message.role === "user");
  const documents = (latest?.attachments ?? []).map(({ name, text }) => ({ name, text }));
  return JSON.stringify({
    messages: chat.messages
      .filter((message) => !message.interrupted)
      .map(({ role, text, attachments }) => ({
        role,
        content: attachments?.length
          ? [text || "Hãy đọc các tệp đính kèm.", ...attachments.map((file) =>
              `Tệp đính kèm ${JSON.stringify(file.name)}:\n${file.text}`,
            )].join("\n\n")
          : text,
      })),
    stream: true,
    laris: {
      kind: "turn",
      session_id: chat.id,
      ...(documents.length ? { documents } : {}),
    },
  });
}

const errors: Record<number, string> = {
  401: "Hãy kiểm tra khóa API của bạn rồi thử lại.",
  403: "Khóa API này không có quyền gửi tin nhắn.",
  413: "Cuộc chat vượt quá giới hạn dung lượng. Hãy bớt tệp hoặc tạo chat mới.",
  426: "Phiên bản giao thức của client và máy chủ không khớp.",
  429: "Bạn đã chạm giới hạn sử dụng. Hãy thử lại sau.",
  502: "Không kết nối được với máy chủ Laris.",
  503: "Máy chủ Laris chưa sẵn sàng. Hãy kiểm tra cấu hình kết nối.",
};

export async function streamReply(
  response: Response,
  onText: (text: string) => void,
  onMeta: (meta: Meta) => void = () => {},
) {
  if (!response.ok) throw new Error(errors[response.status] ?? `Yêu cầu thất bại (HTTP ${response.status}).`);
  if (!response.body) throw new Error("Máy chủ không trả về luồng phản hồi.");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  // A separator or a CRLF pair can span two network chunks.
  const separator = /(?:\r\n|\n)(?:\r\n|\n)/;
  let buffer = "";
  let receivedText = false;
  const stem: StemStep[] = [];
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) throw new Error("Kết nối bị ngắt trước khi phản hồi hoàn tất.");
      buffer += value;

      let boundary: RegExpExecArray | null;
      while ((boundary = separator.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = frame.split(/\r?\n/).flatMap((line) =>
          line.startsWith("data:") ? [line.slice(5).replace(/^ /, "")] : [],
        ).join("\n");

        if (!data) continue;
        if (data === "[DONE]") {
          if (!receivedText) throw new Error("Máy chủ chưa trả về nội dung phản hồi.");
          return;
        }
        const chunk = JSON.parse(data);
        if (chunk.error) throw new Error("Máy chủ gặp lỗi khi đang trả lời. Bạn có thể thử lại.");
        // what the server searched and read for this answer: the whole list so far, the last one wins (the
        // server's extra fields sit directly in the `laris` block)
        const extra = chunk.laris;
        if (Array.isArray(extra?.server_tools) || typeof extra?.gap_report === "string") {
          onMeta({
            ...(Array.isArray(extra.server_tools) ? { tools: extra.server_tools } : {}),
            ...(typeof extra.gap_report === "string" ? { report: extra.gap_report } : {}),
          });
        }
        // the steps of the STEM profile (T284), shown as they end, as the terminal client shows them
        const steps = Array.isArray(extra?.steps) ? extra.steps : [];
        const ended = steps.filter((step: { stage?: string }) => step?.stage === "stem");
        if (ended.length) {
          stem.push(...ended.map((step: StemStep) => ({ code: String(step.code ?? ""), ms: Number(step.ms ?? 0),
            outcome: String(step.outcome ?? "") })));
          onMeta({ stem: [...stem] });
        }
        const text = chunk.choices?.find((choice: { index: number }) => choice.index === 0)?.delta?.content;
        if (typeof text === "string" && text) {
          receivedText = true;
          onText(text);
        }
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
