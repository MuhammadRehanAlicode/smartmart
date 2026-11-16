/* SmartMart order synchronisation engine. Loaded by pages AND by the service worker (Background Sync).
 *
 * - Orders are sent one at a time (sequentially), oldest first.
 * - The order's own UUID is the idempotency key, so a repeated request can never create a second order.
 * - Network problems / 5xx / timeouts: the order stays pending_sync and is retried with exponential backoff.
 * - A local order is only marked confirmed/rejected after the server has answered. It is never deleted by sync.
 */
(function (root) {
  "use strict";
  var NS = root.SmartMart, DB = NS.db, ST = NS.STATUS;
  var API_ORDERS = "/api/v1/offline/orders/", API_CART = "/api/v1/offline/cart/", API_CSRF = "/api/v1/auth/csrf/";
  var TIMEOUT_MS = 15000, STALE_SYNCING_MS = 2 * 60 * 1000, MAX_AUTO_ATTEMPTS = 8;
  var BASE_DELAY_MS = 5000, MAX_DELAY_MS = 15 * 60 * 1000;
  var csrfToken = null, csrfAt = 0;

  function backoff(attempts) {  // 5s, 10s, 20s ... capped at 15 min, +-20% jitter so devices don't retry in lockstep
    var d = Math.min(BASE_DELAY_MS * Math.pow(2, Math.max(attempts - 1, 0)), MAX_DELAY_MS);
    return Math.round(d * (0.8 + Math.random() * 0.4));
  }

  function request(url, opts) {
    var ctl = root.AbortController ? new root.AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, TIMEOUT_MS) : null;
    opts = opts || {}; opts.credentials = "same-origin"; opts.cache = "no-store";
    if (ctl) opts.signal = ctl.signal;
    return root.fetch(url, opts).then(function (res) {
      if (timer) clearTimeout(timer);
      return res.text().then(function (text) {
        var body = null; try { body = text ? JSON.parse(text) : null; } catch (e) {}
        return { status: res.status, body: body };
      });
    }, function (err) { if (timer) clearTimeout(timer); throw err; });   // rejects only on network failure / timeout
  }
  function getCsrf(force) {
    if (!force && csrfToken && Date.now() - csrfAt < 5 * 60 * 1000) return Promise.resolve(csrfToken);
    return request(API_CSRF, { method: "GET", headers: { "Accept": "application/json" } }).then(function (r) {
      if (!r.body || !r.body.csrfToken) throw new Error("no csrf token");
      csrfToken = r.body.csrfToken; csrfAt = Date.now(); return csrfToken;
    });
  }
  function sendJson(url, method, payload) {
    function attempt(force) {
      return getCsrf(force).then(function (token) {
        return request(url, { method: method, headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": token }, body: JSON.stringify(payload) });
      });
    }
    return attempt(false).then(function (r) {
      if (r.status === 403 && !(r.body && r.body.status)) return attempt(true);   // stale CSRF token: fetch a fresh one once
      return r;
    });
  }

  function payloadFor(o) {
    return {
      client_order_id: o.id, customer_ref: o.customerRef, created_at: o.createdAt, payment_method: o.paymentMethod || "cod",
      customer_name: o.customerName, phone: o.phone, address: o.address, delivery_instructions: o.deliveryInstructions || "",
      items: o.items.map(function (i) { return { product_id: i.productId, quantity: i.quantity, unit_price: i.unitPrice, currency: i.currency }; }),
      client_total: o.total, accepted_total: o.acceptedTotal || o.total
    };
  }

  function release(o, code, message) {   // temporary failure: keep the order, try again later
    var attempts = (o.attempts || 0) + 1;
    return DB.updateOrder(o.id, function (cur) {
      cur.attempts = attempts; cur.lastError = { code: code, message: message };
      if (attempts >= MAX_AUTO_ATTEMPTS && code !== "network") {
        cur.status = ST.ATTENTION; cur.lastError = { code: "too_many_attempts", message: "We could not reach the store after several tries. Tap Retry to try again." };
      } else { cur.status = ST.PENDING; cur.nextAttemptAt = Date.now() + backoff(attempts); }
      return cur;
    });
  }
  function finish(o, status, patch) {
    return DB.updateOrder(o.id, function (cur) { cur.status = status; for (var k in patch) cur[k] = patch[k]; return cur; });
  }

  /* Returns {network:true} when the connection failed (so the loop stops), otherwise {}. */
  function syncOne(o) {
    return sendJson(API_ORDERS, "POST", payloadFor(o)).then(function (r) {
      var b = r.body || {};
      if ((r.status === 200 || r.status === 201) && b.status === "confirmed") {
        return finish(o, ST.CONFIRMED, { serverOrderId: b.order_id, orderNumber: b.order_number, serverTotal: b.total, syncedAt: new Date().toISOString(), lastError: null, attempts: 0 })
          .then(function (n) { NS.notify("order-confirmed", { id: o.id, orderNumber: b.order_number }); return { done: true }; });
      }
      if (b.status === "rejected") {
        return finish(o, ST.REJECTED, { lastError: { code: b.reason_code || "rejected", message: b.reason || "The store could not accept this order." }, problems: b.items || [] })
          .then(function () { NS.notify("order-rejected", { id: o.id, reason: b.reason }); return { done: true }; });
      }
      if (b.status === "requires_attention") {
        return finish(o, ST.ATTENTION, { lastError: { code: b.reason_code || "attention", message: b.reason || "This order needs your attention." }, serverTotal: b.server_total || o.serverTotal || null, problems: b.items || [] })
          .then(function () { NS.notify("order-attention", { id: o.id, reason: b.reason }); return { done: true }; });
      }
      if (r.status === 401 || r.status === 403) {
        return finish(o, ST.ATTENTION, { lastError: { code: "auth_required", message: "Please sign in to finish sending this order." } })
          .then(function () { NS.notify("order-attention", { id: o.id, reason: "Please sign in to finish sending this order." }); return { done: true, auth: true }; });
      }
      if (r.status === 400) {
        return finish(o, ST.REJECTED, { lastError: { code: "invalid", message: b.reason || "The saved order contains invalid information." } })
          .then(function () { NS.notify("order-rejected", { id: o.id, reason: b.reason }); return { done: true }; });
      }
      return release(o, "server", "The store had a problem (HTTP " + r.status + "). We will try again.").then(function () { return { retry: true }; });
    }, function () {
      return release(o, "network", "No connection. We will try again automatically.").then(function () { return { network: true, retry: true }; });
    });
  }

  /* Push the cart that was changed offline to the server (idempotent "replace"), then refresh the local copy. */
  function syncCart() {
    return DB.metaGet("cartDirty").then(function (dirty) {
      if (!dirty) return { skipped: true };
      return DB.getAll("cart").then(function (lines) {
        var items = lines.map(function (i) { return { product_id: i.productId, quantity: i.quantity }; });
        return sendJson(API_CART, "PUT", { items: items }).then(function (r) {
          if (r.status === 200 && r.body && r.body.items) {
            return DB.cartReplace(r.body.items, false).then(function () {
              if (r.body.skipped && r.body.skipped.length) NS.notify("cart-adjusted", { skipped: r.body.skipped });
              return { done: true };
            });
          }
          return { pending: true };   // not signed in / server problem: keep the local cart, try again later
        }, function () { return { network: true }; });
      });
    });
  }
  function refreshCartMirror() {   // online and nothing changed offline: keep the local copy equal to the server cart
    return DB.metaGet("cartDirty").then(function (dirty) {
      if (dirty) return { skipped: true };
      return request(API_CART, { method: "GET", headers: { "Accept": "application/json" } }).then(function (r) {
        if (r.status === 200 && r.body && r.body.items) return DB.cartReplace(r.body.items, false).then(function () { return { done: true }; });
        return { skipped: true };
      }, function () { return { network: true }; });
    });
  }

  function requeueStale(session, authenticated) {
    return DB.getAll("orders").then(function (all) {
      var now = Date.now();
      return Promise.all(all.map(function (o) {
        var stale = o.status === ST.SYNCING && now - (o.syncStartedAt || 0) > STALE_SYNCING_MS;   // tab closed mid-request
        var resume = authenticated && o.status === ST.ATTENTION && o.lastError && o.lastError.code === "auth_required" && o.customerRef === session.userId;
        if (!stale && !resume) return null;
        return DB.updateOrder(o.id, function (cur) { cur.status = ST.PENDING; cur.nextAttemptAt = 0; if (resume) cur.attempts = 0; return cur; });
      }));
    });
  }

  function runSync(opts) {
    opts = opts || {};
    var out = { sent: 0, retry: false };
    return DB.metaGet("session").then(function (session) {
      if (!session || session.userId == null) return out;
      return requeueStale(session, !!opts.authenticated).then(function () { return syncCart(); }).then(function (c) {
        if (c && c.network) { out.retry = true; return out; }
        return DB.ordersFor(session.userId).then(function (orders) {
          var now = Date.now();
          var due = orders.filter(function (o) { return o.status === ST.PENDING && (opts.force || o.nextAttemptAt <= now); }).reverse();   // oldest first
          var chain = Promise.resolve(false);
          due.forEach(function (o) {
            chain = chain.then(function (stop) {
              if (stop) return true;
              return DB.claimOrder(o.id, !!opts.force).then(function (claimed) {
                if (!claimed) return false;
                return syncOne(claimed).then(function (r) { if (r.done) out.sent++; if (r.retry) out.retry = true; return !!r.network; });
              });
            });
          });
          return chain.then(function () { return out; });
        });
      });
    }).then(function (res) { NS.notify("sync-finished", res); return res; });
  }

  /* One sync at a time per browser (Web Locks); the server's idempotency covers browsers without it. */
  function syncAll(opts) {
    var nav = root.navigator;
    if (nav && nav.locks && nav.locks.request) {
      return nav.locks.request("smartmart-sync", { ifAvailable: true }, function (lock) { return lock ? runSync(opts) : { skipped: true }; });
    }
    return runSync(opts);
  }

  function pruneConfirmed() {   // synced orders are kept for a week so the customer can still see them, then dropped
    var limit = Date.now() - 7 * 24 * 3600 * 1000;
    return DB.getAll("orders").then(function (all) {
      return Promise.all(all.filter(function (o) { return o.status === ST.CONFIRMED && Date.parse(o.syncedAt || o.updatedAt) < limit; })
        .map(function (o) { return DB.discardOrder(o.id); }));
    });
  }

  NS.sync = { syncAll: syncAll, syncCart: syncCart, refreshCartMirror: refreshCartMirror, backoff: backoff, pruneConfirmed: pruneConfirmed,
              BG_TAG: "smartmart-sync-orders" };
})(typeof self !== "undefined" ? self : this);
