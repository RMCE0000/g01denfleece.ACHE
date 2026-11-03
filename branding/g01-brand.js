(function () {
  var LOGO = "/g01-logo.svg";
  var MARK = "/g01-mark.svg";

  function light() {
    var root = document.documentElement;
    if (root.classList.contains("dark")) root.classList.remove("dark");
    root.style.colorScheme = "light";
  }

  function isBrandLogo(src) {
    return /brand-assets\/logo|logo_dark|logo_thumbnail|\/logo\.svg(?:$|\?)/i.test(src || "");
  }

  function brandImages(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var images = root.querySelectorAll ? root.querySelectorAll("img") : [];
    images.forEach(function (img) {
      var src = img.getAttribute("src") || "";
      if (!isBrandLogo(src) || src.indexOf("g01-logo") !== -1) return;
      img.src = LOGO;
      img.alt = "g01";
    });
    document.querySelectorAll('link[rel~="icon"]').forEach(function (link) {
      var href = link.getAttribute("href") || "";
      if (href.indexOf("g01-mark") !== -1) return;
      if (/brand-assets|favicon|logo/i.test(href)) link.href = MARK;
    });
  }

  light();
  try {
    ["color_scheme", "theme", "cw_theme", "cw-theme", "appearance"].forEach(function (key) {
      localStorage.setItem(key, "light");
    });
  } catch (error) {
    /* private mode can block storage; the class observer still holds the light theme */
  }

  new MutationObserver(function () {
    light();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

  function watch() {
    brandImages(document);
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) brandImages(node);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.body) watch();
  else document.addEventListener("DOMContentLoaded", watch);
})();
