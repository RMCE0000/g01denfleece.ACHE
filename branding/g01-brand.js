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
    lead.textContent = "Use a ZIP that is already on the record, such as 70601.";
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

  function renderCommunityMembers(panel, accountId, payload) {
    var list = panel.querySelector(".g01-community-list");
    list.replaceChildren();
    var members = payload && Array.isArray(payload.members) ? payload.members : [];
    if (!members.length) {
      list.appendChild(communityElement("p", "g01-community-empty", "No other homesteaders are available yet."));
      return;
    }
    members.forEach(function (member) {
      var card = communityElement("article", "g01-community-member");
      card.appendChild(communityElement("h3", "", member.name || "Homesteader"));
      card.appendChild(communityElement("p", "g01-community-locality", member.locality || "Locality not recorded"));
      if (member.connected && member.conversation_path) {
        var open = communityElement("a", "g01-community-primary", "Open conversation");
        open.href = member.conversation_path;
        card.appendChild(open);
      } else {
        var topic = communityElement("input", "g01-community-topic");
        topic.type = "text";
        topic.maxLength = 255;
        topic.placeholder = "Optional topic";
        topic.setAttribute("aria-label", "Topic for conversation with " + (member.name || "homesteader"));
        var start = communityElement("button", "g01-community-primary", "Start conversation");
        start.type = "button";
        start.addEventListener("click", function () {
          start.disabled = true;
          panel.querySelector(".g01-community-error").hidden = true;
          window.axios
            .post(
              "/api/v1/accounts/" + accountId + "/g01/community",
              { member_id: member.id, topic: topic.value.trim() || null },
              { headers: communityHeaders() }
            )
            .then(function (response) {
              var data = response && response.data;
              if (!data || !data.conversation_path) throw new Error("Conversation path missing");
              window.location.assign(data.conversation_path);
            })
            .catch(function (error) {
              var detail = error && error.response && error.response.data;
              showCommunityError(panel, (detail && (detail.detail || detail.error)) || "Conversation was not started.");
              start.disabled = false;
            });
        });
        card.appendChild(topic);
        card.appendChild(start);
      }
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
        "Start a private Chatwoot conversation with another homesteader. Jane joins but stays quiet unless named."
      )
    );
    var error = communityElement("p", "g01-community-error");
    error.hidden = true;
    panel.appendChild(error);
    panel.appendChild(communityElement("div", "g01-community-list", "Loading homesteaders…"));
    backdrop.appendChild(panel);
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) closeCommunity();
    });
    document.body.appendChild(backdrop);
    close.focus();

    window.axios
      .get("/api/v1/accounts/" + accountId + "/g01/community", { headers: communityHeaders() })
      .then(function (response) {
        renderCommunityMembers(panel, accountId, response.data);
      })
      .catch(function (requestError) {
        if (requestError && requestError.response && requestError.response.status === 403) {
          closeCommunity();
          var button = document.getElementById("g01-community-open");
          if (button) button.remove();
          return;
        }
        var detail = requestError && requestError.response && requestError.response.data;
        showCommunityError(panel, (detail && (detail.detail || detail.error)) || "Community directory is unavailable.");
        panel.querySelector(".g01-community-list").replaceChildren();
      });
  }

  function ensureCommunityButton() {
    var accountId = currentAccountId();
    var existing = document.getElementById("g01-community-open");
    if (!accountId) {
      if (existing) existing.remove();
      closeCommunity();
      return;
    }
    if (existing) return;
    var nav = document.querySelector("nav.woot-sidebar-menu, nav.woot-sidebar-main-w-g, nav");
    if (!nav) return;
    var button = communityElement("button", "g01-community-open", "g01 Community");
    button.id = "g01-community-open";
    button.type = "button";
    button.addEventListener("click", openCommunity);
    nav.appendChild(button);
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
