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

  function onLoginPage() {
    return location.pathname.replace(/\/+$/, "") === "/app/login" && location.search.indexOf("sso_auth_token=") === -1;
  }

  function field(labelText, name, type, placeholder) {
    var label = document.createElement("label");
    label.style.display = "block";
    label.style.marginBottom = "0.85rem";
    var caption = document.createElement("span");
    caption.textContent = labelText;
    caption.style.display = "block";
    caption.style.marginBottom = "0.25rem";
    caption.style.fontSize = "0.875rem";
    caption.style.fontWeight = "600";
    var input = document.createElement("input");
    input.name = name;
    input.type = type;
    input.required = true;
    input.autocomplete = type === "password" ? "new-password" : name;
    if (placeholder) input.placeholder = placeholder;
    if (name === "password") input.minLength = 8;
    if (name === "zip_code") input.inputMode = "numeric";
    label.appendChild(caption);
    label.appendChild(input);
    return label;
  }

  function ensureSignup() {
    if (!onLoginPage()) {
      document.body.classList.remove("g01-signup-open");
      var stale = document.getElementById("g01-signup");
      if (stale) stale.remove();
      return;
    }
    if (document.getElementById("g01-signup")) return;
    var heading = document.querySelector("h2");
    if (!heading || !heading.parentNode) return;

    var block = document.createElement("div");
    block.id = "g01-signup";

    var prompt = document.createElement("p");
    prompt.className = "mt-3 text-sm text-center text-n-slate-11";
    prompt.appendChild(document.createTextNode("New here? "));
    var open = document.createElement("button");
    open.type = "button";
    open.className = "g01-signup-link";
    open.textContent = "Create an account";
    prompt.appendChild(open);

    var card = document.createElement("section");
    card.id = "g01-signup-card";
    card.className = "g01-signup-card bg-white shadow sm:mx-auto mt-11 sm:w-full sm:max-w-lg p-11 sm:shadow-lg sm:rounded-lg";
    card.hidden = true;

    var title = document.createElement("h2");
    title.textContent = "Create an account";
    title.style.marginTop = "0";
    title.style.fontSize = "1.5rem";
    var lead = document.createElement("p");
    lead.textContent = "This opens your sign-in and a thread with Jane. Use a ZIP that is already on the record, such as 70601.";
    lead.style.margin = "0.5rem 0 1rem";
    lead.style.color = "#5c5346";

    var form = document.createElement("form");
    form.appendChild(field("Full name", "name", "text", "Ada Yard"));
    form.appendChild(field("Email", "email", "email", "ada@example.com"));
    form.appendChild(field("Password", "password", "password", "At least 8 characters"));
    form.appendChild(field("ZIP code", "zip_code", "text", "70601"));

    var error = document.createElement("p");
    error.className = "g01-signup-error";
    error.hidden = true;
    var submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = "Create account";
    var back = document.createElement("p");
    back.style.marginTop = "0.85rem";
    back.style.textAlign = "center";
    var backButton = document.createElement("button");
    backButton.type = "button";
    backButton.className = "g01-signup-back";
    backButton.textContent = "Already have an account? Log in";
    back.appendChild(backButton);

    form.appendChild(error);
    form.appendChild(submit);
    card.appendChild(title);
    card.appendChild(lead);
    card.appendChild(form);
    card.appendChild(back);
    block.appendChild(prompt);
    block.appendChild(card);
    heading.parentNode.appendChild(block);

    function setOpen(isOpen) {
      card.hidden = !isOpen;
      prompt.hidden = isOpen;
      document.body.classList.toggle("g01-signup-open", isOpen);
      error.hidden = true;
    }

    open.addEventListener("click", function () {
      setOpen(true);
    });
    backButton.addEventListener("click", function () {
      setOpen(false);
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      error.hidden = true;
      submit.disabled = true;
      function value(name) {
        return form.querySelector('[name="' + name + '"]').value;
      }
      var payload = {
        name: value("name"),
        email: value("email"),
        password: value("password"),
        zip_code: value("zip_code"),
      };
      fetch("/g01/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      })
        .then(function (response) {
          return response.json().then(function (body) {
            return { ok: response.ok, body: body };
          });
        })
        .then(function (result) {
          if (result.ok && result.body && result.body.sso_url) {
            window.location.assign(result.body.sso_url);
            return;
          }
          if (result.ok) {
            setOpen(false);
            return;
          }
          var detail = result.body && result.body.detail;
          error.textContent = typeof detail === "string" ? detail : "Account was not created.";
          error.hidden = false;
        })
        .catch(function () {
          error.textContent = "Account was not created.";
          error.hidden = false;
        })
        .then(function () {
          submit.disabled = false;
        });
    });
  }

  function watchSignup() {
    ensureSignup();
    new MutationObserver(function () {
      ensureSignup();
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.body) watchSignup();
  else document.addEventListener("DOMContentLoaded", watchSignup);
})();
