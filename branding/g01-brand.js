(function () {
  var LOGO = "/g01-logo.png";
  var MARK = "/g01-favicon.png?v=6";

  function light() {
    var root = document.documentElement;
    if (root.classList.contains("dark")) root.classList.remove("dark");
    root.style.colorScheme = "light";
  }

  function isBrandLogo(src) {
    return /brand-assets\/logo|logo_dark|logo_thumbnail|\/logo\.svg(?:$|\?)|\/g01-(?:mark|favicon)/i.test(src || "");
  }

  function brandImages(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var images = root.querySelectorAll ? root.querySelectorAll("img") : [];
    images.forEach(function (img) {
      var src = img.getAttribute("src") || "";
      if (!isBrandLogo(src) || src.indexOf("g01-logo") !== -1) return;
      img.src = /thumbnail|g01-(?:mark|favicon)/i.test(src) ? MARK : LOGO;
      img.alt = "g01";
    });
    document.querySelectorAll('link[rel~="icon"]').forEach(function (link) {
      link.href = MARK;
      link.type = "image/png";
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
    if (name === "password") {
      input.minLength = 8;
      input.autocomplete = "new-password";
    }
    if (name === "username") {
      input.minLength = 3;
      input.maxLength = 32;
      input.pattern = "[a-z][a-z0-9._-]{2,31}";
      input.autocapitalize = "none";
      input.spellcheck = false;
    }
    if (name === "zip_code") input.inputMode = "numeric";
    label.appendChild(caption);
    label.appendChild(input);
    if (name === "password") {
      var help = document.createElement("small");
      help.className = "g01-field-help";
      help.textContent = "Use 8+ characters with uppercase, lowercase, a number, and a special character.";
      label.appendChild(help);
    }
    return label;
  }

  function ensureSignup() {
    if (!onLoginPage()) {
      document.body.classList.remove("g01-signup-open");
      document.body.classList.remove("g01-login-page");
      var stale = document.getElementById("g01-signup");
      if (stale) stale.remove();
      return;
    }
    document.body.classList.add("g01-login-page");
    var heading = document.querySelector("h2");
    if (!heading || !heading.parentNode) return;
    if (/login to chatwoot/i.test(heading.textContent || "")) {
      heading.textContent = "Sign in to g01";
    }
    if (/chatwoot/i.test(document.title)) document.title = "Sign in · g01";
    if (document.getElementById("g01-signup")) return;

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
    lead.textContent = "Use a ZIP that is already on the record, such as 70601.";
    lead.style.margin = "0.5rem 0 1rem";
    lead.style.color = "#5c5346";

    var form = document.createElement("form");
    form.appendChild(field("Full name", "name", "text", "Ada Yard"));
    form.appendChild(field("Username", "username", "text", "ada.yard"));
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
        username: value("username"),
        email: value("email"),
        password: value("password"),
        zip_code: value("zip_code"),
      };
      var passwordIsValid =
        payload.password.length >= 8 &&
        /[A-Z]/.test(payload.password) &&
        /[a-z]/.test(payload.password) &&
        /[0-9]/.test(payload.password) &&
        /[!@#$%^&*()_+\-=[\]{}|'"\/\\.,`<>:;?~]/.test(payload.password);
      if (!passwordIsValid) {
        error.textContent =
          "Password must be at least 8 characters and include uppercase, lowercase, a number, and a special character.";
        error.hidden = false;
        submit.disabled = false;
        return;
      }
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

  function currentAccountId() {
    var match = location.pathname.match(/^\/app\/accounts\/(\d+)(?:\/|$)/);
    return match ? match[1] : null;
  }

  function communityHeaders() {
    return { "X-G01-Requested-With": "community-v1" };
  }

  function closeCommunity() {
    var modal = document.getElementById("g01-community-modal");
    if (modal) modal.remove();
    var opener = document.getElementById("g01-community-open");
    if (opener) opener.focus();
  }

  function communityElement(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (typeof text === "string") element.textContent = text;
    return element;
  }

  function showCommunityError(panel, message) {
    var error = panel.querySelector(".g01-community-error");
    error.textContent = message;
    error.hidden = false;
  }

  function renderCommunityState(panel, payload) {
    var identity = panel.querySelector(".g01-community-identity");
    var self = payload && payload.self;
    identity.textContent = self && self.username ? "Your username: @" + self.username : "";
    var list = panel.querySelector(".g01-community-list");
    list.replaceChildren();
    var connections = payload && Array.isArray(payload.connections) ? payload.connections : [];
    if (!connections.length) {
      list.appendChild(communityElement("p", "g01-community-empty", "You have no existing homesteader conversations."));
      return;
    }
    connections.forEach(function (connection) {
      var card = communityElement("article", "g01-community-member");
      card.appendChild(communityElement("h3", "", connection.name || "Homesteader"));
      var details = "@" + (connection.username || "unknown") + " · " + (connection.locality || "Locality not recorded");
      card.appendChild(communityElement("p", "g01-community-locality", details));
      var open = communityElement("a", "g01-community-primary", "Open conversation");
      open.href = connection.conversation_path;
      card.appendChild(open);
      list.appendChild(card);
    });
  }

  function openCommunity() {
    if (document.getElementById("g01-community-modal")) return;
    var accountId = currentAccountId();
    if (!accountId || !window.axios) return;

    var backdrop = communityElement("div", "g01-community-backdrop");
    backdrop.id = "g01-community-modal";
    backdrop.setAttribute("role", "presentation");
    var panel = communityElement("section", "g01-community-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-labelledby", "g01-community-title");
    var header = communityElement("header", "g01-community-header");
    var title = communityElement("h2", "", "g01 Community");
    title.id = "g01-community-title";
    var close = communityElement("button", "g01-community-close", "Close");
    close.type = "button";
    close.addEventListener("click", closeCommunity);
    header.appendChild(title);
    header.appendChild(close);
    panel.appendChild(header);
    panel.appendChild(
      communityElement(
        "p",
        "g01-community-intro",
        "Enter the username of a peer to start a conversation."
      )
    );
    panel.appendChild(communityElement("p", "g01-community-identity"));
    var form = communityElement("form", "g01-community-dial");
    var username = communityElement("input", "g01-community-username");
    username.type = "text";
    username.required = true;
    username.minLength = 3;
    username.maxLength = 33;
    username.placeholder = "@username";
    username.autocapitalize = "none";
    username.spellcheck = false;
    username.setAttribute("aria-label", "Homesteader username");
    var topic = communityElement("input", "g01-community-topic");
    topic.type = "text";
    topic.maxLength = 255;
    topic.placeholder = "Optional topic";
    topic.setAttribute("aria-label", "Conversation topic");
    var start = communityElement("button", "g01-community-primary", "Start conversation");
    start.type = "submit";
    form.appendChild(username);
    form.appendChild(topic);
    form.appendChild(start);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      start.disabled = true;
      panel.querySelector(".g01-community-error").hidden = true;
      window.axios
        .post(
          "/api/v1/accounts/" + accountId + "/g01/community",
          { username: username.value.trim(), topic: topic.value.trim() || null },
          { headers: communityHeaders() }
        )
        .then(function (response) {
          var data = response && response.data;
          if (!data || !data.conversation_path) throw new Error("Conversation path missing");
          window.location.assign(data.conversation_path);
        })
        .catch(function (requestError) {
          var detail = requestError && requestError.response && requestError.response.data;
          showCommunityError(panel, (detail && (detail.detail || detail.error)) || "Conversation was not started.");
          start.disabled = false;
        });
    });
    panel.appendChild(form);
    var error = communityElement("p", "g01-community-error");
    error.hidden = true;
    panel.appendChild(error);
    panel.appendChild(communityElement("h3", "g01-community-existing-title", "Existing conversations"));
    panel.appendChild(communityElement("div", "g01-community-list", "Loading conversations…"));
    backdrop.appendChild(panel);
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) closeCommunity();
    });
    document.body.appendChild(backdrop);
    close.focus();

    window.axios
      .get("/api/v1/accounts/" + accountId + "/g01/community", { headers: communityHeaders() })
      .then(function (response) {
        renderCommunityState(panel, response.data);
      })
      .catch(function (requestError) {
        if (requestError && requestError.response && requestError.response.status === 403) {
          closeCommunity();
          var item = document.getElementById("g01-community-item");
          if (item) item.remove();
          return;
        }
        var detail = requestError && requestError.response && requestError.response.data;
        showCommunityError(panel, (detail && (detail.detail || detail.error)) || "Community service is unavailable.");
        panel.querySelector(".g01-community-list").replaceChildren();
      });
  }

  function ensureCommunityButton() {
    var accountId = currentAccountId();
    var existing = document.getElementById("g01-community-open");
    if (!accountId) {
      var staleItem = document.getElementById("g01-community-item");
      if (staleItem) staleItem.remove();
      closeCommunity();
      return;
    }
    if (existing) return;
    var nav = document.querySelector("nav.woot-sidebar-menu, nav.woot-sidebar-main-w-g, nav");
    if (!nav) return;
    var list = nav.querySelector("ul");
    if (!list) return;
    var item = communityElement("li", "g01-community-item");
    item.id = "g01-community-item";
    var button = communityElement("button", "g01-community-open");
    button.id = "g01-community-open";
    button.type = "button";
    button.title = "g01 Community";
    button.appendChild(communityElement("span", "g01-community-glyph", "g01"));
    button.appendChild(communityElement("span", "g01-community-label", "g01 Community"));
    button.addEventListener("click", openCommunity);
    item.appendChild(button);
    list.appendChild(item);
  }

  function watchCommunity() {
    ensureCommunityButton();
    new MutationObserver(function () {
      ensureCommunityButton();
    }).observe(document.body, { childList: true, subtree: true });
    window.addEventListener("popstate", ensureCommunityButton);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeCommunity();
    });
  }

  if (document.body) watchCommunity();
  else document.addEventListener("DOMContentLoaded", watchCommunity);
})();
