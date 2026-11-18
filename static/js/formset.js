(function () {
  const btn = document.getElementById("add-row");
  const tpl = document.getElementById("empty-form");
  const rows = document.getElementById("formset-rows");
  const total = document.querySelector('input[name$="-TOTAL_FORMS"]');
  if (!btn || !tpl || !rows || !total) return;
  const unitNode = document.getElementById("product-unit-data");
  const productUnits = unitNode ? JSON.parse(unitNode.textContent) : {};
  const stockUrlTemplate = document.getElementById("purchase-form")?.dataset.stockUrlTemplate || "";

  function initUnits(root) {
    root.querySelectorAll(".formset-row").forEach(function (row) {
      const product = row.querySelector('select[name$="-product"]');
      const unit = row.querySelector('select[name$="-unit_code"]');
      const hint = row.querySelector("[data-conversion-hint]");
      const factorInput = row.querySelector('input[name$="-conversion_factor"]');
      const factorWrap = row.querySelector("[data-conversion-factor-wrap]");
      if (!product || !unit || unit.dataset.ready) return;
      unit.dataset.ready = "1";
      function fetchCurrentStock() {
        const productId = product.value;
        const opening = row.querySelector("[data-opening-stock]");
        const openingUnit = row.querySelector("[data-opening-unit]");
        const requestId = Number(row.dataset.stockRequest || "0") + 1;
        row.dataset.stockRequest = String(requestId);
        if (!productId) {
          if (opening) opening.textContent = "—";
          if (openingUnit) openingUnit.textContent = "";
          recalculate();
          return;
        }
        if (opening) opening.textContent = "Loading…";
        const url = stockUrlTemplate.replace(/\/0\/stock\/$/, "/" + encodeURIComponent(productId) + "/stock/");
        fetch(url, {credentials: "same-origin", headers: {"Accept": "application/json"}})
          .then((response) => { if (!response.ok) throw new Error("Stock lookup failed"); return response.json(); })
          .then((data) => {
            if (row.dataset.stockRequest !== String(requestId) || product.value !== productId) return;
            const config = productUnits[productId] || (productUnits[productId] = {base: data.base_unit, units: []});
            config.stock = data.stock;
            config.base = data.base_unit;
            updateHint();
          })
          .catch(() => {
            if (row.dataset.stockRequest !== String(requestId)) return;
            if (opening) opening.textContent = "Unavailable";
            if (openingUnit) openingUnit.textContent = "Stock lookup failed";
            recalculate();
          });
      }
      function refresh() {
        const config = productUnits[product.value];
        const current = unit.value;
        unit.replaceChildren(new Option("Choose unit", ""));
        if (config) config.units.forEach(function (item) { unit.add(new Option(item.label, item.code)); });
        if (config && !config.units.some((item) => item.code === "PK")) {
          unit.add(new Option("Pack (enter conversion)", "PK"));
        }
        const preferred = config && config.units.some((item) => item.code === current) ? current
          : config && config.units.some((item) => item.code === config.base) ? config.base : "";
        unit.value = preferred;
        updateHint();
        fetchCurrentStock();
      }
      function updateHint() {
        const config = productUnits[product.value], item = config && config.units.find((u) => u.code === unit.value);
        const pack = unit.value === "PK";
        const configuredPack = pack && !!item;
        if (factorWrap) factorWrap.hidden = !pack || configuredPack;
        if (factorInput) {
          factorInput.disabled = !pack || configuredPack;
          factorInput.required = pack && !configuredPack;
          factorInput.readOnly = configuredPack;
          if (configuredPack) factorInput.value = item.factor;
          if (!pack) factorInput.value = "";
        }
        if (hint) hint.textContent = item ? "1 " + item.label + " = " + item.factor + " base units"
          : pack ? "Enter the number of base units in one pack." : "";
        const opening = row.querySelector("[data-opening-stock]");
        const openingUnit = row.querySelector("[data-opening-unit]");
        if (opening) opening.textContent = config && config.stock !== undefined ? Number(config.stock).toLocaleString(undefined, {maximumFractionDigits: 6}) : "—";
        if (openingUnit) openingUnit.textContent = config ? config.base : "";
        recalculate();
      }
      product.addEventListener("change", refresh);
      unit.addEventListener("change", updateHint);
      if (product.value) refresh();
    });
  }

  function recalculate() {
    let totalCost = 0;
    let totalItems = 0;
    let totalQuantity = 0;
    rows.querySelectorAll(".formset-row").forEach(function (row) {
      const qty = parseFloat(row.querySelector('input[name$="-quantity"]')?.value || "0");
      const cost = parseFloat(row.querySelector('input[name$="-unit_cost"]')?.value || "0");
      const deleted = row.querySelector('input[name$="-DELETE"]')?.checked;
      const line = Math.max(0, qty * cost);
      totalCost += deleted ? 0 : line;
      if (!deleted && row.querySelector('select[name$="-product"]')?.value) {
        totalItems += 1;
        totalQuantity += Math.max(0, qty);
      }
      let target = row.querySelector("[data-line-total]");
      if (target) target.textContent = line.toFixed(2);
      const product = row.querySelector('select[name$="-product"]');
      const unit = row.querySelector('select[name$="-unit_code"]');
      const config = product && productUnits[product.value];
      const selectedUnit = config && config.units.find((item) => item.code === unit?.value);
      const manualFactor = Number(row.querySelector('input[name$="-conversion_factor"]')?.value || "0");
      const factor = selectedUnit ? Number(selectedUnit.factor)
        : unit?.value === "PK" && manualFactor > 0 ? manualFactor
          : config && unit?.value === config.base ? 1 : 0;
      const opening = config && config.stock !== undefined ? Number(config.stock) : null;
      const incoming = qty * factor;
      const closing = row.querySelector("[data-closing-stock]");
      const closingUnit = row.querySelector("[data-closing-unit]");
      if (closing) closing.textContent = opening === null ? "Unavailable"
        : factor > 0 ? (opening + incoming).toLocaleString(undefined, {maximumFractionDigits: 6}) : "Enter pack conversion";
      if (closingUnit) closingUnit.textContent = config ? config.base : "";
    });
    document.querySelector("[data-total-items]")?.replaceChildren(document.createTextNode(String(totalItems)));
    document.querySelector("[data-total-quantity]")?.replaceChildren(document.createTextNode(totalQuantity.toLocaleString(undefined, {maximumFractionDigits: 6})));
    document.querySelector("[data-purchase-subtotal]")?.replaceChildren(document.createTextNode(totalCost.toFixed(2)));
    document.getElementById("purchase-total")?.replaceChildren(document.createTextNode(totalCost.toFixed(2)));
    const paid = parseFloat(document.querySelector('input[name="amount_paid"]')?.value || "0");
    const paymentStatus = document.querySelector("[data-payment-status]");
    if (paymentStatus) paymentStatus.textContent = totalCost <= 0 ? "No items"
      : paid >= totalCost ? "Paid" : paid > 0 ? "Partially paid" : "Unpaid";
  }

  function initProductPickers(root) {
    root.querySelectorAll("[data-product-picker]").forEach(function (picker) {
      if (picker.dataset.ready) return;
      const select = picker.querySelector("select");
      const input = picker.querySelector("[data-product-search]");
      if (!select || !input) return;
      picker.dataset.ready = "true";

      input.autocomplete = "off";
      input.setAttribute("role", "combobox");
      input.setAttribute("aria-autocomplete", "list");
      input.setAttribute("aria-expanded", "false");
      const list = document.createElement("div");
      list.id = input.id + "-options";
      list.className = "purchase-product-options";
      list.setAttribute("role", "listbox");
      input.setAttribute("aria-controls", list.id);
      list.hidden = true;
      picker.classList.add("has-product-picker");
      picker.appendChild(list);

      function options() {
        return Array.from(select.options).filter(function (option) { return option.value; });
      }
      function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); }
      function render(query) {
        const needle = query.trim().toLocaleLowerCase();
        const matches = options().filter(function (option) { return option.text.toLocaleLowerCase().includes(needle); });
        list.replaceChildren();
        matches.slice(0, 80).forEach(function (option) {
          const item = document.createElement("button");
          item.type = "button";
          item.className = "purchase-product-option";
          item.setAttribute("role", "option");
          item.textContent = option.text;
          item.addEventListener("mousedown", function (event) { event.preventDefault(); });
          item.addEventListener("click", function () {
            select.value = option.value;
            input.value = option.text;
            input.setCustomValidity("");
            select.dispatchEvent(new Event("change", { bubbles: true }));
            close();
          });
          list.appendChild(item);
        });
        if (!matches.length) {
          const empty = document.createElement("p");
          empty.className = "purchase-product-empty";
          empty.textContent = "No matching products";
          list.appendChild(empty);
        }
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
      }
      input.value = select.selectedOptions.length && select.value ? select.selectedOptions[0].text : "";
      // The visible search input takes over required validation after enhancement.
      input.required = select.required;
      select.required = false;
      input.addEventListener("focus", function () { render(input.value); });
      input.addEventListener("input", function () {
        select.value = "";
        input.setCustomValidity("Select a product from the search results.");
        render(input.value);
      });
      input.addEventListener("keydown", function (event) {
        if (event.key === "Escape") close();
        if (event.key === "Enter" && !list.hidden) {
          const first = list.querySelector(".purchase-product-option");
          if (first) { event.preventDefault(); first.click(); }
        }
      });
      input.addEventListener("blur", function () {
        window.setTimeout(function () {
          if (select.value) input.setCustomValidity("");
          close();
        }, 120);
      });
    });
  }

  initProductPickers(rows);
  initUnits(rows);
  rows.addEventListener("input", recalculate);
  rows.addEventListener("change", recalculate);
  document.getElementById("purchase-form")?.querySelector('input[name="amount_paid"]')?.addEventListener("input", recalculate);
  recalculate();
  btn.addEventListener("click", function () {
    const index = parseInt(total.value, 10);
    const html = tpl.innerHTML.replace(/__prefix__/g, String(index));
    rows.insertAdjacentHTML("beforeend", html);
    total.value = String(index + 1);
    initProductPickers(rows);
    initUnits(rows);
    recalculate();
  });
})();
