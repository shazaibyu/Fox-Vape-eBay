const fmt = (n) => "£" + (Number(n) || 0).toFixed(2);
let ALL_ORDERS = [];
let ALL_INVENTORY = [];
let LOW_STOCK = 3;
let monthlyChart = null;

// ---- navigation ----
document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});
function showPage(page) {
  document.querySelectorAll(".page").forEach(p => p.classList.add("hidden"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("bg-blue-100", "text-blue-800", "font-medium"));
  document.getElementById("page-" + page).classList.remove("hidden");
  document.querySelector(`.nav-btn[data-page="${page}"]`).classList.add("bg-blue-100", "text-blue-800", "font-medium");
  if (page === "dashboard") loadDashboard();
  if (page === "products") loadProducts();
}
 
// ---- connection status ----
async function refreshStatus() {
  try {
    const s = await (await fetch("/auth/status")).json();
    const el = document.getElementById("conn-status");
    el.textContent = s.connected ? "Connected (" + s.environment + ")" : "Not connected";
    el.className = "m-3 text-xs px-3 py-2 rounded text-center " + (s.connected ? "bg-green-200 text-green-800" : "bg-red-200 text-red-800");
  } catch (e) {}
}

// ---- dashboard ----
async function loadDashboard() {
  try {
    const [summary, monthly, top] = await Promise.all([
      (await fetch("/api/analytics/summary")).json(),
      (await fetch("/api/analytics/monthly")).json(),
      (await fetch("/api/analytics/top-items")).json(),
    ]);
    document.getElementById("d-profit30").textContent = fmt(summary.last_30_days.profit);
    document.getElementById("d-rev30").textContent = fmt(summary.last_30_days.revenue);
    document.getElementById("d-orders30").textContent = summary.last_30_days.orders;
    document.getElementById("d-avg30").textContent = fmt(summary.last_30_days.avg_profit);
    document.getElementById("d-alltime").textContent =
      `${summary.all_time.orders} orders, ${fmt(summary.all_time.revenue)} revenue, ${fmt(summary.all_time.profit)} profit`;
    document.getElementById("d-refunded").textContent = summary.refunded_orders;

    const ctx = document.getElementById("chart-monthly");
    if (monthlyChart) monthlyChart.destroy();
    monthlyChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: monthly.map(m => m.month),
        datasets: [
          { label: "Profit", data: monthly.map(m => m.profit), backgroundColor: "#16a34a" },
          { label: "Revenue", data: monthly.map(m => m.revenue), backgroundColor: "#93c5fd" },
        ],
      },
      options: { responsive: true, plugins: { legend: { position: "bottom" } } },
    });

    document.getElementById("top-items").innerHTML = top.length
      ? top.map(t => `<div class="flex justify-between border-b py-1"><span class="truncate pr-2">${t.item}</span><span class="font-medium ${t.profit >= 0 ? "text-green-700" : "text-red-700"}">${fmt(t.profit)}</span></div>`).join("")
      : '<p class="text-gray-400">No orders yet - import orders first.</p>';
  } catch (e) {}
}

// ---- orders ----
let STATUS_FILTER = "all";
const STATUS_META = {
  all:              { label: "All",                chip: "bg-gray-200 text-gray-800" },
  awaiting_dispatch:{ label: "Awaiting dispatch",  chip: "bg-blue-100 text-blue-800",   badge: "bg-blue-100 text-blue-800" },
  due_24h:          { label: "Due in 24h",         chip: "bg-amber-100 text-amber-800", badge: "bg-amber-100 text-amber-800" },
  overdue:          { label: "Overdue",            chip: "bg-red-100 text-red-800",     badge: "bg-red-100 text-red-800" },
  shipped:          { label: "Shipped",            chip: "bg-green-100 text-green-800", badge: "bg-green-100 text-green-800" },
  shipped_late:     { label: "Shipped late",       chip: "bg-orange-100 text-orange-800", badge: "bg-orange-100 text-orange-800" },
  past_est_delivery:{ label: "Past est. delivery", chip: "bg-purple-100 text-purple-800", badge: "bg-purple-100 text-purple-800" },
  refunded:         { label: "Refunded",           chip: "bg-gray-300 text-gray-700",   badge: "bg-gray-300 text-gray-700" },
};

