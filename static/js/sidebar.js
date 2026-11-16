(function () {
  "use strict";
  var sidebar = document.getElementById("sidebar");
  var toggle = document.getElementById("sidebar-toggle");
  var backdrop = document.getElementById("sidebar-backdrop");
  var shell = document.querySelector(".ad-main-shell");
  if (!sidebar || !toggle || !shell) return;
  var KEY = "smartmart.admin-sidebar.collapsed";
  var mobile = function () { return window.matchMedia("(max-width: 981px)").matches; };
  function closeMobile() {
    sidebar.classList.remove("is-open");
    if (backdrop) backdrop.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open navigation");
  }
  try {
    if (!mobile() && localStorage.getItem(KEY) === "1") {
      sidebar.classList.add("collapsed");
      shell.classList.add("is-collapsed");
    }
  } catch (e) {}
  toggle.setAttribute("aria-expanded", String(!mobile() && !sidebar.classList.contains("collapsed")));
  toggle.setAttribute("aria-label", mobile() ? "Open navigation" : (sidebar.classList.contains("collapsed") ? "Expand navigation" : "Collapse navigation"));
  toggle.addEventListener("click", function () {
    if (mobile()) {
      var open = sidebar.classList.toggle("is-open");
      if (backdrop) backdrop.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
      return;
    }
    var collapsed = sidebar.classList.toggle("collapsed");
    shell.classList.toggle("is-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "Expand navigation" : "Collapse navigation");
    try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) {}
  });
  if (backdrop) backdrop.addEventListener("click", closeMobile);
  sidebar.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", function () { if (mobile()) closeMobile(); });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && sidebar.classList.contains("is-open")) closeMobile();
  });
  window.addEventListener("resize", function () { if (!mobile()) closeMobile(); });
})();
