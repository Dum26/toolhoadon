# VA STOCK trên Render

Trang web tra cứu mã hàng, tên hàng và tồn kho bằng dữ liệu đã xuất từ ứng dụng VA STOCK Windows. Ai có link đều xem được tồn kho, không cần đăng nhập. Dữ liệu tồn kho không được lưu trong repository.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FDum26%2Ftoolhoadon)

## Triển khai

1. Bấm **Deploy to Render** ở trên và đăng nhập Render.
2. Tạo dịch vụ theo Blueprint dùng gói Free.
3. Sau khi tạo dịch vụ, mở **Environment → Secret Files → Add Secret File**. Đặt tên file là `inventory.json`, dán nội dung bản xuất tồn kho, rồi lưu và triển khai.
4. Mở và chia sẻ địa chỉ `https://<tên-dịch-vụ>.onrender.com` Render cấp. Mọi người mở link là xem được tồn kho.

Trên máy chạy VA STOCK, xuất dữ liệu bằng:

```powershell
cd D:\ToolVacom\va_stock
.\.venv\Scripts\python.exe tools\export_render_inventory.py
```

Nội dung để dán vào Secret File nằm ở `D:\ToolVacom\va_stock\data\render\inventory.json`. Không đưa file này, thư mục phiên đăng nhập, database hoặc mật khẩu lên GitHub.

## Cập nhật tồn kho

Để tự lấy dữ liệu và cập nhật web ngay cả khi máy Windows tắt, xem [hướng dẫn đồng bộ cloud](cloud_sync/README.md). Lịch chạy mặc định chưa bật, cần cấu hình GitHub Secrets trước.

Cập nhật tồn kho trong VA STOCK Windows, chạy lại lệnh xuất, rồi thay nội dung Secret File `inventory.json` trong Render và lưu. Render triển khai lại với bản tồn kho mới; mọi người bấm **Làm mới dữ liệu** trên trang web.

Bản web hiển thị bản tồn kho gần nhất được gửi lên; việc tự lấy VAOnline do workflow cloud đảm nhiệm khi được cấu hình. Bản xuất được lưu ở cấu hình Secret Files của Render nên vẫn có sau khi dịch vụ khởi động lại. Gói Free có thể cần khoảng một phút để mở lại sau 15 phút không có lượt truy cập.

Tài liệu Render: https://render.com/docs/deploy-fastapi và https://render.com/docs/configure-environment-variables#secret-files
