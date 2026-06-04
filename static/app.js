const $ = (selector) => document.querySelector(selector);

const BUCKETS = {
  profitability: ["Lợi nhuận", 30],
  consistency: ["Bền vững", 20],
  moat_margins: ["Moat/Margin", 15],
  balance_sheet: ["Bảng cân đối", 15],
  growth: ["Tăng trưởng", 10],
  valuation: ["Định giá", 10],
};

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtMoney(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  return `${sign}$${abs.toFixed(2)}`;
}

function fmtPrice(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `$${Number(value).toFixed(2)}`;
}

function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function fmtX(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Number(value).toFixed(1)}x`;
}

function fmtNum(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toFixed(digits);
}

function showStatus(message, error = false) {
  const el = $("#status");
  el.textContent = message;
  el.classList.toggle("error", error);
  el.classList.remove("hidden");
}

function hideStatus() {
  $("#status").classList.add("hidden");
}

function setBusy(busy) {
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = busy;
  });
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Không gọi được API.");
  }
  return data.result;
}

function renderStock(stock, options = {}) {
  const compact = Boolean(options.compact);
  const company = stock.company;
  const summary = stock.summary;
  const valuation = stock.valuation || {};
  const price = stock.price || {};
  const score = stock.score || {};
  const narrative = stock.narrative || {};

  return `
    <article class="stock-card">
      <div class="stock-head">
        <div>
          <div class="ticker">
            <strong>${esc(company.ticker)}</strong>
            <span>${esc(company.name)}</span>
            ${company.sic_description ? `<span class="pill">${esc(company.sic_description)}</span>` : ""}
          </div>
          <p class="muted">${esc(narrative.headline || "")}</p>
        </div>
        <div class="score-box">
          <span class="score">${fmtNum(score.total, 0)}</span>
          <span>/100</span>
        </div>
      </div>

      <div class="metrics">
        ${metric("Giá", fmtPrice(price.price))}
        ${metric("Market cap", fmtMoney(summary.market_cap))}
        ${metric("ROIC 5 năm", fmtPct(summary.avg_roic_5y))}
        ${metric("ROE 5 năm", fmtPct(summary.avg_roe_5y))}
        ${metric("FCF yield", fmtPct(summary.fcf_yield))}
        ${metric("P/FCF", fmtX(summary.p_fcf))}
        ${metric("Biên an toàn", fmtPct(valuation.margin_of_safety))}
        ${metric("Nợ/FCF", fmtX(summary.latest_debt_to_fcf))}
      </div>

      <div class="section-grid">
        <div class="box">
          <h3>Góc nhìn Buffett-style</h3>
          <p>${esc(narrative.buffett_view || "")}</p>
          <h3>Điểm mạnh</h3>
          ${list(narrative.strengths)}
          <h3>Rủi ro/cần kiểm chứng</h3>
          ${list(narrative.concerns)}
        </div>
        <div class="box">
          <h3>Thang điểm</h3>
          ${bucketBars(score.buckets || {})}
          <h3>Checklist</h3>
          ${checklist(score.checklist || [])}
        </div>
      </div>

      ${valuation.available ? valuationBox(valuation, price) : `<div class="box"><h3>Định giá</h3><p class="muted">${esc(valuation.reason || "Không đủ dữ liệu định giá.")}</p></div>`}
      ${compact ? "" : annualTable(stock.annuals || [])}
      <p class="muted">Nguồn BCTC: ${esc(stock.data_source?.financials)}${price.date ? ` · Giá: ${esc(price.date)} (${esc(price.source)})` : ""}</p>
    </article>
  `;
}

function metric(label, value) {
  return `<div class="metric"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
}

