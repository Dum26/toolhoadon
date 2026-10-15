# VA STOCK trên Render

Trang web tra cứu mã hàng, tên hàng và tồn kho bằng dữ liệu đã xuất từ ứng dụng VA STOCK Windows. Mọi trang và API tồn kho đều yêu cầu đăng nhập. Dữ liệu và mật khẩu không được lưu trong repository.

## Triển khai

1. Mở https://dashboard.render.com/select-repo?type=blueprint và chọn repository này.
2. Nhập mật khẩu chia sẻ vào biến `VA_STOCK_PASSWORD`; tên đăng nhập là `vastock`. Blueprint dùng gói Free.
3. Sau khi tạo dịch vụ, mở **Environment → Secret Files → Add Secret File**. Đặt tên file là `inventory.json`, dán nội dung bản xuất tồn kho, rồi lưu và triển khai.
4. Mở địa chỉ `https://<tên-dịch-vụ>.onrender.com` Render cấp và đăng nhập. Chia sẻ địa chỉ cùng tài khoản cho người cần xem.

Trên máy chạy VA STOCK, xuất dữ liệu bằng:

```powershell
cd D:\ToolVacom\va_stock
.\.venv\Scripts\python.exe tools\export_render_inventory.py
```

Nội dung để dán vào Secret File nằm ở `D:\ToolVacom\va_stock\data\render\inventory.json`. Không đưa file này, thư mục phiên đăng nhập, database hoặc mật khẩu lên GitHub.

## Cập nhật tồn kho

Cập nhật tồn kho trong VA STOCK Windows, chạy lại lệnh xuất, rồi thay nội dung Secret File `inventory.json` trong Render và lưu. Render triển khai lại với bản tồn kho mới; mọi người bấm **Làm mới dữ liệu** trên trang web.

Bản web không tự đăng nhập VAOnline hoặc tự đồng bộ từ máy Windows. Bản xuất được lưu ở cấu hình Secret Files của Render nên vẫn có sau khi dịch vụ khởi động lại. Gói Free có thể cần khoảng một phút để mở lại sau 15 phút không có lượt truy cập.

Tài liệu Render: https://render.com/docs/deploy-fastapi và https://render.com/docs/configure-environment-variables#secret-files
