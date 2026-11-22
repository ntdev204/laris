import path from "node:path";
import { gapDir, readJson } from "@/lib/gap";
import { RatingSheet } from "@/components/gap/rating-sheet";

export const dynamic = "force-dynamic";

export default async function Rate() {
  const sheet = await readJson<{ items: { item: string; topic: string; text: string }[] }>(path.join(gapDir, "rating", "sheet.json"));
  return (
    <main className="mx-auto max-w-4xl space-y-4 p-6">
      <h1 className="text-xl font-semibold">Phiếu chấm khoảng trống nghiên cứu (chấm mù)</h1>
      <p className="text-sm text-muted-foreground">
        Mỗi mục là một khoảng trống do hệ thống LARIS hoặc một baseline đề xuất; nguồn được ẩn và thứ tự được xáo trộn cố định.
        Chấm hai tiêu chí theo thang 1–5. <b>Mức có căn cứ</b>: 1 = không có căn cứ hoặc căn cứ sai; 3 = có căn cứ một phần; 5 = mọi ý đều có căn cứ đúng trong bài được trích.
        <b> Mức có giá trị</b>: 1 = tầm thường hoặc không phải khoảng trống; 3 = hợp lý nhưng đã biết rộng rãi; 5 = đáng làm thành một đề tài.
      </p>
      {sheet ? <RatingSheet items={sheet.items} /> : <p>Chưa có phiếu (rating/sheet.json).</p>}
    </main>
  );
}
