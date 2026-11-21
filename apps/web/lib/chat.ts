export type Attachment = { id: string; name: string; text: string };
export type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  attachments?: Attachment[];
  interrupted?: boolean;
};
export type Chat = { id: string; title: string; updatedAt: number; messages: Message[] };

export const textExtensions = [
  ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".log", ".tex", ".xml", ".yaml", ".yml",
];
export const fileAccept = textExtensions.join(",");

export async function readAttachment(file: File, maxBytes: number): Promise<Attachment> {
  if (!textExtensions.some((extension) => file.name.toLowerCase().endsWith(extension))) {
    throw new Error("Hãy chọn tệp văn bản UTF-8, ví dụ TXT, Markdown, CSV hoặc JSON.");
  }
  if (file.size > maxBytes) throw new Error("Tệp vượt quá giới hạn dung lượng của máy chủ.");
  const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
  if (text.includes("\0")) throw new Error("Tệp này chứa dữ liệu nhị phân.");
  if (!text.trim()) throw new Error("Tệp văn bản đang trống.");
  return { id: crypto.randomUUID(), name: file.name, text };
}

export function makeRequest(chat: Chat) {
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

export async function streamReply(response: Response, onText: (text: string) => void) {
  if (!response.ok) throw new Error(errors[response.status] ?? `Yêu cầu thất bại (HTTP ${response.status}).`);
  if (!response.body) throw new Error("Máy chủ không trả về luồng phản hồi.");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  // A separator or a CRLF pair can span two network chunks.
  const separator = /(?:\r\n|\n)(?:\r\n|\n)/;
  let buffer = "";
  let receivedText = false;
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
