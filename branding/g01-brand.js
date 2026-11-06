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

  function enhanceAudioPlayers(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var bubbles = [];
    if (root.matches && root.matches('[data-bubble-name="audio"]')) bubbles.push(root);
    var parentBubble = root.closest && root.closest('[data-bubble-name="audio"]');
    if (parentBubble && bubbles.indexOf(parentBubble) === -1) bubbles.push(parentBubble);
    if (root.querySelectorAll) {
      root.querySelectorAll('[data-bubble-name="audio"]').forEach(function (bubble) {
        bubbles.push(bubble);
      });
    }
    bubbles.forEach(function (bubble) {
      try {
        var message = bubble.closest("[data-message-id]") || bubble.closest(".message-bubble-container");
        if (message) message.classList.add("g01-audio-message");
        var audio = bubble.querySelector("audio");
        if (!audio || audio.classList.contains("g01-native-audio")) return;
        var source = audio.querySelector("source");
        var playbackUrl = "";
        if (source && source.src) {
          var url = new URL(source.src, window.location.origin);
          url.pathname = url.pathname.replace(
            "/rails/active_storage/blobs/redirect/",
            "/rails/active_storage/blobs/proxy/"
          );
          playbackUrl = url.toString();
          source.src = playbackUrl;
        }
        audio.classList.remove("hidden");
        audio.classList.add("g01-native-audio");
        audio.controls = true;
        audio.preload = "metadata";
        if (audio.nextElementSibling) {
          audio.nextElementSibling.classList.add("g01-audio-custom-controls");
        }
        audio.load();
        if (source && playbackUrl) {
          window
            .fetch(playbackUrl, { credentials: "same-origin" })
            .then(function (response) {
              if (!response.ok) throw new Error("Audio download failed");
              return response.blob();
            })
            .then(function (blob) {
              if (!audio.isConnected || !blob.size) return;
              var objectUrl = URL.createObjectURL(blob);
              source.src = objectUrl;
              if (blob.type) source.type = blob.type;
              audio.dataset.g01ObjectUrl = objectUrl;
              audio.load();
            })
            .catch(function () {
              // The proxied source remains available if full download fails.
            });
        }
      } catch (_error) {
        // Leave Chatwoot's player intact if a browser cannot enhance this attachment.
      }
    });
  }

  var activeRecorder = null;
  var recorderStarting = false;

  function recorderStatus(button) {
    var parent = button.parentNode;
    var existing = parent && parent.querySelector(".g01-audio-recorder-status");
    if (existing) return existing;
    var status = document.createElement("span");
    status.className = "g01-audio-recorder-status";
    if (parent) parent.appendChild(status);
    return status;
  }

  function preferredRecordingType() {
    return [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/mp4",
      "audio/webm",
    ].find(function (type) {
      return window.MediaRecorder.isTypeSupported(type);
    });
  }

  function finishRecorder(context, message) {
    window.clearInterval(context.timer);
    context.stream.getTracks().forEach(function (track) {
      track.stop();
    });
    context.button.classList.remove("g01-recording-active");
    context.button.title = "Record audio";
    if (activeRecorder === context) activeRecorder = null;
    context.status.textContent = message || "";
    if (message) {
      window.setTimeout(function () {
        context.status.remove();
      }, 4000);
    } else {
      context.status.remove();
    }
  }

  function uploadRecording(context, blob) {
    var route = conversationContext();
    if (!route || !window.axios || !blob.size) {
      finishRecorder(context, "Audio was not sent. Try again.");
      return;
    }
    var simpleType = (blob.type || "audio/webm").split(";", 1)[0];
    var extensions = {
      "audio/webm": "webm",
      "audio/ogg": "ogg",
      "audio/mp4": "m4a",
    };
    var file = new File([blob], "voice-" + Date.now() + "." + (extensions[simpleType] || "webm"), {
      type: simpleType,
    });
    var form = new FormData();
    form.append("attachments[]", file);
    form.append("private", "false");
    form.append("is_voice_message", "true");
    context.status.textContent = "Sending audio…";
    window.axios
      .post(
        "/api/v1/accounts/" +
          route.accountId +
          "/conversations/" +
          route.conversationId +
          "/messages",
        form
      )
      .then(function () {
        finishRecorder(context, "Audio sent");
      })
      .catch(function () {
        finishRecorder(context, "Audio was not sent. Try again.");
      });
  }

  function startFastRecorder(button) {
    var status = recorderStatus(button);
    recorderStarting = true;
    status.textContent = "Starting microphone…";
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then(function (stream) {
        recorderStarting = false;
        var mimeType = preferredRecordingType();
        var recorder;
        try {
          recorder = mimeType
            ? new MediaRecorder(stream, { mimeType: mimeType, audioBitsPerSecond: 48000 })
            : new MediaRecorder(stream);
        } catch (error) {
          stream.getTracks().forEach(function (track) {
            track.stop();
          });
          throw error;
        }
        var context = {
          button: button,
          chunks: [],
          recorder: recorder,
          startedAt: Date.now(),
          status: status,
          stream: stream,
          timer: null,
          failed: false,
        };
        activeRecorder = context;
        recorder.ondataavailable = function (event) {
          if (event.data && event.data.size) context.chunks.push(event.data);
        };
        recorder.onerror = function () {
          context.failed = true;
          finishRecorder(context, "Recording failed. Try again.");
        };
        recorder.onstop = function () {
          if (context.failed) return;
          window.clearInterval(context.timer);
          context.stream.getTracks().forEach(function (track) {
            track.stop();
          });
          uploadRecording(context, new Blob(context.chunks, { type: recorder.mimeType }));
        };
        recorder.start(1000);
        button.classList.add("g01-recording-active");
        button.title = "Stop and send audio";
        status.textContent = "Recording 0:00 — click again to stop and send";
        context.timer = window.setInterval(function () {
          var seconds = Math.floor((Date.now() - context.startedAt) / 1000);
          status.textContent =
            "Recording " +
            Math.floor(seconds / 60) +
            ":" +
            String(seconds % 60).padStart(2, "0") +
            " — click again to stop and send";
        }, 500);
      })
      .catch(function () {
        recorderStarting = false;
        status.textContent = "Microphone access was denied.";
        window.setTimeout(function () {
          status.remove();
        }, 4000);
      });
  }

  function installFastAudioRecorder() {
    document.addEventListener(
      "click",
      function (event) {
        var button = event.target.closest && event.target.closest("button");
        if (
          !button ||
          !button.querySelector('[class*="i-ph-microphone"]') ||
          !window.MediaRecorder ||
          !navigator.mediaDevices
        ) {
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        if (recorderStarting) return;
        if (activeRecorder) {
          if (activeRecorder.recorder.state === "recording") {
            activeRecorder.status.textContent = "Finishing audio…";
            activeRecorder.recorder.stop();
          }
          return;
        }
        startFastRecorder(button);
      },
      true
    );
  }

  var currentUserId = null;
  var messageSenders = {};
  var activeConversationKey = "";
  var messageClassificationRequest = null;

  function conversationContext() {
    var match = window.location.pathname.match(
      /\/app\/accounts\/(\d+).*\/conversations?\/(\d+)/
    );
    if (!match) return null;
    return {
      accountId: match[1],
      conversationId: match[2],
      key: match[1] + ":" + match[2],
    };
  }

  function visibleMessages() {
    return Array.prototype.slice.call(
      document.querySelectorAll(".message-bubble-container[data-message-id]")
    );
  }

  function applyMessageClasses(messages) {
    if (currentUserId == null) return;
    messages.forEach(function (message) {
      var messageId = Number(message.getAttribute("data-message-id"));
      var senderId = messageSenders[messageId];
      if (senderId == null || senderId === false) return;
      var own = Number(senderId) === Number(currentUserId);
      message.classList.toggle("g01-own-message", own);
      message.classList.toggle("g01-other-message", !own);
    });
  }

  function classifyMessages() {
    var context = conversationContext();
    var messages = visibleMessages();
    if (!context || !messages.length || !window.axios) return;

    if (activeConversationKey !== context.key) {
      activeConversationKey = context.key;
      messageSenders = {};
    }
    applyMessageClasses(messages);

    var missingIds = messages
      .map(function (message) {
        return Number(message.getAttribute("data-message-id"));
      })
      .filter(function (messageId) {
        return Number.isFinite(messageId) && messageSenders[messageId] === undefined;
      });
    if (!missingIds.length || messageClassificationRequest) return;

    var firstId = Math.min.apply(Math, missingIds);
    var lastId = Math.max.apply(Math, missingIds);
    var requestKey = context.key;
    var userRequest = currentUserId
      ? Promise.resolve()
      : window.axios.get("/auth/validate_token").then(function (response) {
          currentUserId = response.data.payload.data.id;
        });
    var messagesUrl =
      "/api/v1/accounts/" +
      context.accountId +
      "/conversations/" +
      context.conversationId +
      "/messages";
    var messagesRequest = window.axios
      .get(messagesUrl, { params: { after: firstId, before: lastId + 1 } })
      .then(function (response) {
        if (activeConversationKey !== requestKey) return;
        (response.data.payload || []).forEach(function (message) {
          var senderId = message.sender_id;
          if (senderId == null && message.sender) senderId = message.sender.id;
          messageSenders[message.id] = senderId == null ? false : senderId;
        });
      });

    messageClassificationRequest = Promise.all([userRequest, messagesRequest])
      .then(function () {
        if (activeConversationKey === requestKey) applyMessageClasses(visibleMessages());
      })
      .catch(function () {
        // Keep Chatwoot's messages usable if either read-only lookup fails.
      })
      .finally(function () {
        messageClassificationRequest = null;
      });
  }

  var messageClassificationQueued = false;
  function scheduleMessageClassification() {
    if (messageClassificationQueued) return;
    messageClassificationQueued = true;
    window.requestAnimationFrame(function () {
      messageClassificationQueued = false;
      classifyMessages(document);
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
    classifyMessages(document);
    enhanceAudioPlayers(document);
    installFastAudioRecorder();
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) {
            brandImages(node);
            scheduleMessageClassification();
            enhanceAudioPlayers(node);
          }
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
    window.setTimeout(function () {
      classifyMessages(document);
    }, 1000);
    window.setTimeout(function () {
      classifyMessages(document);
    }, 3000);
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

  var communityLastOpener = null;

  function closeCommunity() {
    var modal = document.getElementById("g01-community-modal");
    if (modal) modal.remove();
    var opener = communityLastOpener || document.getElementById("g01-community-open");
    if (opener) opener.focus();
    communityLastOpener = null;
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

  function renderCommunityConnections(list, connections, emptyMessage) {
    list.replaceChildren();
    if (!connections.length) {
      list.appendChild(
        communityElement(
          "p",
          "g01-community-empty",
          emptyMessage || "You have no existing homesteader conversations."
        )
      );
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

  function renderCommunityState(panel, payload) {
    var identity = panel.querySelector(".g01-community-identity");
    var self = payload && payload.self;
    identity.textContent = self && self.username ? "Your username: @" + self.username : "";
    var connections = payload && Array.isArray(payload.connections) ? payload.connections : [];
    renderCommunityConnections(panel.querySelector(".g01-community-list"), connections);
  }

  function openCommunity() {
    if (document.getElementById("g01-community-modal")) return;
    var accountId = currentAccountId();
    if (!accountId || !window.axios) return;
    communityLastOpener = document.getElementById("g01-community-open");

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

  function openCommunitySearch(opener) {
    if (document.getElementById("g01-community-modal")) return;
    var accountId = currentAccountId();
    if (!accountId || !window.axios) return;
    communityLastOpener = opener || null;

    var backdrop = communityElement("div", "g01-community-backdrop");
    backdrop.id = "g01-community-modal";
    backdrop.setAttribute("role", "presentation");
    var panel = communityElement("section", "g01-community-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-labelledby", "g01-community-title");
    var header = communityElement("header", "g01-community-header");
    var title = communityElement("h2", "", "Community conversations");
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
        "Search conversations you have already opened through Community."
      )
    );
    var search = communityElement("input", "g01-community-search");
    search.type = "search";
    search.placeholder = "Search by peer name or username";
    search.setAttribute("aria-label", "Search existing Community conversations");
    panel.appendChild(search);
    var error = communityElement("p", "g01-community-error");
    error.hidden = true;
    panel.appendChild(error);
    var list = communityElement("div", "g01-community-list", "Loading conversations…");
    panel.appendChild(list);
    backdrop.appendChild(panel);
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) closeCommunity();
    });
    document.body.appendChild(backdrop);
    search.focus();

    window.axios
      .get("/api/v1/accounts/" + accountId + "/g01/community", { headers: communityHeaders() })
      .then(function (response) {
        var payload = response.data || {};
        var connections = Array.isArray(payload.connections) ? payload.connections : [];
        var filterConnections = function () {
          var query = search.value.trim().toLocaleLowerCase();
          var visible = connections.filter(function (connection) {
            return [connection.name, connection.username, connection.locality, connection.topic]
              .filter(Boolean)
              .some(function (value) {
                return String(value).toLocaleLowerCase().indexOf(query) !== -1;
              });
          });
          renderCommunityConnections(
            list,
            visible,
            query
              ? "No existing Community conversations match that search."
              : "You have no existing homesteader conversations."
          );
        };
        search.addEventListener("input", filterConnections);
        filterConnections();
      })
      .catch(function (requestError) {
        var detail = requestError && requestError.response && requestError.response.data;
        showCommunityError(panel, (detail && (detail.detail || detail.error)) || "Community service is unavailable.");
        list.replaceChildren();
      });
  }

  function ensureCommunitySearch() {
    var searchLinks = document.querySelectorAll('a[href*="/search"]');
    searchLinks.forEach(function (link) {
      if (!link.querySelector(".i-lucide-search") || link.dataset.g01CommunitySearch === "true") return;
      link.dataset.g01CommunitySearch = "true";
      link.title = "Search Community conversations";
      var label = Array.prototype.find.call(link.querySelectorAll("span"), function (span) {
        return !span.className.includes("i-lucide-search") && span.textContent.trim();
      });
      if (label) label.textContent = "Search…";
      link.addEventListener(
        "click",
        function (event) {
          event.preventDefault();
          event.stopImmediatePropagation();
          openCommunitySearch(link);
        },
        true
      );
      var row = link.parentElement;
      var composeIcon = row && row.querySelector(".i-lucide-pen-line");
      var composeButton = composeIcon && composeIcon.closest("button");
      if (composeButton) composeButton.classList.add("g01-hidden-compose");
      if (row) {
        row.querySelectorAll("button").forEach(function (button) {
          if (button === composeButton || button.dataset.g01CommunitySearch === "true") return;
          button.dataset.g01CommunitySearch = "true";
          button.title = "Search Community conversations";
          button.addEventListener(
            "click",
            function (event) {
              event.preventDefault();
              event.stopImmediatePropagation();
              openCommunitySearch(link);
            },
            true
          );
        });
      }
    });
  }

  function ensureCallsHidden() {
    document.querySelectorAll('a[href*="/calls"]').forEach(function (link) {
      var item = link.closest("li");
      (item || link).classList.add("g01-hidden-calls");
    });
  }

  function ensureMentionsHidden() {
    document.querySelectorAll('nav a[href*="/mentions/"]').forEach(function (link) {
      var item = link.closest("li");
      (item || link).classList.add("g01-hidden-mentions");
    });
  }

  function ensureSingleConversationButton() {
    var link = document.querySelector('nav a[data-g01-conversations-button="true"]');
    if (!link) {
      link = Array.prototype.find.call(document.querySelectorAll("nav a"), function (candidate) {
        return Array.prototype.some.call(candidate.querySelectorAll("span, div"), function (element) {
          return !element.children.length && element.textContent.trim() === "All Conversations";
        });
      });
    }
    if (!link) return;

    var label =
      link.querySelector('[data-g01-conversations-label="true"]') ||
      Array.prototype.find.call(link.querySelectorAll("span, div"), function (element) {
        return !element.children.length && element.textContent.trim() === "All Conversations";
      });
    if (label) {
      label.dataset.g01ConversationsLabel = "true";
      if (label.textContent !== "Conversations") label.textContent = "Conversations";
    }
    link.dataset.g01ConversationsButton = "true";
    link.title = "Conversations";

    var primaryItem = link.closest("li");
    var group = primaryItem && primaryItem.parentElement;
    while (group && group !== document.body) {
      if (group.tagName === "LI" && group.classList.contains("group/sidebar-section")) break;
      group = group.parentElement;
    }
    if (!group || group === document.body) return;

    group.classList.add("g01-conversations-single");
    primaryItem.classList.add("g01-conversations-primary");
    group.querySelectorAll("li").forEach(function (item) {
      if (item !== primaryItem && !item.contains(primaryItem)) {
        item.classList.add("g01-hidden-conversation-filter");
      }
    });
  }

  function ensureContactsHidden() {
    document.querySelectorAll("nav .i-lucide-contact").forEach(function (icon) {
      var item = icon.closest("li");
      if (item) item.classList.add("g01-hidden-contacts");
    });
  }

  function ensureBusinessToolsHidden() {
    [
      [".i-lucide-building-2", "g01-hidden-companies"],
      [".i-lucide-bolt", "g01-hidden-settings"],
    ].forEach(function (entry) {
      document.querySelectorAll("nav " + entry[0]).forEach(function (icon) {
        var item = icon.closest("li");
        if (item) item.classList.add(entry[1]);
      });
    });
  }

  function ensureHelpCenterGuide() {
    document.querySelectorAll('nav a[href*="/portals"]').forEach(function (link) {
      var item = link.closest("li") || link;
      if (link.dataset.g01HelpCenterGuide === "true") return;
      var label = Array.prototype.find.call(link.querySelectorAll("span, div"), function (element) {
        return !element.children.length && element.textContent.trim().toLocaleLowerCase() === "articles";
      });
      if (!label) {
        item.classList.add("g01-hidden-help-center-control");
        return;
      }
      link.dataset.g01HelpCenterGuide = "true";
      link.href = "/hc/g01-guide/en";
      link.title = "Open the g01 product guide";
      label.textContent = "Product Guide";
      link.addEventListener(
        "click",
        function (event) {
          event.preventDefault();
          event.stopImmediatePropagation();
          window.location.assign("/hc/g01-guide/en");
        },
        true
      );
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
    button.title = "Community";
    button.appendChild(communityElement("span", "g01-community-glyph", "g01"));
    button.appendChild(communityElement("span", "g01-community-label", "Community"));
    button.addEventListener("click", openCommunity);
    item.appendChild(button);
    list.appendChild(item);
  }

  function watchCommunity() {
    ensureCommunityButton();
    ensureCommunitySearch();
    ensureCallsHidden();
    ensureMentionsHidden();
    ensureSingleConversationButton();
    ensureContactsHidden();
    ensureBusinessToolsHidden();
    ensureHelpCenterGuide();
    new MutationObserver(function () {
      ensureCommunityButton();
      ensureCommunitySearch();
      ensureCallsHidden();
      ensureMentionsHidden();
      ensureSingleConversationButton();
      ensureContactsHidden();
      ensureBusinessToolsHidden();
      ensureHelpCenterGuide();
    }).observe(document.body, { childList: true, subtree: true });
    window.addEventListener("popstate", ensureCommunityButton);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeCommunity();
      if (
        event.key.toLocaleLowerCase() === "k" &&
        (event.metaKey || event.ctrlKey) &&
        currentAccountId()
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        openCommunitySearch(document.querySelector('[data-g01-community-search="true"]'));
      }
    }, true);
  }

  if (document.body) watchCommunity();
  else document.addEventListener("DOMContentLoaded", watchCommunity);
})();
