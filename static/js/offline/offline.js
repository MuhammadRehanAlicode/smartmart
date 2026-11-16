/* SmartMart offline-first storefront layer (page side).
 * Registers the service worker, keeps the offline cart, shows the connection indicator, renders the offline cart /
 * checkout / orders pages, and triggers synchronisation. It adds behaviour only - it does not restyle the store.
 */
(function () {
  "use strict";
  var NS = window.SmartMart;
  if (!NS || !NS.db || !NS.sync) return;
  var DB = NS.db, ST = NS.STATUS, body = document.body;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var cachedPage = !!$('meta[name="sm-cached"]');                      // served from the service worker cache: login state unknown
  var pageKind = ($("[data-offline-page]") || { dataset: {} }).dataset.offlinePage || "";
  var userId = body.dataset.userId ? Number(body.dataset.userId) : null;
  var isCustomer = body.dataset.userRole === "customer";
  var authenticatedNow = !cachedPage && navigator.onLine !== false && userId !== null && isCustomer;
  var LOGIN_URL = body.dataset.loginUrl || "/accounts/sign-in/";
  var currency = body.dataset.currency || "Rs.";

  /* ---------- tiny helpers ---------- */
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") n.textContent = attrs[k];
      else if (k === "html") n.innerHTML = attrs[k];   // only ever used with static markup below, never with user data
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function toast(msg, isError) {
    var box = $("#sm-toasts"); if (!box) return;
    var t = el("div", { "class": "sm-toast" + (isError ? " err" : ""), text: msg }); box.appendChild(t);
    setTimeout(function () { t.remove(); }, 4500);
  }
  function fmt(v) { return currency + " " + DB.money(v); }
  function when(iso) { try { return new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }); } catch (e) { return iso; } }
  function getSession() { return DB.metaGet("session"); }
  var ICON_REMOVE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M6 7l1 14h10l1-14M9 7V4h6v3"/></svg><span>Remove</span>';
  var ICON_ARROW = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-7-7 7 7-7 7"/></svg>';

  /* ---------- service worker ---------- */
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }
  function requestBackgroundSync() {   // browsers without Background Sync simply rely on the online event + timer below
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.ready.then(function (reg) { if (reg.sync) return reg.sync.register(NS.sync.BG_TAG); }).catch(function () {});
  }

  /* ---------- session, pricing, product capture ---------- */
  function captureSession() {
    var work = [];
    if (body.dataset.deliveryFee) {
      work.push(DB.metaSet("pricing", { deliveryFee: body.dataset.deliveryFee, freeDelivery: body.dataset.freeDelivery, currency: currency }));
    }
    if (cachedPage || navigator.onLine === false) return Promise.all(work);   // login state unknown: change nothing
    if (userId !== null && isCustomer) {
      work.push(getSession().then(function (prev) {
        var save = function () { return DB.metaSet("session", { userId: userId, at: Date.now() }); };
        return prev && prev.userId !== userId ? DB.clearPrivate().then(save) : save();
      }));
      var form = $("#checkout-form");
      if (form && form.elements.customer_name) {
        work.push(DB.metaSet("profile", { customerName: form.elements.customer_name.value, phone: form.elements.phone.value, address: form.elements.address.value }));
      }
    } else {   // signed out, session expired, or a staff account
      work.push(DB.metaDelete("session"));
      work.push(DB.metaGet("cartDirty").then(function (dirty) { if (!dirty) return DB.cartReplace([], false); }));
    }
    return Promise.all(work);
  }
  function captureProducts() {
    var list = [];
    $$("form.js-add-form").forEach(function (f) {
      var d = f.dataset, input = f.querySelector('input[name="product_id"]'), id = input ? Number(input.value) : 0;
      if (!id || !d.price) return;
      list.push({ id: id, name: d.productName, price: d.price, listPrice: d.listPrice || d.price, image: d.image || "", stock: Number(d.stock), sku: d.sku || "" });
    });
    if (!list.length) return;
    DB.run("products", "readwrite", function (s) { list.forEach(function (p) { s.products.put(p); }); }).catch(function () {});
  }
  function infoFromForm(form) {
    var d = form.dataset;
    return { name: d.productName, price: d.price, listPrice: d.listPrice || d.price, image: d.image || "", stock: d.stock !== undefined && d.stock !== "" ? Number(d.stock) : undefined, sku: d.sku || "" };
  }

  /* ---------- catalogue prefetch (so products can be browsed offline) ---------- */
  function prefetchCatalog() {
    if (!navigator.onLine || cachedPage || !("serviceWorker" in navigator) || !navigator.serviceWorker.controller) return;
    try { var last = Number(localStorage.getItem("sm_prefetch_at") || 0); if (Date.now() - last < 30 * 60 * 1000) return; localStorage.setItem("sm_prefetch_at", String(Date.now())); } catch (e) {}
    var seen = {}, queue = ["/", "/shop/", "/categories/"], imgs = [], count = 0;
    function links(html) {
      var re = /href="(\/(?:product\/\d+|category\/[^"\/]+)\/)"/g, m;
      while ((m = re.exec(html)) && queue.length < 40) { if (!seen[m[1]] && queue.indexOf(m[1]) < 0) queue.push(m[1]); }
      var ire = /<img[^>]+src="(\/(?:media|static)\/[^"]+)"/g;
      while ((m = ire.exec(html)) && imgs.length < 90) { if (imgs.indexOf(m[1]) < 0) imgs.push(m[1]); }
    }
    $$("a[href]").forEach(function (a) { var h = a.getAttribute("href"); if (/^\/(product\/\d+|category\/[^\/]+)\/$/.test(h) && queue.indexOf(h) < 0 && queue.length < 40) queue.push(h); });
    function next() {
      var url = queue.shift();
      if (!url || count >= 40 || !navigator.onLine) return images();
      seen[url] = true; count++;
      return fetch(url, { credentials: "same-origin", headers: { "X-SM-Prefetch": "1" } })
        .then(function (r) { return r.ok ? r.text() : ""; }).then(links).catch(function () {}).then(next);
    }
    function images() {
      var batch = imgs.splice(0, 6);
      if (!batch.length || !navigator.onLine) return;
      return Promise.all(batch.map(function (u) { return fetch(u).catch(function () {}); })).then(images);
    }
    setTimeout(function () { next(); }, 2500);
  }

  /* ---------- connection indicator ---------- */
  var pill = $("[data-conn-status]");
  function updateStatus() {
    var offline = navigator.onLine === false;
    return getSession().then(function (s) { return s ? DB.ordersFor(s.userId) : []; }).then(function (orders) {
      var pending = orders.filter(function (o) { return o.status === ST.PENDING || o.status === ST.SYNCING; }).length;
      var syncing = orders.some(function (o) { return o.status === ST.SYNCING; });
      var attention = orders.filter(function (o) { return o.status === ST.ATTENTION; }).length;
      var text = "", state = "";
      if (offline) { text = pending ? "Offline · " + pending + " pending" : "Offline"; state = "offline"; }
      else if (syncing) { text = "Syncing…"; state = "syncing"; }
      else if (pending) { text = pending + " order" + (pending > 1 ? "s" : "") + " waiting to sync"; state = "pending"; }
      else if (attention) { text = attention + " order" + (attention > 1 ? "s" : "") + " need attention"; state = "attention"; }
      if (pill) { pill.hidden = !text; pill.textContent = text; pill.dataset.state = state; }
      document.documentElement.classList.toggle("sm-is-offline", offline);
      return orders;
    }).catch(function () {});
  }
  function updateBadge() {
    if (!(navigator.onLine === false || cachedPage || pageKind)) return Promise.resolve();
    return getSession().then(function (s) { if (!s) return; return DB.cartCount().then(function (n) { $$("[data-cart-count]").forEach(function (b) { b.textContent = n; }); }); });
  }

  /* ---------- offline cart actions used by storefront.js ---------- */
  function addFromForm(form) {
    var pid = Number((form.querySelector('input[name="product_id"]') || {}).value), qtyInput = form.querySelector('input[name="quantity"]');
    var qty = Math.max(1, Number(qtyInput && qtyInput.value) || 1);
    getSession().then(function (session) {
      if (!session) { toast("You are offline. Log in when you are back online to start shopping.", true); return; }
      return DB.cartAdd(pid, qty, infoFromForm(form)).then(function (r) {
        if (!r.ok) { toast(r.error === "out_of_stock" ? "This product is out of stock." : "Could not add this product while offline.", true); return; }
        toast("Added to your cart. It will be saved to your account when you are online.");
        return DB.cartCount().then(function (n) { $$("[data-cart-count]").forEach(function (b) { b.textContent = n; }); });
      });
    }).catch(function () { toast("Could not save to the offline cart on this device.", true); });
    return true;
  }
  function networkFailure(error) { return navigator.onLine === false || !!(error && error.name === "TypeError"); }
  function handleAddFailure(form, error) { return networkFailure(error) ? addFromForm(form) : false; }
  function handleCartFailure(form, error) {
    if (!networkFailure(error)) return false;
    var row = form.closest("[data-cart-item]"), pid = Number(row && row.dataset.productId), q = form.querySelector('input[name="quantity"]');
    if (!pid) return false;
    DB.cartSet(pid, Math.max(0, Number(q && q.value) || 0)).then(function (r) { if (r && r.ok) window.location.reload(); }).catch(function () {});
    return true;
  }
  function mirror() { if (navigator.onLine !== false && authenticatedNow) NS.sync.syncCart().then(function () { return NS.sync.refreshCartMirror(); }).then(updateAll).catch(function () {}); }

  /* ---------- sync triggers ---------- */
  var running = false;
  function trigger(opts) {
    if (running || navigator.onLine === false) return Promise.resolve();
    running = true;
    return NS.sync.syncAll(opts || {}).catch(function () {}).then(function () { running = false; return updateAll(); }, function () { running = false; });
  }
  function updateAll() {
    return updateStatus().then(function () {
      var box = $("[data-offline-orders]"); if (box) renderOrders(box, pageKind === "orders");
      return updateBadge();
    });
  }

  /* ---------- orders list ---------- */
  var STATUS_TEXT = {};
  STATUS_TEXT[ST.PENDING] = "Saved on this device · waiting for internet";
  STATUS_TEXT[ST.SYNCING] = "Sending to W&B General Store…";
  STATUS_TEXT[ST.CONFIRMED] = "Confirmed";
  STATUS_TEXT[ST.REJECTED] = "Not accepted";
  STATUS_TEXT[ST.ATTENTION] = "Needs your attention";

  function actionButton(label, handler, primary) {
    var b = el("button", { type: "button", "class": "btn " + (primary ? "btn-primary" : "btn-outline"), style: "min-height:2.25rem;padding:.35rem .9rem;font-size:.9rem", text: label });
    b.addEventListener("click", function () { b.disabled = true; handler().catch(function () {}).then(updateAll); });
    return b;
  }
  function renderOrderCard(o) {
    var err = o.lastError || {}, badgeClass = "alert" + (o.status === ST.CONFIRMED ? " alert-success" : (o.status === ST.REJECTED || o.status === ST.ATTENTION) ? " alert-error" : "");
    var title = o.status === ST.CONFIRMED && o.orderNumber ? o.orderNumber : "Order saved on this device";
    var count = o.items.reduce(function (n, i) { return n + i.quantity; }, 0);
    var card = el("div", { "class": "card", "data-offline-order": o.id, "data-status": o.status, style: "margin-bottom:.75rem" });
    card.appendChild(el("div", { "class": "flex flex-wrap justify-between gap-2" }, [
      el("strong", { text: title }),
      el("span", { "class": badgeClass, style: "padding:.1rem .6rem;display:inline-block;margin:0", text: STATUS_TEXT[o.status] || o.status })]));
    card.appendChild(el("p", { "class": "help", text: when(o.createdAt) + " · " + fmt(o.total) + " · " + count + " item" + (count === 1 ? "" : "s") + " · Cash on delivery" }));
    if (o.status === ST.PENDING) card.appendChild(el("p", { "class": "help", text: "This order is NOT confirmed yet. It will be sent automatically when you are back online." + (o.attempts ? " Last attempt: " + (err.message || "no connection") : "") }));
    if (o.status === ST.CONFIRMED) card.appendChild(el("p", { "class": "help", text: "W&B General Store has received your order." }));
    if ((o.status === ST.REJECTED || o.status === ST.ATTENTION) && err.message) card.appendChild(el("p", { style: "margin:.4rem 0;color:#B42318", text: err.message }));
    var det = el("details", { style: "margin:.4rem 0" }, [el("summary", { text: "View items" })]);
    var ul = el("ul", { style: "margin:.4rem 0 0 1.1rem;list-style:disc" });
    o.items.forEach(function (i) { ul.appendChild(el("li", { text: i.quantity + " × " + i.name + " — " + fmt(Number(i.unitPrice) * i.quantity) })); });
    det.appendChild(ul); card.appendChild(det);

    var actions = el("div", { "class": "flex flex-wrap gap-2", style: "margin-top:.5rem" });
    var syncNow = function () { return trigger({ force: true, authenticated: authenticatedNow }); };
    if (o.status === ST.PENDING) actions.appendChild(actionButton("Retry now", function () { return DB.retryNow(o.id).then(syncNow); }, true));
    if (o.status === ST.CONFIRMED && o.serverOrderId) actions.appendChild(el("a", { "class": "btn btn-outline", style: "min-height:2.25rem;padding:.35rem .9rem;font-size:.9rem", href: "/orders/" + o.serverOrderId + "/", text: "View order" }));
    if (o.status === ST.REJECTED) {
      if (["insufficient_stock", "unavailable"].indexOf(err.code) > -1) actions.appendChild(actionButton("Try again", function () { return DB.retryAsNew(o.id).then(syncNow); }, true));
      actions.appendChild(actionButton("Remove", function () { return DB.discardOrder(o.id); }));
    }
    if (o.status === ST.ATTENTION) {
      if (err.code === "price_changed" && o.serverTotal) actions.appendChild(actionButton("Accept new total (" + fmt(o.serverTotal) + ")", function () { return DB.acceptNewTotal(o.id).then(syncNow); }, true));
      if (err.code === "auth_required") actions.appendChild(el("a", { "class": "btn btn-primary", style: "min-height:2.25rem;padding:.35rem .9rem;font-size:.9rem", href: LOGIN_URL, text: "Log in to continue" }));
      if (["network", "server", "too_many_attempts"].indexOf(err.code) > -1) actions.appendChild(actionButton("Retry now", function () { return DB.retryNow(o.id).then(syncNow); }, true));
      actions.appendChild(actionButton("Remove", function () { return DB.discardOrder(o.id); }));
    }
    if (actions.childNodes.length) card.appendChild(actions);
    return card;
  }
  function renderOrders(container, isShell) {
    return getSession().then(function (s) { return s ? DB.ordersFor(s.userId) : []; }).then(function (orders) {
      var recent = Date.now() - 10 * 60 * 1000;
      var shown = orders.filter(function (o) { return isShell || o.status !== ST.CONFIRMED || Date.parse(o.syncedAt || o.updatedAt) > recent; });
      container.textContent = "";
      if (!shown.length) {
        if (isShell) container.appendChild(el("div", { "class": "card text-center" }, [el("p", { text: "You have no orders saved on this device." }), el("a", { "class": "btn btn-primary", style: "margin-top:.75rem", href: "/shop/", text: "Keep shopping" })]));
        return;
      }
      if (!isShell) container.appendChild(el("h2", { "class": "text-xl font-bold mb-3", text: "Saved on this device" }));
      shown.forEach(function (o) { container.appendChild(renderOrderCard(o)); });
    });
  }

  /* ---------- offline cart page ---------- */
  function cartTotals(lines, pricing) { return DB.computeTotals(lines, pricing); }
  function renderCartShell(root) {
    return Promise.all([getSession(), DB.getAll("cart"), DB.metaGet("pricing")]).then(function (r) {
      var session = r[0], lines = r[1].filter(function (i) { return i.quantity > 0; }), pricing = r[2];
      root.textContent = "";
      if (!session) { root.appendChild(el("section", { "class": "sm-cart-empty" }, [el("h2", { text: "Log in to see your cart" }), el("p", { text: "You are offline, and we cannot tell which account this device belongs to. Reconnect and log in." }), el("a", { "class": "sm-cart-checkout", href: LOGIN_URL, text: "Log in" })])); return; }
      if (!lines.length) {
        root.appendChild(el("section", { "class": "sm-cart-empty", "aria-labelledby": "empty-cart-title" }, [
          el("div", { "class": "sm-cart-empty-icon", html: '<svg class="sm-ic"><use href="#i-cart"/></svg>' }),
          el("span", { "class": "sm-cart-eyebrow", text: "A little room for something fresh" }),
          el("h2", { id: "empty-cart-title", text: "Your cart is waiting" }),
          el("p", { text: "Explore fresh groceries and everyday essentials, then add your favorites here." }),
          el("a", { "class": "sm-cart-checkout", href: "/shop/", html: "Browse products " + ICON_ARROW })]));
        return;
      }
      var t = cartTotals(lines, pricing), count = lines.reduce(function (n, i) { return n + i.quantity; }, 0);
      var layout = el("div", { "class": "sm-cart-layout" });
      var items = el("section", { "class": "sm-cart-items", "aria-label": "Items in your cart" });
      items.appendChild(el("div", { "class": "sm-cart-items-head" }, [el("div", {}, [el("h2", { text: "Cart items" }), el("span", { text: count + " item" + (count === 1 ? "" : "s") })]), el("span", { "class": "sm-cart-head-note", text: "Price" })]));
      lines.forEach(function (i) {
        var line = fmt(Number(i.price) * i.quantity), step = function (d) { return DB.cartSet(i.productId, i.quantity + d).then(function () { return renderCartShell(root); }).then(updateAll); };
        var input = el("input", { id: "oq" + i.productId, type: "number", name: "quantity", min: "0", max: String(i.stock), value: String(i.quantity), inputmode: "numeric", "aria-label": "Quantity of " + i.name });
        input.addEventListener("change", function () { DB.cartSet(i.productId, Math.max(0, Number(input.value) || 0)).then(function () { return renderCartShell(root); }).then(updateAll); });
        var minus = el("button", { type: "button", "aria-label": "Decrease quantity of " + i.name, text: "−" }), plus = el("button", { type: "button", "aria-label": "Increase quantity of " + i.name, text: "+" });
        minus.addEventListener("click", function () { step(-1); }); plus.addEventListener("click", function () { step(1); });
        var remove = el("button", { type: "button", "aria-label": "Remove " + i.name + " from cart", html: ICON_REMOVE });
        remove.addEventListener("click", function () { DB.cartSet(i.productId, 0).then(function () { return renderCartShell(root); }).then(updateAll); });
        var low = i.stock <= 5 ? el("span", { "class": "sm-cart-stock-low", text: "Only " + i.stock + " left" }) : null;
        items.appendChild(el("article", { "class": "sm-cart-item", "data-cart-item": String(i.productId), "data-product-id": String(i.productId) }, [
          el("a", { "class": "sm-cart-product-image", href: "/product/" + i.productId + "/" }, [el("img", { src: i.image, alt: i.name })]),
          el("div", { "class": "sm-cart-product-info" }, [
            el("a", { "class": "sm-cart-product-name", href: "/product/" + i.productId + "/", text: i.name }),
            el("span", { "class": "sm-cart-unit-price", text: fmt(i.price) + " " }, [el("small", { text: "each" })]), low,
            el("div", { "class": "sm-cart-mobile-total", text: "Line total " }, [el("strong", { text: line })])]),
          el("div", { "class": "sm-cart-controls" }, [el("div", { "class": "sm-cart-quantity-form" }, [el("label", { "for": "oq" + i.productId, text: "Quantity" }), el("div", { "class": "sm-cart-quantity-control" }, [minus, input, plus])])]),
          el("strong", { "class": "sm-cart-line-total", text: line }),
          el("div", { "class": "sm-cart-remove-form" }, [remove])]));
      });
      items.appendChild(el("div", { "class": "sm-cart-bottom-link", html: '<svg class="sm-ic"><use href="#i-refresh"/></svg>Need something else? <a href="/shop/">Keep browsing</a>' }));
      var aside = el("aside", { "class": "sm-cart-summary", "aria-labelledby": "cart-summary-title" });
      aside.appendChild(el("div", { "class": "sm-cart-summary-title", html: '<i><svg class="sm-ic"><use href="#i-cart"/></svg></i><h2 id="cart-summary-title">Order Summary</h2>' }));
      var dl = el("dl", { "class": "grid grid-cols-2 gap-1 mt-3" });
      [["Subtotal", fmt(t.subtotal)], ["Discounts", "-" + fmt(t.discount)], ["Delivery", Number(t.deliveryFee) ? fmt(t.deliveryFee) : "Free"], ["Total", fmt(t.total)]].forEach(function (row, idx) {
        dl.appendChild(el("dt", { "class": idx === 3 ? "text-xl font-bold" : "help", text: row[0] }));
        dl.appendChild(el("dd", { "class": "text-right" + (idx === 3 ? " text-xl font-bold" : ""), text: row[1] }));
      });
      aside.appendChild(dl);
      aside.appendChild(el("a", { "class": "sm-cart-checkout", href: "/checkout/", html: "Proceed to Checkout " + ICON_ARROW }));
      aside.appendChild(el("p", { "class": "sm-cart-checkout-note", text: navigator.onLine === false ? "You are offline · totals are estimates and are confirmed by W&B General Store · Cash on delivery" : "Secure checkout · Cash on delivery" }));
      layout.appendChild(items); layout.appendChild(aside); root.appendChild(layout);
    });
  }

  /* ---------- offline checkout page ---------- */
  var PHONE_RE = /^\+?[0-9]{10,15}$/;
  function initCheckoutShell(root) {
    var form = $("#offline-checkout-form", root), summary = $("[data-offline-summary]", root), done = $("[data-offline-saved]", root);
    var params = new URLSearchParams(location.search);
    if (params.get("saved") === "0") {
      var reasons = { nosession: "We could not tell which account this device belongs to. Please log in when you are online.", empty_cart: "Your cart is empty.", unknown: "Something went wrong." };
      toast(reasons[params.get("reason")] || "Your order could not be saved on this device.", true);
    }
    Promise.all([getSession(), DB.getAll("cart"), DB.metaGet("pricing"), DB.metaGet("profile")]).then(function (r) {
      var session = r[0], lines = r[1].filter(function (i) { return i.quantity > 0; }), pricing = r[2], profile = r[3];
      var errBox = $("[data-offline-error]", root);
      if (!session || !lines.length) {
        form.hidden = true; summary.hidden = true;
        errBox.hidden = false;
        errBox.textContent = !session ? "Log in when you are online before placing an order." : "Your cart is empty. Add products first.";
        return;
      }
      if (profile) { ["customer_name", "phone", "address"].forEach(function (k) { var f = form.elements[k]; var v = profile[{ customer_name: "customerName", phone: "phone", address: "address" }[k]]; if (f && v && !f.value) f.value = v; }); }
      var t = cartTotals(lines, pricing), list = $("[data-offline-lines]", root);
      lines.forEach(function (i) {
        list.appendChild(el("article", { "class": "sm-checkout-order-item" }, [
          el("div", { "class": "sm-checkout-order-image" }, [el("img", { src: i.image, alt: "" }), el("span", { text: String(i.quantity) })]),
          el("div", { "class": "sm-checkout-order-info" }, [el("b", { text: i.name }), el("small", { text: fmt(i.price) + " each" })]),
          el("strong", { text: fmt(Number(i.price) * i.quantity) })]));
      });
      var totals = $("[data-offline-totals]", root); totals.textContent = "";
      [["Subtotal", fmt(t.subtotal)], ["Discounts", "-" + fmt(t.discount)], ["Delivery", Number(t.deliveryFee) ? fmt(t.deliveryFee) : "Free"], ["Total (estimate)", fmt(t.total)]].forEach(function (row, idx) {
        totals.appendChild(el("dt", { "class": idx === 3 ? "text-xl font-bold" : "help", text: row[0] }));
        totals.appendChild(el("dd", { "class": "text-right" + (idx === 3 ? " text-xl font-bold" : ""), text: row[1] }));
      });
      $("[data-offline-cod-total]", root).textContent = fmt(t.total);

      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var v = { customerName: form.elements.customer_name.value.trim(), phone: form.elements.phone.value.trim(), address: form.elements.address.value.trim(), deliveryInstructions: form.elements.delivery_instructions.value.trim() };
        var bad = {};
        if (!v.customerName) bad.customer_name = "Please enter your name.";
        if (!PHONE_RE.test(v.phone)) bad.phone = "Enter a valid phone number (10-15 digits, optional leading +).";
        if (v.address.length < 8) bad.address = "Please enter a full delivery address.";
        $$("[data-offline-field-error]", form).forEach(function (n) { n.textContent = bad[n.dataset.offlineFieldError] || ""; });
        if (Object.keys(bad).length) return;
        var btn = $("button[type=submit]", form); btn.disabled = true;
        v.customerRef = session.userId;
        DB.createOrder(v).then(function (res) {
          if (!res.ok) { btn.disabled = false; toast("Your cart is empty.", true); return; }
          form.hidden = true; summary.hidden = true; done.hidden = false;
          $("[data-offline-saved-total]", done).textContent = fmt(res.order.total);
          requestBackgroundSync(); updateAll(); trigger({ authenticated: authenticatedNow });
        }).catch(function () { btn.disabled = false; toast("Could not save the order on this device. Nothing was placed.", true); });
      });
    });
  }

  /* ---------- wire everything ---------- */
  function init() {
    captureSession().catch(function () {}).then(function () {
      captureProducts();
      var chain = Promise.resolve();
      if (authenticatedNow) {
        // an order/cart changed offline must reach the server BEFORE the server-rendered cart/checkout is used
        chain = DB.metaGet("cartDirty").then(function (dirty) {
          if (dirty) return NS.sync.syncCart().then(function (r) { if (r && r.done && /^\/(cart|checkout)\/$/.test(location.pathname)) location.reload(); });
          var last = Number(sessionStorage.getItem("sm_mirror_at") || 0), forced = /^\/(cart|checkout)\/$/.test(location.pathname);
          if (forced || Date.now() - last > 60000) { try { sessionStorage.setItem("sm_mirror_at", String(Date.now())); } catch (e) {} return NS.sync.refreshCartMirror(); }
        }).catch(function () {});
      }
      return chain.then(function () {
        updateAll();
        if (navigator.onLine !== false) { trigger({ authenticated: authenticatedNow }); NS.sync.pruneConfirmed().catch(function () {}); prefetchCatalog(); }
        else requestBackgroundSync();
        var cartRoot = $("[data-offline-cart-root]"), checkoutRoot = $("[data-offline-checkout]");
        if (pageKind === "cart" && cartRoot) renderCartShell(cartRoot);
        if (pageKind === "checkout" && checkoutRoot) initCheckoutShell(checkoutRoot);
        if (pageKind === "orders") {
          var shell = $("[data-offline-orders]");
          if (shell && new URLSearchParams(location.search).get("saved")) { var ban = $("[data-offline-saved-banner]"); if (ban) ban.hidden = false; }
        }
      });
    });
  }
  window.addEventListener("online", function () { toast("You are back online."); updateAll(); requestBackgroundSync(); trigger({ force: true, authenticated: authenticatedNow }); });
  window.addEventListener("offline", function () { toast("You are offline. You can keep shopping; orders are saved on this device until you reconnect."); updateAll(); });
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") { updateAll(); trigger({ authenticated: authenticatedNow }); } });
  setInterval(function () { if (navigator.onLine !== false) trigger({ authenticated: authenticatedNow }); }, 30000);   // fallback for browsers without Background Sync
  NS.listen(function (msg) {
    if (!msg) return;
    if (msg.type === "order-confirmed") toast("Your order " + (msg.detail.orderNumber || "") + " has been confirmed.");
    if (msg.type === "order-rejected") toast("An order could not be accepted: " + (msg.detail.reason || "see My orders for details."), true);
    if (msg.type === "order-attention") toast("An order needs your attention: " + (msg.detail.reason || "see My orders."), true);
    if (msg.type === "cart-adjusted") toast("Some products in your cart are no longer available and were removed.", true);
    if (msg.type === "sync-finished") updateAll();
  });

  /* offline remove button on the server-rendered cart page, and logout hygiene */
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (f.matches && f.matches(".sm-cart-remove-form") && navigator.onLine === false) {
      e.preventDefault();
      var row = f.closest("[data-cart-item]"), pid = Number(row && row.dataset.productId);
      if (pid) DB.cartSet(pid, 0).then(function () { window.location.reload(); });
      return;
    }
    if (f.matches && f.matches('form[action$="/logout/"]')) {
      e.preventDefault();
      DB.clearPrivate().catch(function () {}).then(function () { f.submit(); });   // pending orders stay on the device; cart and profile do not
    }
  });

  window.SmartMartOffline = { addFromForm: addFromForm, handleAddFailure: handleAddFailure, handleCartFailure: handleCartFailure, mirror: mirror, syncNow: function () { return trigger({ force: true, authenticated: authenticatedNow }); } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