function renderStatusChips() {
  const counts = { all: ALL_ORDERS.length };
  ALL_ORDERS.forEach(o => {
    counts[o.fulfillment_status] = (counts[o.fulfillment_status] || 0) + 1;
  });
  const container = document.getElementById("status-chips");
  container.innerHTML = Object.entries(STATUS_META).map(([key, meta]) => {
    const n = counts[key] || 0;
    if (key !== "all" && n === 0) return "";
    const active = STATUS_FILTER === key ? "ring-2 ring-blue-500" : "";
    return `<button onclick="setStatusFilter('${key}')"
      class="px-3 py-1.5 rounded-full text-xs font-medium ${meta.chip} ${active}">
      ${meta.label} (${n})</button>`;
  }).join("");
}
function setStatusFilter(s) { STATUS_FILTER = s; renderOrders(); }

function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " +
         d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

async function loadOrders() {
  ALL_ORDERS = await (await fetch("/api/orders")).json();
  renderOrders();
}

let PAGE = 1;
const PAGE_SIZE = 100;
let MONTH_FILTER = "all";

function changePage(delta) { PAGE = Math.max(1, PAGE + delta); renderOrders(false); }

function monthKey(iso) {
  if (!iso) return null;
  return iso.slice(0, 7); // "2026-07"
}
function monthLabel(key) {
  const [y, m] = key.split("-");
  const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return names[parseInt(m) - 1] + " " + y;
}
function renderMonthChips() {
  const months = {};
  ALL_ORDERS.forEach(o => {
    const k = monthKey(o.order_date);
    if (k) months[k] = (months[k] || 0) + 1;
  });
  const keys = Object.keys(months).sort().reverse();
  const container = document.getElementById("month-chips");
  const chip = (key, label, count) => {
    const active = MONTH_FILTER === key ? "bg-blue-600 text-white" : "bg-white border";
    return `<button onclick="setMonthFilter('${key}')" class="px-3 py-1.5 rounded text-xs font-medium ${active}">${label}${count !== null ? ` (${count})` : ""}</button>`;
  };
  container.innerHTML = chip("all", "All months", null) +
    keys.map(k => chip(k, monthLabel(k), months[k])).join("");
}
function setMonthFilter(m) { MONTH_FILTER = m; renderOrders(); }

async function quickRefresh() {
  const r = await (await fetch("/api/orders/sync?days=2", { method: "POST" })).json();
  if (r.started === false) { alert(r.message); return; }
  document.getElementById("sync-progress").classList.remove("hidden");
  pollSync();
}

// auto-refresh data every 5 minutes (the server also auto-imports new
// orders every 5 minutes in the background)
setInterval(() => { loadOrders(); loadInventory(); }, 5 * 60 * 1000);

