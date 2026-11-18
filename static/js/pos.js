(function () {
  const root = document.getElementById("pos");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const searchUrl = root.dataset.searchUrl, checkoutUrl = root.dataset.checkoutUrl, cur = root.dataset.currency;
  const csrf = root.querySelector("[name=csrfmiddlewaretoken]").value;
  const cart = new Map(); // product + unit -> quantity and price snapshots
  const key = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => { const r = Math.random() * 16 | 0; return (c === "x" ? r : (r & 3 | 8)).toString(16); });
  const cents = (s) => Math.round(parseFloat(s) * 100);
  const money = (c) => (c / 100).toFixed(2);
  let busy = false, timer = null, lastResults = [], scanInFlight = false;

  function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }

  function addToCart(p, unitCode) {
    const unit = (p.units || []).find((candidate) => candidate.code === (unitCode || p.base_unit)) || (p.units || [])[0];
    if (!unit) { $("pos-error").textContent = "No sales unit is configured for " + p.name + "."; return false; }
    const factor = Number(unit.factor), stock = Number(p.stock), maxQty = stock / factor;
    if (stock < factor) { $("pos-error").textContent = "Not enough stock for one " + unit.label + " of " + p.name + "."; return false; }
    const cartKey = p.id + ":" + unit.code, line = cart.get(cartKey);
    const otherBaseQty = Array.from(cart.values()).filter((item) => item.id === p.id && item.key !== cartKey)
      .reduce((sum, item) => sum + item.qty * item.factor, 0);
    if ((line ? line.qty + 1 : 1) * factor + otherBaseQty > stock) { $("pos-error").textContent = "Only " + stock + " base units of " + p.name + " remain."; return false; }
    if (line) { line.qty += 1; }
    else cart.set(cartKey, { key: cartKey, id: p.id, name: p.name, sku: p.sku,
      price: cents(unit.sale_price || unit.price), list: cents(unit.price), stock, qty: 1, unitCode: unit.code,
      unitLabel: unit.label, factor, units: p.units || [unit] });
    render();
    $("pos-error").textContent = "";
    return true;
  }

  function cacheProduct(p) {
    if (!window.SmartMart || !SmartMart.db) return;
    SmartMart.db.put("barcodeProducts", { id: p.id, name: p.name, sku: p.sku, barcode: p.barcode || "",
      stock: p.stock, base_unit: p.base_unit, price: p.price, list_price: p.list_price, units: p.units || [], cached_at: Date.now() }).catch(() => {});
  }

  async function cachedProduct(barcode) {
    if (!window.SmartMart || !SmartMart.db) return null;
    try {
      const list = await SmartMart.db.getAll("barcodeProducts");
      const found = list.find((item) => item.barcode === barcode);
      if (!found) return null;
      const base = found.base_unit || "PCS";
      return { id: found.id, name: found.name, sku: found.sku, barcode: found.barcode,
        stock: String(found.stock), base_unit: base, price: found.price || found.list_price,
        list_price: found.list_price || found.price,
        units: found.units && found.units.length ? found.units : [{ code: base, label: base, factor: "1", price: found.list_price || found.price, sale_price: found.price || found.list_price }],
        cached: true, cached_at: found.cached_at };
    } catch (_) { return null; }
  }

  async function scanBarcode(value, fromCamera) {
    const input = $("pos-scanner"), barcode = (value || input.value).trim();
    if (!barcode) return;
    if (scanInFlight) return;
    scanInFlight = true;
    input.value = "";
    try {
      const r = await fetch(searchUrl + "?q=" + encodeURIComponent(barcode) + "&scan=1", { credentials: "same-origin" });
      const data = await r.json(), p = (data.results || []).find((item) => item.barcode === barcode);
      if (!p) $("pos-error").textContent = "Barcode not found: " + barcode;
      else { cacheProduct(p); addToCart(p); $("pos-offline-note").textContent = ""; }
    } catch (e) {
      const p = await cachedProduct(barcode);
      if (p) {
        addToCart(p);
        $("pos-offline-note").textContent = "Offline catalog snapshot from " + new Date(p.cached_at || Date.now()).toLocaleString() + ". Checkout still needs the server; stock and price may have changed.";
      } else $("pos-error").textContent = "Barcode not found in the last cached catalog: " + barcode;
    } finally {
      scanInFlight = false;
      if (!fromCamera) input.focus();
    }
  }

  function render() {
    const list = $("pos-cart"); list.textContent = "";
    let sub = 0, tot = 0;
    cart.forEach((l) => {
      sub += l.list * l.qty; tot += l.price * l.qty;
      const li = el("li", undefined, "border-t border-line pt-2");
      li.appendChild(el("div", l.name + " · " + l.unitLabel, "font-semibold"));
      const row = el("div", undefined, "flex items-center gap-2 mt-1");
      const minus = el("button", "−", "btn btn-outline"); minus.type = "button"; minus.setAttribute("aria-label", "Decrease " + l.name);
      minus.onclick = () => { l.qty = Math.max(0.000001, +(l.qty - 1).toFixed(6)); render(); };
      const unitSelect = el("select", undefined, "input");
      l.units.forEach((unit) => unitSelect.add(new Option(unit.label, unit.code)));
      unitSelect.value = l.unitCode;
      unitSelect.onchange = () => {
        const selected = l.units.find((unit) => unit.code === unitSelect.value);
        cart.delete(l.key); l.unitCode = selected.code; l.unitLabel = selected.label;
        l.factor = Number(selected.factor); l.price = cents(selected.sale_price || selected.price); l.list = cents(selected.price);
        l.key = l.id + ":" + l.unitCode;
        const otherBaseQty = Array.from(cart.values()).filter((item) => item.id === l.id)
          .reduce((sum, item) => sum + item.qty * item.factor, 0);
        l.qty = Math.min(l.qty, Math.max(0, l.stock - otherBaseQty) / l.factor);
        if (cart.has(l.key)) cart.get(l.key).qty += l.qty;
        else cart.set(l.key, l);
        render();
      };
      const qty = el("input", undefined, "input"); qty.type = "number"; qty.min = "0.000001"; qty.step = "0.000001"; qty.max = String(l.stock / l.factor); qty.value = String(l.qty);
      qty.style.width = "5rem"; qty.setAttribute("aria-label", "Quantity of " + l.name);
      qty.onchange = () => { const n = parseFloat(qty.value); const used = Array.from(cart.values()).filter((item) => item.id === l.id && item !== l).reduce((sum, item) => sum + item.qty * item.factor, 0); l.qty = Math.min(Math.max(isNaN(n) ? 1 : n, 0.000001), Math.max(0, l.stock - used) / l.factor); render(); };
      const plus = el("button", "+", "btn btn-outline"); plus.type = "button"; plus.setAttribute("aria-label", "Increase " + l.name);
      plus.onclick = () => { const used = Array.from(cart.values()).filter((item) => item.id === l.id && item !== l).reduce((sum, item) => sum + item.qty * item.factor, 0); l.qty = Math.min(l.qty + 1, Math.max(0, l.stock - used) / l.factor); render(); };
      const lineTotal = el("span", cur + " " + money(l.price * l.qty), "ml-auto");
      const rm = el("button", "✕", "btn btn-outline"); rm.type = "button"; rm.setAttribute("aria-label", "Remove " + l.name);
      rm.onclick = () => { cart.delete(l.key); render(); };
      row.append(unitSelect, minus, qty, plus, lineTotal, rm);
      li.appendChild(row);
      if (l.qty * l.factor >= l.stock) li.appendChild(el("p", "All " + l.stock + " base units are in this line", "help"));
      list.appendChild(li);
    });
    $("pos-empty").hidden = cart.size > 0;
    $("pos-subtotal").textContent = money(sub);
    $("pos-discount").textContent = money(sub - tot);
    $("pos-total").textContent = cur + " " + money(tot);
    $("pos-submit").disabled = cart.size === 0 || busy;
    const t = $("pos-tendered").value;
    $("pos-change").textContent = t !== "" && cents(t) >= tot ? cur + " " + money(cents(t) - tot) : "—";
  }

  async function search(enter) {
    const q = $("pos-search").value.trim();
    if (!q) { lastResults = []; $("pos-results").textContent = ""; return; }
    let data;
    try { const r = await fetch(searchUrl + "?q=" + encodeURIComponent(q), { credentials: "same-origin" }); data = await r.json(); }
    catch (e) { $("pos-error").textContent = "Search failed. Check your connection."; return; }
    lastResults = data.results || [];
    lastResults.forEach(cacheProduct);
    const ul = $("pos-results"); ul.textContent = "";
    if (!lastResults.length) ul.appendChild(el("li", "No products found.", "help"));
    lastResults.forEach((p) => {
      const li = el("li");
      const b = el("button", undefined, "btn btn-outline w-full justify-between"); b.type = "button"; b.disabled = p.stock < 1;
      b.appendChild(el("span", p.name + " · " + p.sku));
      b.appendChild(el("span", p.stock < 1 ? "Out of stock" : cur + " " + p.price + " (" + p.stock + " " + p.base_unit + " left)"));
      b.onclick = () => { addToCart(p); $("pos-search").focus(); };
      li.appendChild(b); ul.appendChild(li);
    });
    if (enter) {
      const exact = lastResults.find((p) => p.barcode === q || p.sku.toLowerCase() === q.toLowerCase()) || (lastResults.length === 1 ? lastResults[0] : null);
      if (exact) { addToCart(exact); $("pos-search").value = ""; ul.textContent = ""; }
    }
  }

  $("pos-search").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => search(false), 250); });
  $("pos-search").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); clearTimeout(timer); search(true); } });
  $("pos-tendered").addEventListener("input", render);
  $("pos-scanner").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (!e.repeat) scanBarcode(); } });
  root.addEventListener("smartmart:barcode", (e) => scanBarcode(e.detail.barcode, true));
  $("pos-method").addEventListener("change", () => { $("pos-cash-box").hidden = $("pos-method").value !== "cash"; });
  $("pos-clear").addEventListener("click", () => { if (!cart.size || confirm("Clear the whole cart?")) { cart.clear(); render(); } });

  $("pos-submit").addEventListener("click", async () => {
    if (busy || !cart.size) return;
    busy = true; $("pos-submit").disabled = true; $("pos-error").textContent = "";
    const body = {
      items: Array.from(cart.values()).map((l) => ({ product_id: l.id, quantity: l.qty, unit_code: l.unitCode })),
      payment_method: $("pos-method").value, idempotency_key: key,
      amount_tendered: $("pos-method").value === "cash" ? $("pos-tendered").value : "",
    };
    try {
      const r = await fetch(checkoutUrl, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify(body) });
      const data = await r.json();
      if (r.ok && data.receipt_url) { window.location.href = data.receipt_url; return; }
      $("pos-error").textContent = data.error || "The sale could not be completed.";
    } catch (e) { $("pos-error").textContent = "Connection problem. Press Complete sale again; it will not charge twice."; }
    busy = false; render();
    $("pos-scanner").focus();
  });

  $("pos-cash-box").hidden = $("pos-method").value !== "cash";
  render();
  $("pos-scanner").focus();
})();
