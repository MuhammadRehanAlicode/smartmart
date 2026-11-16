(function () {
  const btn = document.getElementById("add-row");
  const tpl = document.getElementById("empty-form");
  const rows = document.getElementById("formset-rows");
  const total = document.querySelector('input[name$="-TOTAL_FORMS"]');
  if (!btn || !tpl || !rows || !total) return;
  const unitNode = document.getElementById("product-unit-data");
  const productUnits = unitNode ? JSON.parse(unitNode.textContent) : {};

  function initUnits(root) {
    root.querySelectorAll(".formset-row").forEach(function (row) {
      const product = row.querySelector('select[name$="-product"]');
      const unit = row.querySelector('select[name$="-unit_code"]');
      const hint = row.querySelector("[data-conversion-hint]");
      if (!product || !unit || unit.dataset.ready) return;
      unit.dataset.ready = "1";
      function refresh() {
        const config = productUnits[product.value];
        const current = unit.value;
        unit.replaceChildren(new Option("Choose unit", ""));
        if (config) config.units.forEach(function (item) { unit.add(new Option(item.label, item.code)); });
        const preferred = config && config.units.some((item) => item.code === current) ? current
          : config && config.units.some((item) => item.code === config.base) ? config.base : "";
        unit.value = preferred;
        updateHint();
      }
      function updateHint() {
        const config = productUnits[product.value], item = config && config.units.find((u) => u.code === unit.value);
        if (hint) hint.textContent = item ? "1 " + item.label + " = " + item.factor + " base units" : "";
        recalculate();
      }
      product.addEventListener("change", refresh);
      unit.addEventListener("change", updateHint);
      if (product.value) refresh();
    });
  }

  function recalculate() {
    let totalCost = 0;
    rows.querySelectorAll(".formset-row").forEach(function (row) {
      const qty = parseFloat(row.querySelector('input[name$="-quantity"]')?.value || "0");
      const cost = parseFloat(row.querySelector('input[name$="-unit_cost"]')?.value || "0");
      const box = parseFloat(row.querySelector('input[name$="-box_cost"]')?.value || "0");
      const deleted = row.querySelector('input[name$="-DELETE"]')?.checked;
      const line = Math.max(0, qty * cost + box);
      totalCost += deleted ? 0 : line;
      let target = row.querySelector("[data-line-total]");
      if (target) target.textContent = line.toFixed(2);
    });
    const target = document.getElementById("purchase-total");
    if (target) target.textContent = totalCost.toFixed(2);
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
