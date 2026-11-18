(function () {
  "use strict";
  const root = document.getElementById("inventory-barcode");
  if (!root) return;
  const input = document.getElementById("inventory-barcode-input");
  const result = document.getElementById("inventory-barcode-result");
  const message = document.getElementById("inventory-barcode-message");
  let busy = false;

  function show(product) {
    result.replaceChildren();
    const title = document.createElement("h2"); title.className = "text-xl font-bold"; title.textContent = product.name;
    const details = document.createElement("dl"); details.className = "grid grid-cols-2 gap-2 mt-3";
    [["SKU", product.sku], ["Barcode", product.barcode], ["Available stock", product.stock + " " + product.base_unit], ["Base unit", product.base_unit]].forEach(function (pair) {
      const term = document.createElement("dt"); term.className = "help"; term.textContent = pair[0];
      const value = document.createElement("dd"); value.textContent = pair[1]; details.append(term, value);
    });
    result.append(title, details);
    if (product.cached) {
      const stale = document.createElement("p"); stale.className = "help mt-3";
      stale.textContent = "Offline cached snapshot from " + new Date(product.cached_at).toLocaleString() + ". Verify current stock before adjusting.";
      result.append(stale);
    }
    const links = document.createElement("div"); links.className = "flex flex-wrap gap-2 mt-4";
    const detail = document.createElement("a"); detail.className = "btn btn-outline"; detail.href = product.detail_url || ("/dashboard/products/" + product.id + "/"); detail.textContent = "Product details"; links.append(detail);
    if (product.adjust_url) { const adjust = document.createElement("a"); adjust.className = "btn btn-primary"; adjust.href = product.adjust_url; adjust.textContent = "Adjust stock"; links.append(adjust); }
    result.append(links); result.hidden = false;
  }

  async function fromCache(barcode) {
    if (!window.SmartMart || !SmartMart.db) return null;
    try { return (await SmartMart.db.getAll("barcodeProducts")).find(function (item) { return item.barcode === barcode; }) || null; }
    catch (_) { return null; }
  }

  async function lookup(raw, fromCamera) {
    const barcode = (raw || "").trim();
    if (!barcode || busy) return;
    busy = true; input.value = barcode; message.textContent = "Looking up barcode…"; result.hidden = true;
    try {
      const response = await fetch(root.dataset.lookupUrl + "?barcode=" + encodeURIComponent(barcode), { credentials: "same-origin", headers: { "Accept": "application/json" } });
      const product = await response.json();
      if (!response.ok) throw Object.assign(new Error(product.error || "Product not found."), { isResponse: true });
      product.cached_at = Date.now();
      if (window.SmartMart && SmartMart.db) SmartMart.db.put("barcodeProducts", product).catch(function () {});
      show(product); message.textContent = "";
    } catch (error) {
      if (!error.isResponse) {
        const cached = await fromCache(barcode);
        if (cached) { show(Object.assign({}, cached, { cached: true })); message.textContent = ""; }
        else message.textContent = "No online result or cached product found for barcode " + barcode + ".";
      } else message.textContent = error.message;
    } finally { busy = false; if (!fromCamera) input.focus(); }
  }

  root.querySelector("[data-inventory-scan]").addEventListener("submit", function (event) { event.preventDefault(); lookup(input.value, false); });
  root.addEventListener("smartmart:barcode", function (event) { lookup(event.detail.barcode, true); });
})();
