/* SmartMart storefront: login modal, guest-safe Add to Cart, toasts, hero slides, browser-only wishlist. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = function () { var m = $('meta[name="csrf-token"]'); return m ? m.content : ""; };
  var AJAX = { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" };
  function readResponse(r) {
    return r.text().then(function (text) {
      var data = null;
      try { data = text ? JSON.parse(text) : {}; } catch (e) {}
      return { status: r.status, data: data };
    });
  }

  /* ---------- toasts ---------- */
  function toast(msg, isError) {
    var box = $("#sm-toasts"); if (!box) return;
    var t = document.createElement("div");
    t.className = "sm-toast" + (isError ? " err" : ""); t.textContent = msg; box.appendChild(t);
    setTimeout(function () { t.remove(); }, 3600);
  }

  /* ---------- auth modal ---------- */
  var modal = $("#auth-modal"), lastFocus = null, hasIntent = false;
  function setTab(name) {
    $$("[data-auth-tab]").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.authTab === name)); });
    $("#panel-login").hidden = name !== "login"; $("#panel-register").hidden = name !== "register";
    var first = $((name === "login" ? "#panel-login" : "#panel-register") + " input"); if (first) first.focus();
  }
  function clearErrors(form) { $$("[data-error-for]", form).forEach(function (e) { e.textContent = ""; }); }
  function openModal(tab, productName) {
    if (!modal) return false;
    lastFocus = document.activeElement;
    var intent = $("#auth-intent");
    hasIntent = !!productName;
    intent.hidden = !productName;
    if (productName) intent.textContent = "“" + productName + "” will be added to your cart as soon as you sign in.";
    modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false"); document.body.classList.add("sm-lock");
    setTab(tab || "login");
    return true;
  }
  function closeModal() {
    if (!modal || !modal.classList.contains("is-open")) return;
    modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); document.body.classList.remove("sm-lock");
    $$("[data-auth-form]").forEach(clearErrors);
    if (hasIntent) { // visitor cancelled: forget the remembered product so nothing is added later
      hasIntent = false;
      var url = document.body.dataset.pendingClearUrl;
      if (url) fetch(url, { method: "POST", headers: { "X-CSRFToken": csrf() }, credentials: "same-origin" }).catch(function () {});
    }
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  if (modal) {
    modal.addEventListener("mousedown", function (e) { if (e.target === modal) closeModal(); });
    $$("[data-modal-close]").forEach(function (b) { b.addEventListener("click", closeModal); });
    $$("[data-auth-tab]").forEach(function (b) { b.addEventListener("click", function () { setTab(b.dataset.authTab); }); });
    document.addEventListener("keydown", function (e) {
      if (!modal.classList.contains("is-open")) return;
      if (e.key === "Escape") closeModal();
      if (e.key === "Tab") { // keep focus inside the dialog
        var f = $$("button, input, a[href]", $("[data-modal-dialog]")).filter(function (x) { return !x.disabled && x.offsetParent !== null; });
        if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    $$("[data-auth-open]").forEach(function (a) {
      a.addEventListener("click", function (e) { if (openModal(a.dataset.authOpen)) e.preventDefault(); });
    });
    $$("[data-auth-form]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault(); clearErrors(form);
        var btn = $(".sm-submit", form); if (btn) btn.disabled = true;
        fetch(form.action, { method: "POST", body: new FormData(form), headers: AJAX, credentials: "same-origin" })
          .then(readResponse)
          .then(function (res) {
            if (res.data && res.data.ok) { window.location.assign(res.data.redirect || window.location.href); return; }
            if (!res.data) {
              var unexpected = $('[data-error-for="__all__"]', form);
              if (unexpected) unexpected.textContent = "The server returned an unexpected response (HTTP " + res.status + "). Refresh the page and try again.";
              if (btn) btn.disabled = false;
              return;
            }
            var errs = res.data.errors || { __all__: ["Something went wrong. Please try again."] };
            Object.keys(errs).forEach(function (k) {
              var el = $('[data-error-for="' + k + '"]', form) || $('[data-error-for="__all__"]', form);
              if (el) el.textContent = (el.textContent ? el.textContent + " " : "") + (Array.isArray(errs[k]) ? errs[k].join(" ") : String(errs[k]));
            });
            if (btn) btn.disabled = false;
          })
          .catch(function () { var el = $('[data-error-for="__all__"]', form); if (el) el.textContent = "Could not reach the server. Check your connection and try again."; if (btn) btn.disabled = false; });
      });
    });
  }

  /* ---------- Add to Cart (server decides; guests get the modal) ---------- */
  function setCount(n) { $$("[data-cart-count]").forEach(function (b) { b.textContent = n; }); }
  document.addEventListener("submit", function (e) {
    var form = e.target.closest ? e.target.closest("form.js-add-form") : null;
    if (!form) return;
    e.preventDefault();
    var btn = $("button[type=submit]", form); if (btn) btn.classList.add("is-loading");
    fetch(form.action, { method: "POST", body: new FormData(form), headers: AJAX, credentials: "same-origin" })
      .then(readResponse)
      .then(function (res) {
        if (!res.data) { toast("The server returned an unexpected response (HTTP " + res.status + "). Refresh and try again.", true); return; }
        if (res.status === 401 && res.data.login_required) {
          if (!openModal("login", form.dataset.productName)) window.location.assign(document.body.dataset.loginUrl || "/accounts/sign-in/");
        } else if (res.data.ok) { setCount(res.data.cart_count); toast(res.data.message || "Product added to your cart"); if (window.SmartMartOffline) SmartMartOffline.mirror(); }
        else toast(res.data.error || "Could not add this product.", true);
      })
      .catch(function (error) {
        if (window.SmartMartOffline && SmartMartOffline.handleAddFailure(form, error)) return;   // offline: saved to the device cart
        toast("Network problem. Please try again.", true);
      })
      .then(function () { if (btn) btn.classList.remove("is-loading"); });
  });

  /* ---------- wishlist (stored in this browser only) ---------- */
  var KEY = "smartmart_wishlist";
  function wishes() { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { return []; } }
  function saveWishes(list) { try { localStorage.setItem(KEY, JSON.stringify(list)); } catch (e) {} }
  function paintWishes() { var w = wishes(); $$("[data-wish]").forEach(function (b) { var on = w.indexOf(b.dataset.wish) > -1; b.classList.toggle("is-on", on); b.setAttribute("aria-pressed", String(on)); }); }
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-wish]") : null; if (!b) return;
    var w = wishes(), i = w.indexOf(b.dataset.wish);
    if (i > -1) w.splice(i, 1); else w.push(b.dataset.wish);
    saveWishes(w); paintWishes(); toast(i > -1 ? "Removed from wishlist" : "Saved to wishlist");
  });
  var wl = $("[data-wishlist-open]"); if (wl) wl.addEventListener("click", function () { var n = wishes().length; toast(n ? n + " item(s) saved in this browser's wishlist" : "Tap the heart on any product to save it"); });
  paintWishes();

  /* ---------- shop listing controls ---------- */
  var shopSort = $("#shop-sort"), shopProducts = $("[data-shop-products]");
  if (shopSort) shopSort.addEventListener("change", function () { shopSort.form.submit(); });
  $$('[data-auto-filter] input').forEach(function (control) {
    control.addEventListener("change", function () {
      if (control.form.requestSubmit) control.form.requestSubmit();
      else control.form.submit();
    });
  });
  if (shopProducts) {
    $$('[data-shop-view]').forEach(function (button) {
      button.addEventListener("click", function () {
        var view = button.dataset.shopView;
        shopProducts.classList.toggle("is-compact", view === "compact");
        shopProducts.classList.toggle("is-list", view === "list");
        $$('[data-shop-view]').forEach(function (control) {
          var selected = control === button;
          control.classList.toggle("is-selected", selected);
          control.setAttribute("aria-pressed", String(selected));
        });
      });
    });
  }

  /* ---------- hero slides ---------- */
  var track = $("[data-hero-slides]"), carousel = track ? track.closest(".sm-banner-carousel") : null;
  var slides = track ? $$(".sm-banner-slide", track) : [];
  var dots = $$("[data-hero-dot]"), cur = 0, timer;
  // Keep the requested automatic slide rotation enabled; CSS still removes
  // transition motion for visitors who prefer reduced motion.
  var autoplay = true, hovering = false;
  function show(n) {
    if (!slides.length) return;
    cur = (n + slides.length) % slides.length;
    slides.forEach(function (s, i) {
      s.classList.toggle("is-active", i === cur);
      s.setAttribute("aria-hidden", String(i !== cur));
      if (i === cur || i === (cur + 1) % slides.length) {
        var image = s.querySelector("img");
        if (image) image.loading = "eager";
      }
    });
    dots.forEach(function (d, i) {
      d.classList.toggle("is-active", i === cur);
      d.setAttribute("aria-current", String(i === cur));
    });
  }
  function auto() {
    clearTimeout(timer);
    if (!autoplay || hovering) return;
    timer = setTimeout(function () { show(cur + 1); auto(); }, 4500);
  }
  if (slides.length) {
    var p = $("[data-hero-prev]"), n = $("[data-hero-next]");
    show(0);
    if (p) p.addEventListener("click", function () { show(cur - 1); auto(); });
    if (n) n.addEventListener("click", function () { show(cur + 1); auto(); });
    dots.forEach(function (d) { d.addEventListener("click", function () { show(+d.dataset.heroDot); auto(); }); });
    if (carousel) {
      carousel.addEventListener("pointerenter", function (event) {
        if (event.pointerType === "mouse") { hovering = true; clearTimeout(timer); }
      });
      carousel.addEventListener("pointerleave", function (event) {
        if (event.pointerType === "mouse") { hovering = false; auto(); }
      });
      carousel.addEventListener("keydown", function (event) {
        if (event.key === "ArrowLeft") { show(cur - 1); auto(); }
        if (event.key === "ArrowRight") { show(cur + 1); auto(); }
      });
    }
    if (track) {
      var touchStart = null;
      track.addEventListener("pointerdown", function (event) {
        if (event.pointerType === "mouse") return;
        touchStart = { x: event.clientX, y: event.clientY };
      }, { passive: true });
      track.addEventListener("pointerup", function (event) {
        if (!touchStart) return;
        var dx = event.clientX - touchStart.x, dy = event.clientY - touchStart.y;
        touchStart = null;
        if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.2) {
          show(cur + (dx < 0 ? 1 : -1));
          auto();
        }
      }, { passive: true });
      track.addEventListener("pointercancel", function () { touchStart = null; });
    }
    auto();
  }

  /* ---------- contact form submit state ---------- */
  var contactForm = $("[data-contact-form]");
  if (contactForm) contactForm.addEventListener("submit", function () {
    var submit = contactForm.querySelector('button[type="submit"]');
    if (!submit || !contactForm.checkValidity()) return;
    submit.disabled = true;
    submit.setAttribute("aria-busy", "true");
    var label = submit.querySelector("span");
    if (label) label.textContent = "Sending...";
  });

  /* ---------- cart quantity controls ---------- */
  $$('[data-qty-step]').forEach(function (button) {
    button.addEventListener("click", function () {
      var input = button.parentNode.querySelector('input[type="number"]');
      if (!input) return;
      var current = Number(input.value) || 0, minimum = Number(input.min) || 0;
      var maximum = input.max === "" ? Infinity : Number(input.max);
      input.value = String(Math.max(minimum, Math.min(maximum, current + Number(button.dataset.qtyStep))));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
  function updateCartSummary(data) {
    var values = { subtotal: data.subtotal, discount: "-" + data.discount, delivery: Number(data.delivery_fee) ? data.delivery_fee : "Free", total: data.total };
    Object.keys(values).forEach(function (key) {
      var cell = $('[data-cart-total="' + key + '"]');
      if (cell) cell.textContent = key === "delivery" && values[key] === "Free" ? "Free" : "Rs. " + values[key];
    });
    $$('[data-cart-count]').forEach(function (badge) { badge.textContent = data.cart_count; });
    var count = $(".sm-cart-items-head > div > span");
    if (count) count.textContent = data.cart_count + " item" + (data.cart_count === 1 ? "" : "s");
    var checkout = $("[data-cart-checkout]");
    if (checkout && Boolean(checkout.disabled) !== data.has_problems) {
      if (data.has_problems) {
        var blocked = document.createElement("button");
        blocked.type = "button"; blocked.className = "sm-cart-checkout is-disabled";
        blocked.dataset.cartCheckout = ""; blocked.dataset.checkoutUrl = checkout.href;
        blocked.disabled = true; blocked.textContent = "Review item quantities";
        checkout.replaceWith(blocked);
        var note = $(".sm-cart-checkout-note"); if (note) { note.id = "cart-stock-message"; note.textContent = "Checkout is available after stock issues are resolved."; }
      } else {
        var ready = document.createElement("a");
        ready.className = "sm-cart-checkout"; ready.dataset.cartCheckout = "";
        ready.href = checkout.dataset.checkoutUrl || "/checkout/";
        ready.innerHTML = 'Proceed to Checkout <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-7-7 7 7-7 7"/></svg>';
        checkout.replaceWith(ready);
        var note = $(".sm-cart-checkout-note"); if (note) { note.removeAttribute("id"); note.textContent = "Secure checkout · Cash on delivery"; }
      }
    }
  }
  function saveCartQuantity(form) {
    if (form.dataset.saving === "true") return;
    form.dataset.saving = "true";
    var input = $('input[name="quantity"]', form), save = $(".sm-cart-update", form), row = form.closest("[data-cart-item]"), status = $("[data-cart-update-status]");
    var payload = new FormData(form);
    var quantityControls = $$("input,button", form);
    quantityControls.forEach(function (control) { control.disabled = true; });
    if (save) { save.disabled = true; save.textContent = "Saving…"; }
    fetch(form.action, { method: "POST", body: payload, headers: AJAX, credentials: "same-origin" })
      .then(readResponse)
      .then(function (res) {
        if (!res.data || !res.data.ok) throw new Error(res.data && res.data.error || "Could not update this item. Please try again.");
        if (res.data.removed && row) row.remove();
        else if (row) {
          input.value = res.data.quantity;
          var total = $(".sm-cart-line-total", row), mobileTotal = $(".sm-cart-mobile-total strong", row);
          if (total) total.textContent = "Rs. " + res.data.line_total;
          if (mobileTotal) mobileTotal.textContent = "Rs. " + res.data.line_total;
        }
        updateCartSummary(res.data);
        if (status) status.textContent = res.data.removed ? "Item removed." : "Cart updated.";
        if (res.data.items_count === 0) window.location.reload();
        if (window.SmartMartOffline) SmartMartOffline.mirror();
      })
      .catch(function (error) {
        if (window.SmartMartOffline && SmartMartOffline.handleCartFailure(form, error)) return;   // offline: change kept on the device
        if (status) status.textContent = error.message; toast(error.message, true);
      })
      .then(function () {
        form.dataset.saving = "false";
        quantityControls.forEach(function (control) { control.disabled = false; });
        if (save) { save.disabled = false; save.textContent = "Update"; }
      });
  }
  var cartSaveTimers = new WeakMap();
  $$("[data-cart-update-form]").forEach(function (form) {
    form.addEventListener("submit", function (event) { event.preventDefault(); clearTimeout(cartSaveTimers.get(form)); saveCartQuantity(form); });
    var input = $('input[name="quantity"]', form);
    if (input) {
      input.addEventListener("change", function () {
        clearTimeout(cartSaveTimers.get(form));
        cartSaveTimers.set(form, setTimeout(function () { saveCartQuantity(form); }, 250));
      });
      input.addEventListener("input", function () {
        clearTimeout(cartSaveTimers.get(form));
        cartSaveTimers.set(form, setTimeout(function () { saveCartQuantity(form); }, 500));
      });
    }
  });
  document.addEventListener("click", function (event) {
    var checkout = event.target.closest ? event.target.closest("[data-cart-checkout]") : null;
    if (checkout && checkout.tagName === "BUTTON" && !checkout.disabled) window.location.assign(checkout.dataset.checkoutUrl);
  });
})();
