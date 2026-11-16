{% load static %}/* SmartMart service worker. Rendered by apps.store.pwa.service_worker (cache version: {{ version }}).
 *
 * Caching rules (privacy first):
 *  - Public catalogue pages (home, shop, categories, product pages) are cached AFTER removing the CSRF token,
 *    flash messages, the user's name and cart count. Cached copies carry <meta name="sm-cached">.
 *  - Cart, checkout, orders, profile, accounts, dashboard, admin and every /api/ call are NEVER cached.
 *    When offline, /cart/, /checkout/ and /orders/ show the offline shells, which render from IndexedDB.
 *  - Static files and product images are cached for speed and offline use.
 */
importScripts("{% static 'js/offline/offline-db.js' %}", "{% static 'js/offline/offline-sync.js' %}");

var VERSION = "{{ version }}";
var STATIC_CACHE = "smartmart-static-" + VERSION, PAGES_CACHE = "smartmart-pages-" + VERSION, IMAGES_CACHE = "smartmart-images-" + VERSION;
var KEEP = [STATIC_CACHE, PAGES_CACHE, IMAGES_CACHE];
var MAX_PAGES = 80, MAX_IMAGES = 250, NETWORK_TIMEOUT_MS = 4000;
var ADMIN_PREFIX = "/{{ admin_url }}";
var SHELLS = ["/offline/", "/offline/cart/", "/offline/checkout/", "/offline/orders/"];
var PRECACHE_STATIC = [
  "{% static 'css/storefront.css' %}", "{% static 'css/components.css' %}", "{% static 'js/storefront.js' %}",
  "{% static 'js/offline/offline-db.js' %}", "{% static 'js/offline/offline-sync.js' %}", "{% static 'js/offline/offline.js' %}",
  "{% static 'img/pwa/icon-192.png' %}", "{% static 'img/pwa/icon-512.png' %}"{% if USE_TAILWIND_CDN %},
  "{% static 'dist/output.css' %}"{% endif %}
];
var NEVER = ["/api/", "/accounts/", "/dashboard/", ADMIN_PREFIX, "/sw.js", "/manifest.webmanifest"];
var PRIVATE = ["/cart/", "/checkout/", "/orders/", "/profile/"];
var CATALOG = [/^\/$/, /^\/shop\/$/, /^\/categories\/$/, /^\/category\/[^/]+\/$/, /^\/search\/$/, /^\/product\/\d+\/$/, /^\/(about|help|contact)\/$/];
var CDN_HOSTS = ["cdn.tailwindcss.com"];