function renderOrders(resetPage = true) {
  if (resetPage) PAGE = 1;
  renderStatusChips();
  renderMonthChips();
  const q = (document.getElementById("order-search").value || "").toLowerCase();
  const filter = document.getElementById("order-filter").value;
  let rows = ALL_ORDERS.filter(o => {
    const hay = [o.buyer_username, o.item_title, o.ebay_order_id, o.tracking_number].join(" ").toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (filter === "active" && o.refunded) return false;
    if (filter === "refunded" && !o.refunded) return false;
    if (filter === "estimated" && !o.shipping_cost_is_estimated) return false;
    if (STATUS_FILTER !== "all" && o.fulfillment_status !== STATUS_FILTER) return false;
    if (MONTH_FILTER !== "all" && monthKey(o.order_date) !== MONTH_FILTER) return false;
    return true;
  });

  let total = 0;
  rows.forEach(o => { if (!o.refunded) total += o.profit; });
  document.getElementById("total-profit").textContent = fmt(total);

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (PAGE > totalPages) PAGE = totalPages;
  const start = (PAGE - 1) * PAGE_SIZE;
  const pageRows = rows.slice(start, start + PAGE_SIZE);
  document.getElementById("page-info").textContent =
    `Showing ${rows.length ? start + 1 : 0}-${start + pageRows.length} of ${rows.length} orders (page ${PAGE}/${totalPages})`;

  const body = document.getElementById("orders-body");
  body.innerHTML = "";
  pageRows.forEach(o => {
    const profitColor = o.profit >= 0 ? "text-green-700" : "text-red-700";
    const rowClass = o.refunded ? "opacity-50 bg-red-50" : "";
    const meta = STATUS_META[o.fulfillment_status] || STATUS_META.shipped;
    const shipBy = o.fulfillment_status === "overdue" || o.fulfillment_status === "due_24h"
      ? `<span class="text-red-700 font-medium">ship by ${fmtDate(o.ship_by_date)}</span>`
      : (o.shipped_date ? `sent ${fmtDate(o.shipped_date)}` : (o.ship_by_date ? `ship by ${fmtDate(o.ship_by_date)}` : "-"));
    body.innerHTML += `
      <tr class="border-b ${rowClass}">
        <td class="p-2">${o.ebay_order_id}<br><span class="text-gray-400">${o.buyer_username || ""}</span></td>
        <td class="p-2 max-w-xs truncate">${o.item_title || ""}</td>
        <td class="p-2">
          <span class="px-2 py-0.5 rounded-full text-[10px] font-medium ${meta.badge || ""}">${meta.label}</span>
          <br><span class="text-gray-500">${shipBy}</span>
        </td>
        <td class="p-2 text-right">${fmt(o.sale_price)}</td>
        <td class="p-2 text-right">${fmt(o.shipping_charged)}</td>
        <td class="p-2">${o.carrier || "-"}<br><span class="text-gray-400">${o.tracking_number || "no tracking"}</span></td>
        <td class="p-2 text-right">
          <input type="number" step="0.01" value="${o.item_cost}" class="w-16 border rounded p-1 text-right"
            onchange="editOrder('${o.ebay_order_id}', 'item_cost', this.value)">
        </td>
        <td class="p-2 text-right">
          <input type="number" step="0.01" value="${o.shipping_cost}" class="w-16 border rounded p-1 text-right"
            onchange="editOrder('${o.ebay_order_id}', 'shipping_cost', this.value)">
          ${o.shipping_cost_is_estimated ? '<span class="text-yellow-600">est.</span>' : '<span class="text-green-600">actual</span>'}
        </td>
        <td class="p-2 text-right">${fmt(o.ebay_fee)}${o.ebay_fee_is_estimated ? '<span class="text-yellow-600"> est.</span>' : ""}</td>
        <td class="p-2 text-right">${fmt(o.age_verification_fee)}</td>
        <td class="p-2 text-right font-bold ${profitColor}">${fmt(o.profit)}</td>
        <td class="p-2 text-center">
          <input type="checkbox" ${o.refunded ? "checked" : ""} title="Mark refunded"
            onchange="editOrder('${o.ebay_order_id}', 'refunded', this.checked)">
        </td>
      </tr>`;
  });
}

// ---- background import with live progress ----
async function startSync() {
  const r = await (await fetch("/api/orders/sync", { method: "POST" })).json();
  if (r.started === false) { alert(r.message); }
  document.getElementById("sync-progress").classList.remove("hidden");
  document.getElementById("sync-btn").disabled = true;
  pollSync();
}
async function pollSync() {
  const s = await (await fetch("/api/orders/sync/status")).json();
  const pct = s.total ? Math.round((s.imported / s.total) * 100) : 0;
  document.getElementById("sync-progress-bar").style.width = pct + "%";
  document.getElementById("sync-progress-pct").textContent = pct + "%";
  document.getElementById("sync-progress-text").textContent =
    `Imported ${s.imported} of ${s.total || "?"} orders · ${fmt(s.revenue)} revenue so far`;
  if (s.running) {
    setTimeout(pollSync, 2000);
  } else {
    document.getElementById("sync-btn").disabled = false;
    document.getElementById("sync-progress-text").textContent = s.error
      ? ("Stopped: " + s.error + ` (${s.imported} orders saved)`)
      : `Done - ${s.imported} orders, ${fmt(s.revenue)} revenue imported`;
    loadOrders();
    loadDashboard();
  }
}