function list(items) {
  if (!items || !items.length) return `<p class="muted">Không có điểm nổi bật.</p>`;
  return `<ul>${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
}

function bucketBars(buckets) {
  return `<div class="bars">${Object.entries(BUCKETS)
    .map(([key, [label, max]]) => {
      const value = Number(buckets[key] || 0);
      const width = Math.max(0, Math.min(100, (value / max) * 100));
      return `
        <div class="bar-row">
          <span>${esc(label)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
          <b>${value.toFixed(0)}</b>
        </div>`;
    })
    .join("")}</div>`;
}

function checklist(items) {
  if (!items.length) return `<p class="muted">Không có dữ liệu checklist.</p>`;
  return `<div class="checklist">${items
    .map((item) => `
      <div class="check ${item.passed ? "pass" : "fail"}">
        <span class="icon">${item.passed ? "✓" : "!"}</span>
        <div><b>${esc(item.label)}</b><div class="muted">${formatChecklistValue(item.value)}</div></div>
      </div>`)
    .join("")}</div>`;
}

function formatChecklistValue(value) {
  if (!value || typeof value !== "object") return "";
  return Object.entries(value)
    .map(([key, val]) => `${labelize(key)}: ${formatLoose(key, val)}`)
    .join(" · ");
}

function labelize(key) {
  return key
    .replaceAll("_", " ")
    .replace("roe", "ROE")
    .replace("roic", "ROIC")
    .replace("fcf", "FCF")
    .replace("cagr", "CAGR");
}

function formatLoose(key, value) {
  if (value === null || value === undefined) return "—";
  if (key.includes("years")) return `${value}`;
  if (key.includes("margin") || key.includes("roe") || key.includes("roic") || key.includes("cagr")) return fmtPct(value);
  if (key.includes("debt")) return fmtX(value);
  return fmtNum(value);
}

function valuationBox(valuation, price) {
  return `
    <div class="box">
      <h3>Ước tính giá trị nội tại</h3>
      <div class="metrics">
        ${metric("Owner earnings nền", fmtMoney(valuation.base_owner_earnings))}
        ${metric("Tăng trưởng giả định", fmtPct(valuation.growth_rate))}
        ${metric("Giá trị/cp", fmtPrice(valuation.intrinsic_per_share))}
        ${metric("Giá hiện tại", fmtPrice(price.price))}
      </div>
      <p class="muted">${esc(valuation.method || "")}</p>
    </div>`;
}

function annualTable(annuals) {
  if (!annuals.length) return "";
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Năm</th>
            <th>Doanh thu</th>
            <th>LN ròng</th>
            <th>FCF</th>
            <th>Owner earnings</th>
            <th>ROE</th>
            <th>ROIC</th>
            <th>FCF margin</th>
            <th>Nợ/FCF</th>
          </tr>
        </thead>
        <tbody>
          ${annuals
            .slice()
            .reverse()
            .map((row) => `
              <tr>
                <td class="left"><b>${row.year}</b></td>
                <td>${fmtMoney(row.revenue)}</td>
                <td>${fmtMoney(row.net_income)}</td>
                <td>${fmtMoney(row.free_cash_flow)}</td>
                <td>${fmtMoney(row.owner_earnings)}</td>
                <td>${fmtPct(row.roe)}</td>
                <td>${fmtPct(row.roic)}</td>
                <td>${fmtPct(row.fcf_margin)}</td>
                <td>${fmtX(row.debt_to_fcf)}</td>
              </tr>`)
            .join("")}
        </tbody>
      </table>
    </div>`;
}

function renderComparison(result) {
  const [first, second] = result.stocks;
  const comparison = result.comparison;
  const firstTicker = first.company.ticker;
  const secondTicker = second.company.ticker;
  return `
    <article class="compare-card">
      <h2>So sánh ${esc(firstTicker)} và ${esc(secondTicker)}</h2>
      <div class="compare-summary">
        <div><span class="muted">Kết luận</span><h3>${esc(comparison.overall_winner)}</h3><p>${esc(comparison.summary)}</p></div>
        <div><span class="muted">${esc(firstTicker)}</span><h3>${fmtNum(first.score.total, 0)}/100</h3><p>${esc(first.score.verdict)}</p></div>
        <div><span class="muted">${esc(secondTicker)}</span><h3>${fmtNum(second.score.total, 0)}/100</h3><p>${esc(second.score.verdict)}</p></div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Tiêu chí</th><th>${esc(firstTicker)}</th><th>${esc(secondTicker)}</th><th>Thắng</th></tr>
          </thead>
          <tbody>
            ${comparison.rows.map((row) => compareRow(row)).join("")}
          </tbody>
        </table>
      </div>
    </article>
    <div class="grid-2">
      ${renderStock(first, { compact: true })}
      ${renderStock(second, { compact: true })}
    </div>
  `;
}

function compareRow(row) {
  return `
    <tr>
      <td class="left">${esc(row.label)}</td>
      <td>${formatCompare(row.label, row.first)}</td>
      <td>${formatCompare(row.label, row.second)}</td>
      <td class="winner">${esc(row.winner)}</td>
    </tr>`;
}

function formatCompare(label, value) {
  if (value === null || value === undefined) return "—";
  if (label.includes("Điểm")) return fmtNum(value, 0);
  if (label.includes("dương")) return `${value}`;
  if (label.includes("Nợ/FCF")) return fmtX(value);
  return fmtPct(value);
}

$("#analyzeForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const ticker = $("#ticker").value.trim();
  if (!ticker) return;
  setBusy(true);
  showStatus(`Đang lấy BCTC SEC và phân tích ${ticker.toUpperCase()}...`);
  $("#compareResult").classList.add("hidden");
  try {
    const result = await postJson("/api/analyze", { ticker, years: 10 });
    $("#result").innerHTML = renderStock(result);
    $("#result").classList.remove("hidden");
    hideStatus();
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});

$("#compareForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const tickerA = $("#tickerA").value.trim();
  const tickerB = $("#tickerB").value.trim();
  if (!tickerA || !tickerB) return;
  setBusy(true);
  showStatus(`Đang so sánh ${tickerA.toUpperCase()} và ${tickerB.toUpperCase()}...`);
  $("#result").classList.add("hidden");
  try {
    const result = await postJson("/api/compare", { ticker_a: tickerA, ticker_b: tickerB, years: 10 });
    $("#compareResult").innerHTML = renderComparison(result);
    $("#compareResult").classList.remove("hidden");
    hideStatus();
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});