/* ---------- removing private data before a page is stored ---------- */
function sanitizeHtml(html) {
  return html
    .replace(/(<meta name="csrf-token" content=")[^"]*(")/g, "$1$2")
    .replace(/(name="csrfmiddlewaretoken" value=")[^"]*(")/g, "$1$2")
    .replace(/\sdata-user-id="[^"]*"/g, "").replace(/\sdata-user-role="[^"]*"/g, "")
    .replace(/(<[^>]*data-sm-private="name"[^>]*>)[^<]*(<)/g, "$1Account$2")
    .replace(/(<span class="sm-badge" data-cart-count>)[^<]*(<)/g, function (m, a, b) { return a + "0" + b; })
    .replace(/<!--sm-private-start-->[\s\S]*?<!--sm-private-end-->/g, "")
    .replace("<head>", '<head><meta name="sm-cached" content="1">');
}
function storeSanitized(cache, request, response) {
  var type = response.headers.get("content-type") || "";
  if (!response.ok || type.indexOf("text/html") === -1 || response.redirected) return Promise.resolve();
  return response.clone().text().then(function (html) {
    var headers = new Headers({ "Content-Type": "text/html; charset=utf-8", "X-SM-Cached-At": String(Date.now()) });
    return cache.put(request, new Response(sanitizeHtml(html), { status: 200, headers: headers }));
  }).then(function () { return trim(cache, MAX_PAGES); });
}
function trim(cache, max) {   // drop the oldest entries; the /offline/ shells are never evicted
  return cache.keys().then(function (keys) {
    keys = keys.filter(function (k) { return new URL(k.url).pathname.indexOf("/offline/") !== 0; });
    return Promise.all(keys.slice(0, Math.max(keys.length - max, 0)).map(function (k) { return cache.delete(k); }));
  });
}

/* ---------- lifecycle ---------- */
self.addEventListener("install", function (event) {
  event.waitUntil((async function () {
    var statics = await caches.open(STATIC_CACHE), pages = await caches.open(PAGES_CACHE);
    await Promise.all(PRECACHE_STATIC.map(function (u) { return statics.add(u).catch(function () {}); }));
    await Promise.all(SHELLS.map(function (u) {
      return fetch(u, { credentials: "same-origin" }).then(function (r) { return storeSanitized(pages, new Request(u), r); }).catch(function () {});
    }));
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (names) {
    return Promise.all(names.filter(function (n) { return n.indexOf("smartmart-") === 0 && KEEP.indexOf(n) === -1; }).map(function (n) { return caches.delete(n); }));
  }).then(function () { return self.clients.claim(); }));
});

/* ---------- helpers ---------- */
function startsWithAny(path, list) { return list.some(function (p) { return path.indexOf(p) === 0; }); }
function isCatalog(path) { return CATALOG.some(function (re) { return re.test(path); }); }
function timeout(ms) { return new Promise(function (_, reject) { setTimeout(function () { reject(new Error("timeout")); }, ms); }); }

function offlineFallbackFor(path) {
  var target = "/offline/";
  if (path === "/cart/") target = "/offline/cart/";
  else if (path === "/checkout/") target = "/offline/checkout/";
  else if (path === "/orders/") target = "/offline/orders/";
  return caches.open(PAGES_CACHE).then(function (c) { return c.match(target); }).then(function (r) {
    return r || new Response("<h1>You are offline</h1><p>Please reconnect to continue shopping.</p>", { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } });
  });
}

/* Network first, but fall back to the cached copy when the connection is down OR too slow to be useful. */
function catalogPage(request, url) {
  var cacheKey = new Request(url.origin + url.pathname + url.search);
  return caches.open(PAGES_CACHE).then(function (cache) {
    var network = fetch(request).then(function (response) { storeSanitized(cache, cacheKey, response.clone()); return response; });
    return cache.match(cacheKey).then(function (cached) {
      return (cached ? Promise.race([network, timeout(NETWORK_TIMEOUT_MS)]) : network).catch(function () {
        if (cached) return cached;
        return cache.match(new Request(url.origin + url.pathname)).then(function (base) { return base || offlineFallbackFor(url.pathname); });
      });
    });
  });
}

function staleWhileRevalidate(request, cacheName, max) {
  return caches.open(cacheName).then(function (cache) {
    return cache.match(request).then(function (cached) {
      var fresh = fetch(request).then(function (response) {
        if (response && (response.ok || response.type === "opaque")) { cache.put(request, response.clone()).then(function () { if (max) trim(cache, max); }); }
        return response;
      });
      if (cached) { fresh.catch(function () {}); return cached; }
      return fresh;
    });
  });
}

/* The checkout form was submitted but the connection failed: keep the order on the device. Never pretend it succeeded. */
function saveOfflineCheckout(request) {
  return request.formData().then(async function (form) {
    var DB = self.SmartMart.db, session = await DB.metaGet("session");
    var id = String(form.get("idempotency_key") || "");
    var back = "/offline/checkout/?saved=0";
    if (!session || session.userId == null || !id) return Response.redirect(back + "&reason=nosession", 303);
    var made = await DB.createOrder({
      id: id, customerRef: session.userId, customerName: String(form.get("customer_name") || "").trim(),
      phone: String(form.get("phone") || "").trim(), address: String(form.get("address") || "").trim(),
      deliveryInstructions: String(form.get("delivery_instructions") || "").trim()
    });
    if (!made.ok) return Response.redirect(back + "&reason=" + encodeURIComponent(made.error), 303);
    if (self.registration && self.registration.sync) { try { await self.registration.sync.register(self.SmartMart.sync.BG_TAG); } catch (e) {} }
    return Response.redirect("/offline/orders/?saved=" + encodeURIComponent(made.order.id), 303);
  });
}

/* ---------- fetch ---------- */
self.addEventListener("fetch", function (event) {
  var request = event.request, url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    if (request.method === "GET" && CDN_HOSTS.indexOf(url.hostname) > -1) event.respondWith(staleWhileRevalidate(request, STATIC_CACHE));
    return;
  }
  var path = url.pathname;
  if (request.method === "POST" && path === "/checkout/" && request.mode === "navigate") {
    event.respondWith(fetch(request.clone()).catch(function () { return saveOfflineCheckout(request); }));
    return;
  }
  if (request.method !== "GET" || startsWithAny(path, NEVER)) return;

  if (path.indexOf("/static/") === 0) { event.respondWith(staleWhileRevalidate(request, STATIC_CACHE)); return; }
  if (path.indexOf("/media/") === 0) { event.respondWith(staleWhileRevalidate(request, IMAGES_CACHE, MAX_IMAGES)); return; }

  var isNav = request.mode === "navigate" || request.headers.get("X-SM-Prefetch") === "1";
  if (!isNav) return;

  if (/^\/offline\//.test(path)) {   // the shells: cache first, they contain no private data
    event.respondWith(caches.open(PAGES_CACHE).then(function (c) { return c.match(new Request(url.origin + path)).then(function (r) { return r || fetch(request); }); }));
    return;
  }
  if (startsWithAny(path, PRIVATE)) {   // never cached; if the network is down show the offline shell
    event.respondWith(fetch(request).catch(function () { return request.mode === "navigate" ? offlineFallbackFor(path) : Response.error(); }));
    return;
  }
  if (isCatalog(path)) { event.respondWith(catalogPage(request, url)); return; }
  event.respondWith(fetch(request).catch(function () { return offlineFallbackFor(path); }));
});

/* ---------- Background Sync + messages ---------- */
self.addEventListener("sync", function (event) {
  if (event.tag !== self.SmartMart.sync.BG_TAG) return;
  event.waitUntil(self.SmartMart.sync.syncAll({ force: true }).then(function (r) { if (r && r.retry) throw new Error("retry later"); }));   // throwing makes the browser retry with its own backoff
});
self.addEventListener("message", function (event) {
  if (event.data && event.data.type === "SYNC_NOW") event.waitUntil(self.SmartMart.sync.syncAll({ force: !!event.data.force }));
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});
