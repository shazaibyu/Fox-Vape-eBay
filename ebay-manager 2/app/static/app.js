const fmt = (n) => "£" + (Number(n) || 0).toFixed(2);

// ---- tabs ----
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("border-b-2", "border-blue-600", "text-blue-600"));
    document.getElementById("tab-" + btn.dataset.tab).classList.remove("hidden");
    btn.classList.add("border-b-2", "border-blue-600", "text-blue-600");
  });
});
document.querySelector(".tab-btn").click();

// ---- connection status ----
async function refreshStatus() {
  const s = await (await fetch("/auth/status")).json();
  const el = document.getElementById("conn-status");
  el.textContent = s.connected ? "Connected to eBay (" + s.environment + ")" : "Not connected";
  el.className = "text-sm px-3 py-1 rounded-full " + (s.connected ? "bg-green-200 text-green-800" : "bg-red-200 text-red-800");
}

// ---- orders ----
async function loadOrders() {
  const orders = await (await fetch("/api/orders")).json();
  const body = document.getElementById("orders-body");
  body.innerHTML = "";
  let total = 0;
  orders.forEach(o => {
    total += o.profit;
    const profitColor = o.profit >= 0 ? "text-green-700" : "text-red-700";
    body.innerHTML += `
      <tr class="border-b">
        <td class="p-2">${o.ebay_order_id}</td>
        <td class="p-2">${o.buyer_username || ""}</td>
        <td class="p-2">${o.item_title || ""}</td>
        <td class="p-2 text-right">${fmt(o.sale_price)}</td>
        <td class="p-2 text-right">${fmt(o.shipping_charged)}</td>
        <td class="p-2">${o.carrier || "-"}<br><span class="text-gray-400 text-xs">${o.tracking_number || "no tracking"}</span></td>
        <td class="p-2 text-right">
          <input type="number" step="0.01" value="${o.item_cost}" class="w-20 border rounded p-1 text-right"
            onchange="editOrder('${o.ebay_order_id}', 'item_cost', this.value)">
        </td>
        <td class="p-2 text-right">
          <input type="number" step="0.01" value="${o.shipping_cost}" class="w-20 border rounded p-1 text-right"
            onchange="editOrder('${o.ebay_order_id}', 'shipping_cost', this.value)">
          ${o.shipping_cost_is_estimated ? '<span class="text-xs text-yellow-600">est.</span>' : '<span class="text-xs text-green-600">actual</span>'}
        </td>
        <td class="p-2 text-right">${fmt(o.ebay_fee)}${o.ebay_fee_is_estimated ? '<span class="text-xs text-yellow-600"> est.</span>' : ""}</td>
        <td class="p-2 text-right">${fmt(o.age_verification_fee)}</td>
        <td class="p-2 text-right font-bold ${profitColor}">${fmt(o.profit)}</td>
      </tr>`;
  });
  document.getElementById("total-profit").textContent = fmt(total);
}

async function syncOrders() {
  const btn = event.target;
  btn.disabled = true; btn.textContent = "Importing...";
  try {
    const r = await (await fetch("/api/orders/sync", { method: "POST" })).json();
    alert("Imported " + (r.imported ?? 0) + " orders");
  } catch (e) { alert("Error importing orders - check Settings/connection."); }
  btn.disabled = false; btn.textContent = "Import Orders from eBay";
  loadOrders();
}

async function editOrder(orderId, field, value) {
  const body = new URLSearchParams();
  body.set(field, value);
  await fetch(`/api/orders/${orderId}/edit?${body.toString()}`, { method: "POST" });
  loadOrders();
}

// ---- inventory ----
async function loadInventory() {
  const items = await (await fetch("/api/inventory")).json();
  const body = document.getElementById("inventory-body");
  body.innerHTML = items.map(i => `
    <tr class="border-b"><td class="p-2">${i.sku}</td><td class="p-2">${i.title || ""}</td><td class="p-2 text-right">${i.quantity}</td></tr>
  `).join("");
}
async function syncInventory() {
  const btn = event.target;
  btn.disabled = true; btn.textContent = "Fetching...";
  try {
    const r = await (await fetch("/api/inventory/sync", { method: "POST" })).json();
    alert("Synced " + (r.synced ?? 0) + " items");
  } catch (e) { alert("Error fetching inventory - check Settings/connection."); }
  btn.disabled = false; btn.textContent = "Fetch Stock from eBay";
  loadInventory();
}

// ---- messages ----
async function loadMessagesTab() {
  const s = await (await fetch("/api/settings")).json();
  document.getElementById("away-toggle").checked = s.away_mode;
  document.getElementById("away-message").value = s.away_message;
  const log = await (await fetch("/api/messages/log")).json();
  document.getElementById("message-log").innerHTML = log.map(m => `
    <div class="p-2 rounded ${m.direction === 'out' ? 'bg-blue-50' : 'bg-gray-50'}">
      <b>${m.buyer_username || ''}</b> (${m.direction}${m.auto_generated ? ', auto' : ''}): ${m.message_text}
    </div>`).join("");
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
    </div>`).join("");
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
refreshStatus();
loadOrders();
loadInventory();
loadMessagesTab();
loadSettingsTab();
setInterval(refreshStatus, 15000);
