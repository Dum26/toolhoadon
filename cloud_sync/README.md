# Tự cập nhật khi máy Windows tắt

Workflow `.github/workflows/sync-inventory.yml` chạy trên GitHub Actions vào phút 07, 22, 37 và 52 mỗi giờ. Nó dùng Chromium để đọc cùng báo cáo VAOnline như ứng dụng Windows, cập nhật riêng Secret File `inventory.json` trên Render rồi triển khai lại bản build hiện có. Không cần máy Windows chạy thường trực.

Chỉ dữ liệu từ lần lấy thành công mới được gửi lên Render. Khi đăng nhập hết hạn, báo cáo lỗi hoặc không có dòng hàng hợp lệ, workflow báo lỗi và giữ bản tồn kho đang phục vụ. Workflow không mở trang đăng nhập tương tác hoặc tự vượt CAPTCHA/OTP.

## Cấu hình một lần

Trong https://github.com/Dum26/toolhoadon/settings/secrets/actions, chọn **New repository secret** và tạo:

| Secret | Giá trị |
| --- | --- |
| `VAONLINE_URL` | Địa chỉ HTTPS của công ty trên VAOnline, giống địa chỉ ứng dụng Windows đang mở. |
| `VAONLINE_STORAGE_STATE_GZIP_B64` | Toàn bộ nội dung file `D:\ToolVacom\va_stock\data\render\VAONLINE_STORAGE_STATE_GZIP_B64.txt`. |
| `RENDER_API_KEY` | API key tạo tại Render → Account Settings → API Keys, có quyền cập nhật dịch vụ tồn kho. |
| `RENDER_SERVICE_ID` | ID bắt đầu bằng `srv-` trong địa chỉ dashboard của dịch vụ `toolhoadon` trên Render. |
| `VAONLINE_REPORT_OPTIONS` | Tùy chọn: nội dung `D:\ToolVacom\va_stock\data\render\VAONLINE_REPORT_OPTIONS.json` để giữ bộ lọc đang dùng. Nếu bỏ trống, lấy cả năm hiện tại. |

Phiên VAOnline cho phép truy cập tài khoản. Chỉ dán phiên và API key vào **GitHub Actions Secrets**; không đưa vào mã nguồn, README, ảnh chụp hoặc chat. Session được nén để vừa giới hạn 48 KB của GitHub Secrets; gzip/base64 không tự mã hóa dữ liệu. GitHub mã hóa dữ liệu khi lưu dưới dạng Secret.

Sau khi đủ Secrets, mở **Settings → Secrets and variables → Actions → Variables**, tạo Repository Variable `AUTO_SYNC_ENABLED` với giá trị `true`. Biến này bật lịch chạy; mặc định workflow chưa hoạt động.

Vào **Actions → Update VA STOCK inventory → Run workflow** để chạy thử. Chỉ coi là đã cấu hình xong sau khi run màu xanh, Render triển khai thành công và thời gian cập nhật trên trang web đổi sang lần lấy dữ liệu mới.

## Gia hạn phiên đăng nhập

Khi workflow báo hết hạn phiên:

1. Trên Windows, mở VA STOCK và đăng nhập lại VAOnline, hoàn tất CAPTCHA/OTP nếu có.
2. Chạy:

   ```powershell
   cd D:\ToolVacom\va_stock
   .\.venv\Scripts\python.exe tools\prepare_cloud_session.py
   ```

3. Thay giá trị Secret `VAONLINE_STORAGE_STATE_GZIP_B64` bằng nội dung file vừa tạo, rồi chạy lại workflow.

Khoảng **Cả năm**, **Tháng này** và **Tháng trước** tự dịch theo ngày hiện tại ở múi giờ UTC+7. Khoảng **Tùy chọn** giữ nguyên ngày đã lưu.

## Giới hạn vận hành

Lịch GitHub Actions có thể trễ hoặc bỏ lượt khi hệ thống quá tải. Với repository công khai, GitHub tự tắt lịch sau 60 ngày không có hoạt động repository; cần bật lại workflow khi đó. Vì thế đây là lịch cập nhật định kỳ, không bảo đảm dữ liệu thời gian thực. Mỗi lần cập nhật file cần chờ Render triển khai lại.

Nếu cần dịch vụ theo lịch có cam kết vận hành cao hơn, cân nhắc Render Cron Job với cấu hình thanh toán riêng; cấu hình hiện tại không tạo Cron Job trả phí.

Tài liệu:

- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://api-docs.render.com/reference/add-or-update-secret-file
- https://api-docs.render.com/reference/create-deploy