async function syncFees(ev) {
  const btn = ev.target;
  btn.disabled = true; btn.textContent = "Syncing fees...";
  try {
    const r = await (await fetch("/api/orders/sync-fees", { method: "POST" })).json();
    if (r.error) alert("Fee sync failed:\n\n" + r.error);
    else alert(`Real eBay fees applied to ${r.orders_updated} orders (${r.fees_found} fee records found).`);
  } catch (e) { alert("Fee sync error - try again."); }
  btn.disabled = false; btn.textContent = "Sync eBay Fees";
  loadOrders();
}

async function uploadCsv(input) {
  if (!input.files.length) return;
  const fd = new FormData();
  fd.append("file", input.files[0]);
  const r = await (await fetch("/api/orders/import-csv", { method: "POST", body: fd })).json();
  if (r.error) alert("CSV import failed:\n\n" + r.error);
  else alert(`Imported ${r.imported} orders from CSV (${r.skipped} rows skipped).`);
  input.value = "";
  loadOrders();
  loadDashboard();
}

async function editOrder(orderId, field, value) {
  const body = new URLSearchParams();
  body.set(field, value);
  await fetch(`/api/orders/${orderId}/edit?${body.toString()}`, { method: "POST" });
  loadOrders();
}

// ---- inventory ----
async function loadInventory() {
  ALL_INVENTORY = await (await fetch("/api/inventory")).json();
  renderInventory();
}
function renderInventory() {
  const q = (document.getElementById("inv-search").value || "").toLowerCase();
  const body = document.getElementById("inventory-body");
  const rows = ALL_INVENTORY.filter(i => !q || (i.sku + " " + (i.title || "")).toLowerCase().includes(q));
  body.innerHTML = rows.map(i => {
    const low = i.quantity <= LOW_STOCK;
    return `<tr class="border-b ${low ? "bg-yellow-50" : ""}">
      <td class="p-2 text-gray-400">${i.sku}</td>
      <td class="p-2">${i.title || ""}</td>
      <td class="p-2 text-right">${i.price ? fmt(i.price) : "-"}</td>
      <td class="p-2 text-right">
        <input type="number" min="0" value="${i.quantity}" class="w-20 border rounded p-1 text-right font-medium ${low ? "text-red-700 border-red-300" : ""}"
          onchange="setInvQty('${i.sku}', this.value)">${low ? " ⚠" : ""}
      </td>
      <td class="p-2 text-center"><button onclick="deleteInvItem('${i.sku}')" class="text-red-500 text-xs">✕</button></td>
    </tr>`;
  }).join("") || '<tr><td class="p-3 text-gray-400" colspan="5">No inventory yet - add products above or fetch from eBay.</td></tr>';
}
function saveLowStock() {
  LOW_STOCK = parseInt(document.getElementById("low-stock").value || "3");
  renderInventory();
}
async function syncInventory(ev) {
  if (!confirm("Fetch from eBay OVERWRITES your manual stock quantities with eBay's numbers. Continue?")) return;
  const btn = ev.target;
  btn.disabled = true; btn.textContent = "Fetching...";
  try {
    const r = await (await fetch("/api/inventory/sync", { method: "POST" })).json();
    if (r.error) alert("Fetch failed:\n\n" + r.error);
    else alert("Synced " + (r.synced ?? 0) + " listings from eBay");
  } catch (e) { alert("Error fetching inventory."); }
  btn.disabled = false; btn.textContent = "Fetch Stock from eBay";
  loadInventory();
}

