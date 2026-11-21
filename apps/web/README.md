# Laris Chat

Laris Chat là web client dùng Next.js App Router và các component shadcn/ui. Client kết nối cổng P1 hiện
có của Laris qua một route cùng origin và sử dụng model mặc định do gateway cấu hình.

## Chạy cục bộ

Cần Node.js từ 22.18 trở lên và một Laris gateway đang chạy.

```sh
cd apps/web
cp .env.example .env.local
npm ci
npm run dev -- --hostname 127.0.0.1
```

Trước khi chạy `npm run dev`, đặt `LARIS_SERVER_URL` trong `.env.local` thành origin của gateway,
ví dụ `https://localhost:38443` với cổng HTTPS trong cấu hình mẫu. Nếu gateway dùng CA nội bộ, khởi
động Node với `NODE_EXTRA_CA_CERTS` trỏ đến chứng chỉ CA đã tin cậy. Xem [runbook triển khai](../../docs/deployment/RUNBOOK.md)
để lấy khóa API và thông tin CA. Mở trang localhost mà Next.js in ra, rồi chọn **Khóa API** ở
góc trên bên phải nếu gateway yêu cầu xác thực.

## Tệp và lịch sử

Chọn hoặc kéo thả tệp văn bản UTF-8 như TXT, Markdown, CSV và JSON. Khi gửi, nội dung tệp đi cùng
tin nhắn đến máy chủ Laris. Toàn bộ lịch sử được gửi lại để cung cấp ngữ cảnh và dùng chung giới hạn
request. Đặt `LARIS_WEB_MAX_REQUEST_BYTES` nếu giới hạn của gateway khác mặc định.

Lịch sử chat và nội dung tệp được lưu theo origin trong IndexedDB của trình duyệt. Khóa API chỉ giữ
trong bộ nhớ của tab. Dùng HTTPS khi truy cập ngoài localhost.

## Kiểm tra và build

```sh
npm run typecheck
npm test
npm run build
npm start -- --hostname 127.0.0.1
```
