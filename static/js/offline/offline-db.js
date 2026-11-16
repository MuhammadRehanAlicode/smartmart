/* SmartMart offline storage (IndexedDB). Loaded by pages AND by the service worker (importScripts).
 *
 * Stores:  orders   - orders placed offline (never deleted until the server has answered)
 *          cart     - the offline cart / local copy of the customer's cart
 *          products - minimal product info captured from pages so the cart can work offline
 *          meta     - small key/value items (session, cartDirty, pricing, profile)
 * Never stored: card numbers, CVVs, passwords, tokens. Payment method is "cod" (cash on delivery) only.
 */
(function (root) {
  "use strict";
  var NS = root.SmartMart = root.SmartMart || {};
  var DB_NAME = "smartmart-offline", DB_VERSION = 1;
  var dbPromise = null;

  var STATUS = { PENDING: "pending_sync", SYNCING: "syncing", CONFIRMED: "confirmed", REJECTED: "rejected", ATTENTION: "requires_attention" };

  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      if (!root.indexedDB) { reject(new Error("IndexedDB is not available")); return; }
      var req = root.indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains("orders")) {
          var o = db.createObjectStore("orders", { keyPath: "id" });
          o.createIndex("status", "status"); o.createIndex("customerRef", "customerRef");
        }
        if (!db.objectStoreNames.contains("cart")) db.createObjectStore("cart", { keyPath: "productId" });
        if (!db.objectStoreNames.contains("products")) db.createObjectStore("products", { keyPath: "id" });
        if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "key" });
      };
      req.onsuccess = function () {
        var db = req.result;
        db.onversionchange = function () { db.close(); dbPromise = null; };
        resolve(db);
      };
      req.onerror = function () { dbPromise = null; reject(req.error); };
    });
    return dbPromise;
  }

  /* run(storeNames, mode, work): work(stores, setResult) executes inside ONE transaction. */
  function run(storeNames, mode, work) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var names = [].concat(storeNames), tx = db.transaction(names, mode), result;
        tx.oncomplete = function () { resolve(result); };
        tx.onerror = function () { reject(tx.error || new Error("IndexedDB transaction failed")); };
        tx.onabort = function () { reject(tx.error || new Error("IndexedDB transaction aborted")); };
        var stores = {};
        names.forEach(function (n) { stores[n] = tx.objectStore(n); });
        try { work(stores, function (v) { result = v; }); } catch (e) { try { tx.abort(); } catch (_) {} reject(e); }
      });
    });
  }
  function getAll(store) { return run(store, "readonly", function (s, set) { var r = s[store].getAll(); r.onsuccess = function () { set(r.result); }; }); }
  function get(store, key) { return run(store, "readonly", function (s, set) { var r = s[store].get(key); r.onsuccess = function () { set(r.result); }; }); }
  function put(store, value) { return run(store, "readwrite", function (s) { s[store].put(value); }); }
  function del(store, key) { return run(store, "readwrite", function (s) { s[store].delete(key); }); }

  /* ---------- helpers ---------- */
  function uuid() {
    if (root.crypto && root.crypto.randomUUID) return root.crypto.randomUUID();
    var b = new Uint8Array(16); root.crypto.getRandomValues(b);
    b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    var h = Array.prototype.map.call(b, function (x) { return ("0" + x.toString(16)).slice(-2); }).join("");
    return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
  }
  function toCents(v) { return Math.round(parseFloat(v) * 100) || 0; }
  function fromCents(c) { return (c / 100).toFixed(2); }
  function money(v) { return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

  /* Estimate only - the server recomputes every price and total before accepting an order. */
  function computeTotals(items, pricing) {
    pricing = pricing || {};
    var fee = pricing.deliveryFee != null ? toCents(pricing.deliveryFee) : 15000;
    var free = pricing.freeDelivery != null ? toCents(pricing.freeDelivery) : 200000;
    var sub = 0, goods = 0;
    items.forEach(function (i) {
      sub += i.quantity * toCents(i.listPrice != null ? i.listPrice : i.price);
      goods += i.quantity * toCents(i.price);
    });
    var delivery = items.length && goods < free ? fee : 0;
    return { subtotal: fromCents(sub), discount: fromCents(sub - goods), goods: fromCents(goods),
             deliveryFee: fromCents(delivery), total: fromCents(goods + delivery) };
  }

  /* ---------- notifications between page and service worker ---------- */
  function notify(type, detail) {
    try { if (root.BroadcastChannel) { var c = new root.BroadcastChannel("smartmart-offline"); c.postMessage({ type: type, detail: detail || {} }); c.close(); } } catch (e) {}
  }
  function listen(fn) {
    try { if (root.BroadcastChannel) { var c = new root.BroadcastChannel("smartmart-offline"); c.onmessage = function (e) { fn(e.data); }; return c; } } catch (e) {}
    return null;
  }

  /* ---------- cart ---------- */
  function setCartDirty(stores, value) { stores.meta.put({ key: "cartDirty", value: !!value }); }

  /* Change one line of the offline cart. qty <= 0 removes it. Marks the cart as "changed offline". */
  function cartSet(productId, qty, info) {
    return run(["cart", "products", "meta"], "readwrite", function (s, set) {
      var r = s.cart.get(productId);
      r.onsuccess = function () {
        var line = r.result;
        var pr = s.products.get(productId);
        pr.onsuccess = function () {
          var base = info || line || pr.result;
          if (!base) { set({ ok: false, error: "unknown_product" }); return; }
          var stock = base.stock != null ? Number(base.stock) : 100;
          if (qty > 0 && stock < 1) { set({ ok: false, error: "out_of_stock" }); return; }
          qty = Math.min(qty, Math.max(stock, 1), 100);
          if (qty <= 0) { s.cart.delete(productId); }
          else {
            s.cart.put({ productId: productId, name: base.name, sku: base.sku || "", price: base.price,
                         listPrice: base.listPrice != null ? base.listPrice : base.price, image: base.image || "",
                         stock: stock, quantity: qty });
          }
          setCartDirty(s, true);
          set({ ok: true, quantity: Math.max(qty, 0) });
        };
      };
    });
  }
  function cartAdd(productId, qty, info) {
    return get("cart", productId).then(function (line) { return cartSet(productId, (line ? line.quantity : 0) + qty, info); });
  }
  function cartReplace(items, dirty) {
    return run(["cart", "meta"], "readwrite", function (s) {
      s.cart.clear();
      items.forEach(function (i) {
        s.cart.put({ productId: i.product_id, name: i.name, sku: i.sku || "", price: i.price, listPrice: i.list_price || i.price,
                     image: i.image || "", stock: i.stock, quantity: i.quantity });
      });
      setCartDirty(s, dirty);
    });
  }
  function cartCount() { return getAll("cart").then(function (l) { return l.reduce(function (n, i) { return n + i.quantity; }, 0); }); }

  /* ---------- orders ---------- */
  /* Creates the order and empties the cart in ONE transaction: either both happen or neither. */
  function createOrder(input) {
    return run(["cart", "orders", "meta"], "readwrite", function (s, set) {
      var id = input.id || uuid();
      var existing = s.orders.get(id);
      existing.onsuccess = function () {
        if (existing.result) { set({ ok: true, order: existing.result, existing: true }); return; }
        var c = s.cart.getAll();
        c.onsuccess = function () {
          var lines = c.result.filter(function (i) { return i.quantity > 0; });
          if (!lines.length) { set({ ok: false, error: "empty_cart" }); return; }
          var pm = s.meta.get("pricing");
          pm.onsuccess = function () {
            var pricing = pm.result ? pm.result.value : {};
            var items = lines.map(function (i) {
              return { productId: i.productId, name: i.name, sku: i.sku, image: i.image, quantity: i.quantity,
                       unitPrice: i.price, listPrice: i.listPrice, currency: pricing.currency || "Rs." };
            });
            var totals = computeTotals(lines, pricing);
            var now = new Date().toISOString();
            var order = {
              id: id, customerRef: input.customerRef, createdAt: now, updatedAt: now, paymentMethod: "cod",
              currency: pricing.currency || "Rs.", customerName: input.customerName, phone: input.phone,
              address: input.address, deliveryInstructions: input.deliveryInstructions || "",
              items: items, totals: totals, total: totals.total, acceptedTotal: totals.total,
              status: STATUS.PENDING, attempts: 0, nextAttemptAt: 0, lastError: null
            };
            s.orders.put(order);
            s.cart.clear();
            setCartDirty(s, true);   // the server copy of the cart must be emptied once we are online
            set({ ok: true, order: order });
          };
        };
      };
    });
  }

  /* Atomically take an order for syncing, so two tabs / the service worker never send it at the same time. */
  function claimOrder(id, force) {
    return run("orders", "readwrite", function (s, set) {
      var r = s.orders.get(id);
      r.onsuccess = function () {
        var o = r.result, now = Date.now();
        if (!o || o.status !== STATUS.PENDING || (!force && o.nextAttemptAt > now)) { set(null); return; }
        o.status = STATUS.SYNCING; o.syncStartedAt = now; o.updatedAt = new Date().toISOString();
        s.orders.put(o); set(o);
      };
    });
  }
  /* Read-modify-write a single order. mutate(order) returns the new order or null to leave it alone. */
  function updateOrder(id, mutate) {
    return run("orders", "readwrite", function (s, set) {
      var r = s.orders.get(id);
      r.onsuccess = function () {
        var o = r.result; if (!o) { set(null); return; }
        var n = mutate(o); if (!n) { set(o); return; }
        n.updatedAt = new Date().toISOString(); s.orders.put(n); set(n);
      };
    });
  }
  function acceptNewTotal(id) {
    return updateOrder(id, function (o) {
      if (o.status !== STATUS.ATTENTION || !o.serverTotal) return null;
      o.acceptedTotal = o.serverTotal; o.status = STATUS.PENDING; o.attempts = 0; o.nextAttemptAt = 0; o.lastError = null; return o;
    });
  }
  function retryNow(id) {
    return updateOrder(id, function (o) {
      if (o.status === STATUS.PENDING) { o.nextAttemptAt = 0; return o; }
      if (o.status === STATUS.ATTENTION && ["network", "server", "auth_required", "too_many_attempts"].indexOf(o.lastError && o.lastError.code) > -1) {
        o.status = STATUS.PENDING; o.attempts = 0; o.nextAttemptAt = 0; return o;
      }
      return null;
    });
  }
  /* A rejected order is final on the server. "Try again" keeps the customer's data under a NEW id. */
  function retryAsNew(id) {
    return run("orders", "readwrite", function (s, set) {
      var r = s.orders.get(id);
      r.onsuccess = function () {
        var o = r.result; if (!o || o.status !== STATUS.REJECTED) { set(null); return; }
        var copy = JSON.parse(JSON.stringify(o)), now = new Date().toISOString();
        copy.id = uuid(); copy.createdAt = copy.updatedAt = now; copy.status = STATUS.PENDING; copy.attempts = 0;
        copy.nextAttemptAt = 0; copy.lastError = null; copy.serverTotal = null; copy.acceptedTotal = copy.total;
        delete copy.syncStartedAt; delete copy.serverOrderId; delete copy.orderNumber;
        s.orders.put(copy); s.orders.delete(id); set(copy);
      };
    });
  }
  /* Only finished orders can be removed, and only by an explicit customer action. */
  function discardOrder(id) {
    return run("orders", "readwrite", function (s, set) {
      var r = s.orders.get(id);
      r.onsuccess = function () {
        var o = r.result;
        if (o && (o.status === STATUS.REJECTED || o.status === STATUS.CONFIRMED || o.status === STATUS.ATTENTION)) { s.orders.delete(id); set(true); } else set(false);
      };
    });
  }
  function ordersFor(userId) {
    return getAll("orders").then(function (all) {
      return all.filter(function (o) { return userId != null && o.customerRef === userId; })
                .sort(function (a, b) { return a.createdAt < b.createdAt ? 1 : -1; });
    });
  }

  /* ---------- meta ---------- */
  function metaGet(key) { return get("meta", key).then(function (r) { return r ? r.value : undefined; }); }
  function metaSet(key, value) { return put("meta", { key: key, value: value }); }
  function metaDelete(key) { return del("meta", key); }

  /* Called on logout / when another customer signs in: private cart data must not stay on the device. */
  function clearPrivate() {
    return run(["cart", "meta"], "readwrite", function (s) {
      s.cart.clear(); s.meta.delete("session"); s.meta.delete("cartDirty"); s.meta.delete("profile");
    });
  }

  NS.STATUS = STATUS;
  NS.db = {
    open: open, getAll: getAll, get: get, put: put, del: del, run: run, uuid: uuid,
    computeTotals: computeTotals, money: money, toCents: toCents,
    cartSet: cartSet, cartAdd: cartAdd, cartReplace: cartReplace, cartCount: cartCount,
    createOrder: createOrder, claimOrder: claimOrder, updateOrder: updateOrder, acceptNewTotal: acceptNewTotal,
    retryNow: retryNow, retryAsNew: retryAsNew, discardOrder: discardOrder, ordersFor: ordersFor,
    metaGet: metaGet, metaSet: metaSet, metaDelete: metaDelete, clearPrivate: clearPrivate
  };
  NS.notify = notify; NS.listen = listen;
})(typeof self !== "undefined" ? self : this);