// ---- products & costs ----
let ALL_PRODUCTS = [];
async function loadProducts() {
  ALL_PRODUCTS = await (await fetch("/api/products")).json();
  renderProducts();
}
function renderProducts() {
  const q = (document.getElementById("prod-search").value || "").toLowerCase();
  const rows = ALL_PRODUCTS.filter(p => !q || (p.title + " " + (p.sku || "")).toLowerCase().includes(q));
  document.getElementById("products-body").innerHTML = rows.map(p => `
    <tr class="border-b">
      <td class="p-2 max-w-md truncate">${p.title}</td>
      <td class="p-2 text-gray-400">${p.sku || "-"}</td>
      <td class="p-2 text-right">${p.orders}</td>
      <td class="p-2 text-right">${p.units}</td>
      <td class="p-2 text-right">
        £ <input type="number" step="0.01" value="${p.unit_cost}" class="w-20 border rounded p-1 text-right"
          onchange="setProductCost('${encodeURIComponent(p.product_key)}', this.value, this)">
      </td>
    </tr>`).join("") || '<tr><td class="p-3 text-gray-400" colspan="5">No products yet - import orders first.</td></tr>';
}
async function setProductCost(encodedKey, value, el) {
  el.disabled = true;
  const r = await (await fetch(`/api/products/cost?key=${encodedKey}&unit_cost=${value}`, { method: "POST" })).json();
  el.disabled = false;
  if (r.ok) {
    el.classList.add("bg-green-100");
    setTimeout(() => el.classList.remove("bg-green-100"), 1500);
    loadOrders();
  } else alert("Couldn't save cost");
}

async function createGroup() {
  const kw = document.getElementById("group-keyword").value.trim();
  const cost = document.getElementById("group-cost").value;
  if (!kw || cost === "") { alert("Enter a product name and unit cost"); return; }
  const r = await (await fetch(`/api/products/group?keyword=${encodeURIComponent(kw)}&unit_cost=${cost}`, { method: "POST" })).json();
  if (r.error) { alert(r.error); return; }
  alert(`Group created - cost applied to ${r.orders_updated} orders.`);
  document.getElementById("group-keyword").value = "";
  document.getElementById("group-cost").value = "";
  loadProducts();
  loadOrders();
}

// ---- inventory management ----
async function addInvItem() {
  const title = document.getElementById("inv-add-title").value.trim();
  const sku = document.getElementById("inv-add-sku").value.trim();
  const qty = document.getElementById("inv-add-qty").value || 0;
  if (!title) { alert("Enter a title"); return; }
  const p = new URLSearchParams({ title, quantity: qty });
  if (sku) p.set("sku", sku);
  const r = await (await fetch(`/api/inventory/add?${p}`, { method: "POST" })).json();
  if (r.error) { alert(r.error); return; }
  document.getElementById("inv-add-title").value = "";
  document.getElementById("inv-add-sku").value = "";
  document.getElementById("inv-add-qty").value = "";
  loadInventory();
}
async function setInvQty(sku, qty) {
  await fetch(`/api/inventory/set-qty?sku=${encodeURIComponent(sku)}&quantity=${qty}`, { method: "POST" });
  loadInventory();
}
async function deleteInvItem(sku) {
  if (!confirm("Remove this item from inventory?")) return;
  await fetch(`/api/inventory/item?sku=${encodeURIComponent(sku)}`, { method: "DELETE" });
  loadInventory();
}

// ---- prefix rates ----
async function loadPrefixRates() {
  const rates = await (await fetch("/api/settings/prefix-rates")).json();
  document.getElementById("prefix-rates-list").innerHTML = rates.map(r => `
    <div class="flex justify-between items-center border-b py-1">
      <span>Starts with <b>${r.prefix}</b> → ${fmt(r.cost)}</span>
      <button onclick="deletePrefixRate(${r.id})" class="text-red-600 text-xs">remove</button>
    </div>`).join("") || '<p class="text-gray-400 text-xs">No prefix rates.</p>';
}
async function addPrefixRate() {
  const prefix = document.getElementById("pr-prefix").value.trim();
  const cost = document.getElementById("pr-cost").value;
  if (!prefix || cost === "") { alert("Enter prefix and cost"); return; }
  await fetch(`/api/settings/prefix-rates?prefix=${encodeURIComponent(prefix)}&cost=${cost}`, { method: "POST" });
  document.getElementById("pr-prefix").value = "";
  document.getElementById("pr-cost").value = "";
  loadPrefixRates();
}
async function deletePrefixRate(id) {
  await fetch(`/api/settings/prefix-rates/${id}`, { method: "DELETE" });
  loadPrefixRates();
}
async function reapplyShipping() {
  const r = await (await fetch("/api/settings/reapply-shipping", { method: "POST" })).json();
  alert(`Shipping rules re-applied to ${r.orders_updated} orders.`);
  loadOrders();
}

