# Buffett Lens — App phân tích cổ phiếu Mỹ

Web app Flask giúp người dùng nhập mã chứng khoán Mỹ, lấy dữ liệu báo cáo tài chính nhiều năm từ **SEC Company Facts XBRL**, rồi phân tích theo checklist Buffett-style: chất lượng doanh nghiệp, moat định lượng, owner earnings, nợ, tăng trưởng và biên an toàn. App cũng hỗ trợ so sánh 2 cổ phiếu.

> Dữ liệu và phân tích chỉ để tham khảo, không phải khuyến nghị đầu tư.

## Tính năng

- Nhập 1 ticker để phân tích nhanh: doanh thu, lợi nhuận, FCF, owner earnings, ROE, ROIC, nợ/FCF.
- Chấm điểm 0–100 theo 6 nhóm: lợi nhuận, bền vững, moat/margin, bảng cân đối, tăng trưởng, định giá.
- Ước tính giá trị nội tại đơn giản bằng owner earnings DCF bảo thủ: tăng trưởng bị giới hạn, chiết khấu 10%.
- Dự báo tăng trưởng EPS/doanh thu các năm tới và tính PEG ratio. Nếu có `ALPHAVANTAGE_API_KEY`, app dùng Alpha Vantage estimates/PEGRatio; nếu thiếu, app tự tính từ lịch sử SEC.
- So sánh 2 ticker theo điểm tổng, ROIC/ROE, FCF, tăng trưởng, nợ và biên an toàn.
- Cache dữ liệu trong thư mục `cache/` để giảm gọi SEC/Stooq.

## Nguồn dữ liệu

- Báo cáo tài chính: SEC `company_tickers.json`, `companyfacts` và `submissions`.
- Dữ liệu thị trường: Nasdaq public quote API trước, Yahoo Chart và Stooq CSV làm fallback. App dùng giá/market cap trực tiếp nếu có, rồi mới tự suy ra market cap từ giá × số cổ phiếu.
- Dự báo tăng trưởng/PEG: Alpha Vantage `OVERVIEW` và `EARNINGS_ESTIMATES` khi cấu hình `ALPHAVANTAGE_API_KEY`; fallback nội bộ dùng CAGR lịch sử đã chặn biên.

## Chạy local

```bash
cd /home/ubuntu/us-stock-buffett-app
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
export SEC_USER_AGENT="Your Name your.email@example.com"
export ALPHAVANTAGE_API_KEY="your_alpha_vantage_key"  # tùy chọn, giúp lấy PEG/analyst estimates
./run.sh
```

Mở trình duyệt tại:

```text
http://127.0.0.1:8866
```

Nếu muốn đổi cổng:

```bash
PORT=8890 ./run.sh
```

## API

### Phân tích 1 cổ phiếu

```bash
curl 'http://127.0.0.1:8866/api/analyze?ticker=AAPL&years=10'
```

### So sánh 2 cổ phiếu

```bash
curl 'http://127.0.0.1:8866/api/compare?ticker_a=AAPL&ticker_b=MSFT&years=10'
```

## Cấu trúc

- `app.py` — Flask routes và xử lý lỗi.
- `sec_client.py` — gọi SEC/Stooq, cache, chuẩn hóa ticker, trích dữ liệu XBRL.
- `analyzer.py` — tính chỉ số, owner earnings, DCF, điểm Buffett-style và so sánh.
- `analyzer.py` — tính chỉ số, owner earnings, forecast growth, PEG, DCF, điểm Buffett-style và so sánh.
- `templates/index.html` — giao diện chính.
- `static/app.js` — gọi API và render dashboard.
- `static/style.css` — giao diện responsive.

## Lưu ý phân tích

- Đây là bộ lọc định lượng, chưa thay thế việc đọc 10-K, đánh giá moat thật, ban lãnh đạo và ngành.
- Dữ liệu XBRL có thể khác nhau theo ngành/ticker; app xử lý thiếu dữ liệu bằng cách hiển thị `—` hoặc bỏ qua tiêu chí không đủ dữ liệu.
- Với ngân hàng, bảo hiểm và công ty tài chính, các chỉ số nợ/FCF có thể không phù hợp như doanh nghiệp sản xuất/dịch vụ thông thường.
- Một số nguồn market data public có thể giới hạn tần suất hoặc thiếu ticker đặc biệt; khi đó app tự fallback giữa Nasdaq, Yahoo Chart và Stooq.
- PEG ratio = `P/E / tăng trưởng EPS dự báo (%)`; nếu Alpha Vantage trả `PEGRatio`, app ưu tiên giá trị đó và vẫn hiển thị forecast growth riêng.