// ---- messages ----
async function loadMessagesTab() {
  const s = await (await fetch("/api/settings")).json();
  document.getElementById("away-toggle").checked = s.away_mode;
  document.getElementById("away-message").value = s.away_message;
  const log = await (await fetch("/api/messages/log")).json();
  document.getElementById("message-log").innerHTML = log.length ? log.map(m => `
    <div class="p-2 rounded ${m.direction === 'out' ? 'bg-blue-50' : 'bg-gray-50'}">
      <b>${m.buyer_username || ''}</b> (${m.direction}${m.auto_generated ? ', auto' : ''}): ${m.message_text}
    </div>`).join("") : '<p class="text-gray-400">No messages logged yet.</p>';
}
async function toggleAway() {
  const checked = document.getElementById("away-toggle").checked;
  await fetch(`/api/settings?away_mode=${checked}`, { method: "POST" });
}
async function saveAwayMessage() {
  const msg = encodeURIComponent(document.getElementById("away-message").value);
  await fetch(`/api/settings?away_message=${msg}`, { method: "POST" });
  alert("Saved");
}
async function checkNow() {
  const r = await (await fetch("/api/messages/check-now", { method: "POST" })).json();
  alert(JSON.stringify(r));
  loadMessagesTab();
}

// ---- settings ----
async function loadSettingsTab() {
  const s = await (await fetch("/api/settings")).json();
  document.getElementById("s-fee-percent").value = s.ebay_fee_percent;
  document.getElementById("s-fee-fixed").value = s.ebay_fee_fixed;
  document.getElementById("s-age-fee").value = s.age_verification_fee;
  document.getElementById("s-environment").value = s.ebay_environment;
  loadRates();
  loadPrefixRates();
}
async function saveKeys() {
  const p = new URLSearchParams({
    client_id: document.getElementById("s-client-id").value,
    client_secret: document.getElementById("s-client-secret").value,
    redirect_uri: document.getElementById("s-redirect-uri").value,
    environment: document.getElementById("s-environment").value,
  });
  await fetch(`/auth/save-keys?${p.toString()}`, { method: "POST" });
  alert("Saved. Now click Connect to eBay.");
  refreshStatus();
}
function connectEbay() { window.location.href = "/auth/connect"; }

async function saveFeeSettings() {
  const p = new URLSearchParams({
    ebay_fee_percent: document.getElementById("s-fee-percent").value,
    ebay_fee_fixed: document.getElementById("s-fee-fixed").value,
    age_verification_fee: document.getElementById("s-age-fee").value,
  });
  await fetch(`/api/settings?${p.toString()}`, { method: "POST" });
  alert("Saved");
}

async function loadRates() {
  const rates = await (await fetch("/api/settings/shipping-rates")).json();
  document.getElementById("rates-list").innerHTML = rates.map(r => `
    <div class="flex justify-between items-center border-b py-1">
      <span>${r.carrier} - ${r.service_name}: ${fmt(r.default_cost)}</span>
      <button onclick="deleteRate(${r.id})" class="text-red-600 text-xs">remove</button>
    </div>`).join("") || '<p class="text-gray-400 text-xs">No fallback rates yet.</p>';
}
async function addRate() {
  const p = new URLSearchParams({
    carrier: document.getElementById("r-carrier").value,
    service_name: document.getElementById("r-service").value,
    default_cost: document.getElementById("r-cost").value,
  });
  await fetch(`/api/settings/shipping-rates?${p.toString()}`, { method: "POST" });
  loadRates();
}
async function deleteRate(id) {
  await fetch(`/api/settings/shipping-rates/${id}`, { method: "DELETE" });
  loadRates();
}

// ---- init ----
showPage("dashboard");
refreshStatus();
loadOrders();
loadInventory();
loadMessagesTab();
loadSettingsTab();
setInterval(refreshStatus, 15000);
