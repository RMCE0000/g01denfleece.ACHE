(function () {
  var LOGO = "/g01-logo.png";
  var MARK = "/g01-favicon.png?v=59";
  var TAB_TITLE = "g01denfleece";

  function savedColorScheme() {
    try {
      return localStorage.getItem("color_scheme");
    } catch (error) {
      return null;
    }
  }

  function systemIsDark() {
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function applyColorScheme() {
    var selected = savedColorScheme();
    var dark = selected === "dark" || ((selected === "auto" || !selected) && systemIsDark());
    if (onLoginPage()) dark = false;
    var root = document.documentElement;
    var scheme = dark ? "dark" : "light";
    if (root.classList.contains("dark") !== dark) root.classList.toggle("dark", dark);
    if (document.body && document.body.classList.contains("dark") !== dark) {
      document.body.classList.toggle("dark", dark);
    }
    if (root.style.colorScheme !== scheme) root.style.colorScheme = scheme;
  }

  var g01Silent = null;
  var allowDashboardSoundUntil = 0;
  var nativeAudioPlay = window.Audio && Audio.prototype.play;
  if (nativeAudioPlay) {
    Audio.prototype.play = function () {
      var src = "";
      try {
        src = this.currentSrc || this.src || "";
      } catch (error) {}
      if (
        dashboardSoundIsSilent() &&
        Date.now() > allowDashboardSoundUntil &&
        /\/audio\/dashboard\//.test(src)
      ) {
        return Promise.resolve();
      }
      return nativeAudioPlay.apply(this, arguments);
    };
  }
  document.addEventListener(
    "click",
    function (event) {
      var element = event.target && event.target.nodeType === 1 ? event.target : event.target && event.target.parentElement;
      var button = element && element.closest && element.closest("button");
      if (!button || !button.querySelector(".i-lucide-volume-2")) return;
      allowDashboardSoundUntil = Date.now() + 1500;
    },
    true
  );

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
    pinTabIcons();
  }

  function tabIcon(link) {
    if (!link || !link.tagName || link.tagName !== "LINK") return false;
    var rel = (link.getAttribute("rel") || "").toLowerCase();
    return link.classList.contains("favicon") || rel.indexOf("icon") !== -1;
  }

  // The signed-in page rewrites .favicon to /favicon-*.png when the tab is shown again
  // and to /favicon-badge-*.png when a notification arrives.
  function pinTabIcon(link) {
    if (!tabIcon(link)) return;
    if ((link.getAttribute("href") || "").indexOf("g01-favicon.png") === -1) {
      link.href = MARK;
      link.type = "image/png";
    }
    if (link.classList.contains("favicon")) link.classList.remove("favicon");
  }

  function pinTabIcons() {
    document.querySelectorAll("link").forEach(pinTabIcon);
  }

  function pinTabTitle() {
    var title = document.title || "";
    var next = title.replace(/chatwoot/gi, TAB_TITLE);
    if (!next || next === "g01" || next === "Sign in · g01") next = TAB_TITLE;
    if (next !== document.title) document.title = next;
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
        // Leave g01's player intact if a browser cannot enhance this attachment.
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
        // Keep g01's messages usable if either read-only lookup fails.
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

  function watchColorScheme() {
    applyColorScheme();
    if (!document.body || document.body.dataset.g01ColorSchemeWatch === "true") return;
    document.body.dataset.g01ColorSchemeWatch = "true";
    new MutationObserver(applyColorScheme).observe(document.body, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }

  watchColorScheme();
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyColorScheme);
  }
  window.addEventListener("storage", function (event) {
    if (!event.key || event.key === "color_scheme") applyColorScheme();
  });
  if (!document.body) document.addEventListener("DOMContentLoaded", watchColorScheme);

  function composerElement(node) {
    if (!node) return null;
    return node.nodeType === 1 ? node : node.parentElement;
  }

  function insideComposer(node) {
    var element = composerElement(node);
    return !!(element && element.closest && element.closest(".ProseMirror, .reply-box"));
  }

  // Typing rewrites the editor on every character. A detached node was removed
  // from an editor parent, so it still belongs to that keystroke.
  function composerOnly(records) {
    if (!records || !records.length) return false;
    return records.every(function (record) {
      if (!insideComposer(record.target)) return false;
      var outside = false;
      function visit(node) {
        if (outside || insideComposer(node)) return;
        var element = composerElement(node);
        if (element && element.isConnected) outside = true;
      }
      record.addedNodes.forEach(visit);
      if (record.removedNodes) record.removedNodes.forEach(visit);
      return !outside;
    });
  }

  function rewriteThinking(pill) {
    pill.childNodes.forEach(function (node) {
      if (node.nodeType !== 3 || !node.nodeValue) return;
      var next = node.nodeValue.replace(/\bis typing\b/gi, "is thinking").replace(/\bare typing\b/gi, "are thinking");
      if (next !== node.nodeValue) node.nodeValue = next;
    });
  }

  function shapeThinking(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var images = [];
    if (root.matches && root.matches('img[alt="Someone is typing"], img[src*="typing.gif"]')) images.push(root);
    if (root.querySelectorAll) {
      root.querySelectorAll('img[alt="Someone is typing"], img[src*="typing.gif"]').forEach(function (img) {
        images.push(img);
      });
    }
    images.forEach(function (img) {
      var pill = img.parentElement;
      var row = pill && pill.parentElement;
      if (!pill || !row) return;
      row.classList.add("g01-thinking-row");
      pill.classList.add("g01-thinking");
      rewriteThinking(pill);
      if (pill.querySelector(".g01-thinking-dots")) return;
      var dots = document.createElement("span");
      dots.className = "g01-thinking-dots";
      dots.setAttribute("aria-hidden", "true");
      dots.appendChild(document.createElement("i"));
      dots.appendChild(document.createElement("i"));
      dots.appendChild(document.createElement("i"));
      pill.appendChild(dots);
      if (pill.dataset.g01Thinking === "1") return;
      pill.dataset.g01Thinking = "1";
      new MutationObserver(function () {
        rewriteThinking(pill);
      }).observe(pill, { characterData: true, subtree: true, childList: true });
    });
  }

  var thinkingWait = null;
  var thinkingTimer = 0;
  var thinkingEchoTimer = 0;

  function composerText(box) {
    var editor = box && box.querySelector ? box.querySelector(".ProseMirror") : null;
    return editor ? editor.innerText || "" : "";
  }

  function janeWillAnswer(text) {
    var titles = document.querySelectorAll(".conversation--header--actions [title]");
    var sawInbox = false;
    for (var i = 0; i < titles.length; i += 1) {
      var name = titles[i].getAttribute("title") || "";
      if (!name || name.charAt(0) === "#") continue;
      sawInbox = true;
      if (/^jane\b/i.test(name)) return true;
    }
    if (/\bjane\b/i.test(text || "")) return true;
    return !sawInbox;
  }

  function hideThinking() {
    thinkingWait = null;
    window.clearTimeout(thinkingTimer);
    window.clearTimeout(thinkingEchoTimer);
    document.querySelectorAll(".g01-thinking-row").forEach(function (row) {
      row.remove();
    });
  }

  function placeThinking() {
    var row = document.querySelector(".g01-thinking-live");
    var box = document.querySelector(".reply-box");
    if (!row || !box) return;
    var rect = box.getBoundingClientRect();
    if (rect.width < 8 || rect.bottom < 0) {
      row.style.visibility = "hidden";
      return;
    }
    row.style.visibility = "visible";
    row.style.left = Math.max(8, rect.left) + "px";
    row.style.width = Math.max(0, rect.width) + "px";
    row.style.bottom = Math.max(8, window.innerHeight - rect.top + 6) + "px";
  }

  function mountThinking() {
    var row = document.querySelector(".g01-thinking-live");
    if (!row) {
      row = document.createElement("div");
      row.className = "g01-thinking-row g01-thinking-live";
      row.setAttribute("role", "status");
      var pill = document.createElement("div");
      pill.className = "g01-thinking";
      pill.appendChild(document.createTextNode("Jane is thinking"));
      var dots = document.createElement("span");
      dots.className = "g01-thinking-dots";
      dots.setAttribute("aria-hidden", "true");
      dots.appendChild(document.createElement("i"));
      dots.appendChild(document.createElement("i"));
      dots.appendChild(document.createElement("i"));
      pill.appendChild(dots);
      row.appendChild(pill);
      document.body.appendChild(row);
    }
    placeThinking();
  }

  function syncThinking() {
    if (!thinkingWait) return;
    mountThinking();
    var bubbles = document.querySelectorAll(".message-bubble-container");
    if (bubbles.length <= thinkingWait.baseline) return;
    var last = bubbles[bubbles.length - 1];
    var lastText = (last.innerText || "").replace(/\s+/g, " ").trim();
    var sent = (thinkingWait.sent || "").replace(/\s+/g, " ").trim();
    if (!sent) {
      if (bubbles.length >= thinkingWait.baseline + 2) hideThinking();
      return;
    }
    var snippet = sent.slice(0, 80);
    if (snippet && lastText.indexOf(snippet) !== -1 && bubbles.length < thinkingWait.baseline + 2) return;
    hideThinking();
  }

  function showThinking(sent) {
    thinkingWait = {
      baseline: document.querySelectorAll(".message-bubble-container").length,
      sent: sent || ""
    };
    window.clearTimeout(thinkingTimer);
    window.clearTimeout(thinkingEchoTimer);
    thinkingTimer = window.setTimeout(hideThinking, 45000);
    thinkingEchoTimer = window.setTimeout(function () {
      if (!thinkingWait) return;
      if (document.querySelectorAll(".message-bubble-container").length <= thinkingWait.baseline) hideThinking();
    }, 1500);
    mountThinking();
  }

  function maybeShowThinking(box) {
    if (!box || box.classList.contains("is-private")) return;
    var text = composerText(box);
    if (!text.trim() && !box.querySelector(".attachment, .file-uploads, [data-file]")) return;
    if (!janeWillAnswer(text)) return;
    showThinking(text);
  }

  function installThinking() {
    document.addEventListener(
      "click",
      function (event) {
        var target = event.target && event.target.nodeType === 1 ? event.target : event.target && event.target.parentElement;
        var button = target && target.closest ? target.closest(".reply-box button[type='submit']") : null;
        if (!button || button.disabled) return;
        maybeShowThinking(button.closest(".reply-box"));
      },
      true
    );
    document.addEventListener(
      "keydown",
      function (event) {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        var target = event.target && event.target.nodeType === 1 ? event.target : event.target && event.target.parentElement;
        var editor = target && target.closest ? target.closest(".reply-box .ProseMirror") : null;
        if (!editor) return;
        maybeShowThinking(editor.closest(".reply-box"));
      },
      true
    );
    window.addEventListener("resize", placeThinking);
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", placeThinking);
      window.visualViewport.addEventListener("scroll", placeThinking);
    }
    document.addEventListener(
      "scroll",
      function () {
        if (thinkingWait) placeThinking();
      },
      true
    );
  }

  function watch() {
    pinTabIcons();
    pinTabTitle();
    shapeThinking(document);
    installThinking();
    brandImages(document);
    classifyMessages(document);
    enhanceAudioPlayers(document);
    installFastAudioRecorder();
    new MutationObserver(function (records) {
      if (composerOnly(records)) return;
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) {
            brandImages(node);
            shapeThinking(node);
            scheduleMessageClassification();
            enhanceAudioPlayers(node);
          }
        });
      });
      syncThinking();
    }).observe(document.body, { childList: true, subtree: true });
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        if (record.type === "attributes") pinTabIcon(record.target);
        if (!record.addedNodes) return;
        record.addedNodes.forEach(function (node) {
          if (!node || node.nodeType !== 1) return;
          pinTabIcon(node);
          if (node.querySelectorAll) node.querySelectorAll("link").forEach(pinTabIcon);
        });
      });
    }).observe(document.head, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["href", "rel", "class"]
    });
    var titleNode = document.querySelector("title");
    if (titleNode) {
      new MutationObserver(pinTabTitle).observe(titleNode, { childList: true, characterData: true, subtree: true });
    }
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
    pinTabTitle();
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
    function signupDetail(body) {
      var detail = body && body.detail;
      if (typeof detail === "string" && detail.trim()) return detail.trim();
      if (Array.isArray(detail)) {
        var message = detail.map(function (item) {
          if (typeof item === "string") return item;
          return item && typeof item.msg === "string" ? item.msg : "";
        }).filter(Boolean)[0];
        if (message) return message;
      }
      return "Account was not created.";
    }
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
      if (payload.password.length > 72 || new TextEncoder().encode(payload.password).length > 72) {
        error.textContent = "Password must be 72 characters or fewer.";
        error.hidden = false;
        submit.disabled = false;
        return;
      }
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
          return response.text().then(function (text) {
            var body = null;
            try {
              body = text ? JSON.parse(text) : null;
            } catch (parseError) {
              body = { detail: text || "Account was not created." };
            }
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
          error.textContent = signupDetail(result.body);
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
    closeReading();
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

  function hideSidebarEntries(labels, className) {
    document.querySelectorAll("nav span, nav div").forEach(function (element) {
      if (element.children.length || labels.indexOf(element.textContent.trim()) === -1) return;
      var item = element.closest("li");
      if (item) item.classList.add(className);
    });
  }

  function assigneeTabLabel(link) {
    var label = "";
    link.childNodes.forEach(function (node) {
      if (node.nodeType === 3) label += node.textContent;
    });
    return label.trim();
  }

  var allConversationTabs = null;
  var allConversationChosen = false;

  function ensureAllConversations() {
    var tabs = document.querySelector(".conversations-list-wrap > .h-10.w-full.px-3.-mt-1");
    if (!tabs) {
      allConversationTabs = null;
      allConversationChosen = false;
      return;
    }
    if (tabs !== allConversationTabs) {
      allConversationTabs = tabs;
      allConversationChosen = false;
    }
    var all = null;
    tabs.querySelectorAll("a").forEach(function (link) {
      if (assigneeTabLabel(link) === "All") all = link;
    });
    if (!all) return;
    if (all.classList.contains("text-n-blue-11")) {
      allConversationChosen = true;
      return;
    }
    if (allConversationChosen) return;
    allConversationChosen = true;
    all.click();
  }

  var HIDDEN_CONTACT_SECTIONS = { "conversation actions": true, macros: true };

  function contactListItem(heading) {
    var node = heading;
    while (node && node.parentElement) {
      var parent = node.parentElement;
      if (
        parent.classList &&
        (parent.classList.contains("flex-col") || parent.classList.contains("list-group"))
      ) {
        return node;
      }
      node = parent;
    }
    var button = heading.closest && heading.closest("button");
    return (button && button.parentElement) || heading;
  }

  function ensureContactSectionsHidden() {
    document.querySelectorAll(".list-group h5").forEach(function (heading) {
      var text = heading.textContent.replace(/\s+/g, " ").trim().toLowerCase();
      if (!HIDDEN_CONTACT_SECTIONS[text]) return;
      var block = contactListItem(heading);
      if (!block || block === heading) {
        var button = heading.closest && heading.closest("button");
        block = (button && button.parentElement) || block;
      }
      if (!block) return;
      block.classList.add("g01-hidden-contact-section");
      block.style.setProperty("display", "none", "important");
    });
  }

  function ensureConversationToolsHidden() {
    hideSidebarEntries(
      ["Mentions", "Participating", "Unattended", "Folders", "Teams", "Channels", "Labels"],
      "g01-hidden-conversation-tool"
    );
  }

  function ensureConversationGroupFlat() {
    document.querySelectorAll("nav a[title]").forEach(function (header) {
      var title = (header.getAttribute("title") || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (title !== "conversations") return;
      var named = false;
      header.querySelectorAll("span").forEach(function (span) {
        if (span.children.length) return;
        if (span.textContent.replace(/\s+/g, " ").trim().toLowerCase() === "conversations") named = true;
      });
      if (!named) return;
      var group = header.closest("li");
      if (!group) return;
      var list = group.querySelector(":scope > ul");
      if (!list) return;
      if (list.textContent.replace(/\s+/g, " ").toLowerCase().indexOf("all conversations") === -1) return;
      list.classList.add("g01-hidden-conversation-children");
      header.querySelectorAll(".i-lucide-chevron-up, .i-lucide-chevron-down").forEach(function (chevron) {
        chevron.classList.add("g01-hidden-conversation-children");
      });
    });
  }

  function collapsedConversationTrigger(node) {
    if (!node || !node.closest || !node.closest("nav")) return null;
    var link = node.closest("a[title], button[title]");
    if (!link || !link.closest("nav")) {
      link = node.querySelector ? node.querySelector(":scope > a[title], :scope > button[title]") : null;
    }
    if (!link || !link.closest("nav")) return null;
    var title = (link.getAttribute("title") || "").replace(/\s+/g, " ").trim().toLowerCase();
    if (title !== "conversations") return null;
    var label = (link.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    if (label === "conversations") return null;
    return link;
  }

  function isCollapsedConversationFlyout(panel) {
    if (!panel || !panel.closest || panel.closest("nav, aside")) return false;
    var header = null;
    panel.querySelectorAll("div").forEach(function (item) {
      if (header || item.children.length) return;
      if (item.textContent.replace(/\s+/g, " ").trim().toLowerCase() === "conversations") header = item;
    });
    if (!header || !panel.querySelector("ul")) return false;
    return panel.textContent.replace(/\s+/g, " ").toLowerCase().indexOf("all conversations") !== -1;
  }

  function ensureCollapsedConversationMenuHidden() {
    document.querySelectorAll("div.fixed").forEach(function (panel) {
      if (!isCollapsedConversationFlyout(panel)) return;
      panel.classList.add("g01-hidden-conversation-flyout");
      panel.setAttribute("hidden", "");
      panel.style.setProperty("display", "none", "important");
      panel.style.setProperty("visibility", "hidden", "important");
      panel.style.setProperty("pointer-events", "none", "important");
    });
  }

  var collapsedConversationMenuGuardInstalled = false;

  function installCollapsedConversationMenuGuard() {
    ensureCollapsedConversationMenuHidden();
    if (collapsedConversationMenuGuardInstalled) return;
    collapsedConversationMenuGuardInstalled = true;
    document.addEventListener(
      "mouseenter",
      function (event) {
        if (!collapsedConversationTrigger(event.target)) return;
        event.stopPropagation();
      },
      true
    );
  }

  function ensureCaptainHidden() {
    document.querySelectorAll("nav .i-woot-captain").forEach(function (icon) {
      var item = icon.closest("li");
      if (item) item.classList.add("g01-hidden-captain");
    });
    hideSidebarEntries(["Captain", "Captain AI"], "g01-hidden-captain");
  }

  function ensureContactsHidden() {
    document.querySelectorAll("nav .i-lucide-contact").forEach(function (icon) {
      var item = icon.closest("li");
      if (item) item.classList.add("g01-hidden-contacts");
    });
  }

  var profileDocsGuardInstalled = false;

  function profileDocsItem(node) {
    var element = eventElement(node);
    var item = element && element.closest ? element.closest(".n-dropdown-item") : null;
    if (!item) return null;
    if (
      item.querySelector(".i-lucide-book") ||
      item.querySelector('a[href*="chatwoot.com/hc"]') ||
      item.querySelector(".i-lucide-scroll-text") ||
      item.querySelector('a[href*="chatwoot.com/changelog"]')
    ) {
      return item;
    }
    return null;
  }

  function ensureProfileDocsHidden() {
    document.querySelectorAll(".n-dropdown-item").forEach(function (item) {
      if (profileDocsItem(item)) item.classList.add("g01-hidden-profile-docs");
    });
    if (profileDocsGuardInstalled) return;
    profileDocsGuardInstalled = true;
    document.addEventListener(
      "click",
      function (event) {
        if (!profileDocsItem(event.target)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
      },
      true
    );
  }

  function eventInput(name) {
    var node = document.getElementById("checkbox-" + name);
    if (!node) return null;
    if (node.tagName === "INPUT") return node;
    return node.querySelector("input");
  }

  function eventInputs() {
    return ["assigned", "unassigned", "notme"].map(eventInput).filter(Boolean);
  }

  function dashboardSoundIsSilent() {
    if (g01Silent !== null) return g01Silent === true;
    var boxes = eventInputs();
    if (boxes.length) return boxes.every(function (input) { return !input.checked; });
    return false;
  }

  function sectionHeading(section) {
    var heading = section && section.querySelector("h4");
    return heading ? heading.textContent.replace(/\s+/g, " ").trim().toLowerCase() : "";
  }

  function sectionByHeading(label) {
    var sections = document.querySelectorAll("section");
    for (var i = 0; i < sections.length; i++) {
      if (sectionHeading(sections[i]) === label) return sections[i];
    }
    return null;
  }

  function audioState(instance) {
    if (!instance) return null;
    var sources = [instance.setupState, instance.exposed, instance.ctx, instance.devtoolsRawSetupState];
    for (var i = 0; i < sources.length; i++) {
      var state = sources[i];
      if (!state) continue;
      if (typeof state.handleAudioConfigChange === "function" || typeof state.handAudioAlertChange === "function") {
        return state;
      }
    }
    return null;
  }

  function audioNotificationSetup() {
    var root = document.querySelector("#app");
    var app = root && root.__vue_app__;
    var found = null;
    var seen = [];
    function visitInstance(instance) {
      if (!instance || found || seen.indexOf(instance) !== -1) return;
      seen.push(instance);
      found = audioState(instance);
      if (found) return;
      visit(instance.subTree);
    }
    function visit(vnode) {
      if (!vnode || found || seen.indexOf(vnode) !== -1) return;
      seen.push(vnode);
      if (vnode.component) visitInstance(vnode.component);
      var children = vnode.children;
      if (Array.isArray(children)) children.forEach(visit);
      else if (children && typeof children === "object") visit(children);
      if (Array.isArray(vnode.dynamicChildren)) vnode.dynamicChildren.forEach(visit);
      if (vnode.suspense && vnode.suspense.activeBranch) visit(vnode.suspense.activeBranch);
    }
    if (app) visitInstance(app._instance);
    return found;
  }

  function hideNotificationBanners() {
    document.querySelectorAll("[popover]").forEach(function (popover) {
      if (!/notification preferences are updated/i.test(popover.textContent || "")) return;
      if (popover.hidePopover) popover.hidePopover();
      popover.style.setProperty("display", "none", "important");
    });
  }

  function withoutNotificationBanners(work) {
    var observer = document.body
      ? new MutationObserver(hideNotificationBanners)
      : null;
    if (observer) observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    try {
      work();
    } finally {
      window.setTimeout(hideNotificationBanners, 0);
      window.setTimeout(function () {
        hideNotificationBanners();
        if (observer) observer.disconnect();
      }, 800);
    }
  }

  function saveSilentRequest(silent) {
    var headers = authHeaders();
    fetch("/api/v1/profile", { headers: headers, credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (profile) {
        if (!profile) return null;
        var settings = Object.assign({}, profile.ui_settings || (profile.data && profile.data.ui_settings) || {});
        settings.enable_audio_alerts = silent ? "none" : "all";
        settings.always_play_audio_alert = !silent;
        return fetch("/api/v1/profile", {
          method: "PUT",
          credentials: "same-origin",
          headers: headers,
          body: JSON.stringify({ profile: { ui_settings: settings } }),
        });
      })
      .catch(function () {});
  }

  function saveSilent(silent) {
    var setup = audioNotificationSetup();
    withoutNotificationBanners(function () {
      if (setup && setup.handleAudioConfigChange) {
        setup.handleAudioConfigChange({
          enable_audio_alerts: silent ? "none" : "all",
          always_play_audio_alert: !silent,
        });
        return;
      }
      if (setup && setup.handAudioAlertChange) {
        setup.handAudioAlertChange(silent ? "none" : "all");
        if (!silent && setup.handleAudioAlertConditions) setup.handleAudioAlertConditions("tab_is_inactive", false);
        return;
      }
      saveSilentRequest(silent);
    });
  }

  var silentProfileRequested = false;
  var silentChosen = false;

  function authHeaders() {
    var headers = { Accept: "application/json", "Content-Type": "application/json" };
    var parts = document.cookie ? document.cookie.split("; ") : [];
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].indexOf("cw_d_session_info=") !== 0) continue;
      var value = parts[i].slice("cw_d_session_info=".length);
      var data = null;
      try {
        data = JSON.parse(decodeURIComponent(value));
      } catch (error) {
        try {
          data = JSON.parse(value);
        } catch (parseError) {}
      }
      if (!data) break;
      ["access-token", "token-type", "client", "expiry", "uid"].forEach(function (key) {
        if (data[key]) headers[key] = data[key];
      });
      break;
    }
    var csrf = document.querySelector('meta[name="csrf-token"]');
    if (csrf && csrf.content) headers["X-CSRF-Token"] = csrf.content;
    return headers;
  }

  function loadSilentPreference() {
    if (silentProfileRequested || onLoginPage()) return;
    silentProfileRequested = true;
    fetch("/api/v1/profile", { headers: authHeaders(), credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (profile) {
        var settings = profile && (profile.ui_settings || (profile.data && profile.data.ui_settings));
        if (!settings || silentChosen) return;
        var alerts = settings.enable_audio_alerts;
        g01Silent = !alerts || alerts === "none";
        var toggle = document.getElementById("g01-silent-input");
        if (toggle) toggle.checked = g01Silent;
      })
      .catch(function () {});
  }

  function ensureSilentToggle() {
    var section = document.querySelector("[data-g01-notifications='true']") || sectionByHeading("audio alerts");
    var preferences = sectionByHeading("notification preferences");
    if (preferences) preferences.classList.add("g01-hidden-notification-preferences");
    if (!section) return;
    section.dataset.g01Notifications = "true";
    var heading = section.querySelector("h4");
    if (heading && heading.textContent.trim() !== "Notifications") heading.textContent = "Notifications";
    var note = section.querySelector("header p");
    if (note) note.textContent = "Choose a notification sound, or turn Silent on to mute it.";
    var form = section.querySelector("#profile-settings-notifications");
    if (form) {
      Array.prototype.forEach.call(form.children, function (child) {
        if (child.querySelector(".i-lucide-volume-2")) return;
        child.classList.add("g01-hidden-notification-form");
      });
    }
    var row = section.querySelector("#g01-silent-row");
    if (!row) {
      row = document.createElement("label");
      row.id = "g01-silent-row";
      row.className = "g01-silent-row";
      var copy = document.createElement("span");
      var title = document.createElement("strong");
      title.textContent = "Silent";
      var detail = document.createElement("span");
      detail.textContent = "Mute sounds for new messages.";
      copy.appendChild(title);
      copy.appendChild(detail);
      var control = document.createElement("span");
      control.className = "g01-silent-switch";
      var input = document.createElement("input");
      input.id = "g01-silent-input";
      input.type = "checkbox";
      if (g01Silent !== null) input.checked = g01Silent;
      input.addEventListener("change", function () {
        silentChosen = true;
        g01Silent = input.checked;
        saveSilent(g01Silent);
      });
      control.appendChild(input);
      control.appendChild(document.createElement("i"));
      row.appendChild(copy);
      row.appendChild(control);
      if (form && form.parentElement) form.parentElement.insertBefore(row, form);
      else section.appendChild(row);
    }
    if (!silentChosen && g01Silent === null) {
      var boxes = eventInputs();
      if (boxes.length) g01Silent = boxes.every(function (box) { return !box.checked; });
    }
    var toggle = document.getElementById("g01-silent-input");
    if (toggle && g01Silent !== null) toggle.checked = g01Silent;
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

  var HIDDEN_MESSAGE_MENU_LABELS = { translate: true, "add to canned responses": true };
  var MESSAGE_MENU_ICON_PATHS = ["M16.953 5.303", "M12.022 3a6.473"];
  var messageMenuGuardInstalled = false;

  function menuLabelText(node) {
    return (node && node.textContent ? node.textContent : "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
  }

  function ensureMessageMenuStyle() {
    if (document.getElementById("g01-message-menu-style")) return;
    var style = document.createElement("style");
    style.id = "g01-message-menu-style";
    style.textContent = [
      ".menu-container .menu:has(path[d^=\"M16.953 5.303\"]),",
      ".menu-container .menu:has(path[d^=\"M12.022 3a6.473\"]),",
      ".g01-hidden-message-menu-item {",
      "  display: none !important;",
      "  pointer-events: none !important;",
      "}",
    ].join("\n");
    (document.head || document.documentElement).appendChild(style);
  }

  function rowBlocksMessageMenu(row) {
    if (!row || !row.closest || !row.closest(".menu-container")) return false;
    var label = row.querySelector(".menu-label, p, span");
    if (HIDDEN_MESSAGE_MENU_LABELS[menuLabelText(label || row)]) return true;
    return MESSAGE_MENU_ICON_PATHS.some(function (prefix) {
      return !!row.querySelector('path[d^="' + prefix + '"]');
    });
  }

  function hideMessageMenuRow(row) {
    row.classList.add("g01-hidden-message-menu-item");
    row.style.setProperty("display", "none", "important");
    row.style.setProperty("pointer-events", "none", "important");
  }

  function ensureMessageMenuTrimmed() {
    ensureMessageMenuStyle();
    document.querySelectorAll(".menu-container .menu, .menu-container [role='button']").forEach(function (row) {
      if (rowBlocksMessageMenu(row)) hideMessageMenuRow(row);
    });
  }

  function installMessageMenuGuard() {
    ensureMessageMenuTrimmed();
    if (messageMenuGuardInstalled) return;
    messageMenuGuardInstalled = true;
    document.addEventListener(
      "contextmenu",
      function () {
        ensureMessageMenuTrimmed();
        requestAnimationFrame(ensureMessageMenuTrimmed);
        setTimeout(ensureMessageMenuTrimmed, 0);
        setTimeout(ensureMessageMenuTrimmed, 50);
      },
      true
    );
    document.addEventListener(
      "click",
      function (event) {
        var source = event.target && event.target.closest ? event.target : event.target && event.target.parentElement;
        var row = source && source.closest && source.closest(".menu-container .menu, .menu-container [role='button']");
        if (!row || !rowBlocksMessageMenu(row)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
      },
      true
    );
    new MutationObserver(function (records) {
      if (composerOnly(records)) return;
      try {
        ensureMessageMenuTrimmed();
      } catch (error) {}
    }).observe(document.documentElement, { childList: true, subtree: true });
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

  var READING_PAGES = [
    {
      id: "tenets",
      label: "Core Tenets",
      glyph: "1",
      paragraphs: [
        "Every homestead ought be,"
      ],
      ordered: true,
      lines: [
        "Clean - The central difference between a company and homesteader, a homestead ought not be required to take up sales, marketing, or branding of any kind.",
        "Automated - Homesteader/s ought not need to work in order to maintain the property and its productive capability.",
        "Aesthetic - The property ought be beautiful, according to the homesteader/s taste.",
        "Material - Homesteader/s ought be able to live and profit off of the fruits produced by the property, alone, indefinitely.",
        "Energetic - The property ought produce and profit off of its own energy, indefinitely.",
        "Contained - The property ought leak no harmful waste.",
        "Utilized - The property ought be recorded along the cutting edge of financial tools, to the greatest good of its homesteader/s.",
        "Defensible - The property ought be able to defend against invasion and disaster.",
        "Insured - The guiding principle of homesteading itself, homesteaders and all assets ought be insured.",
        "Integrated - A homestead ought contribute to its city's sovereignty, where its home city may sustain itself, if necessary, indefinitely."
      ]
    },
    {
      id: "scorecard",
      label: "Score Card",
      glyph: "0",
      paragraphs: [
        "Each product is taken as the total process required to produce the consumable item that triggers any given score. Components that are grown, are taken to be unitary. \"Local\" is defined as a city and its suburbs. Any given place, not within a city's limits, is a suburb of its closest city.",
        "A component of the product is produced by a..."
      ],
      lines: [
        "local homestead + 0",
        "local company + 1",
        "homestead within the state + 2",
        "company within the state + 3",
        "homestead within the country + 4",
        "company within the country + 5",
        "homestead abroad + 6",
        "company abroad + 7"
      ],
      closing: [
        "The sum of all components of a product is the product's score. 0 is the target."
      ]
    }
  ];

  var readingLastOpener = null;

  function closeReading() {
    var modal = document.getElementById("g01-reading-modal");
    if (modal) modal.remove();
    var opener = readingLastOpener;
    readingLastOpener = null;
    if (opener) opener.focus();
  }

  function openReading(page) {
    closeReading();
    closeCommunity();
    readingLastOpener = document.getElementById("g01-reading-" + page.id);
    var backdrop = communityElement("div", "g01-community-backdrop");
    backdrop.id = "g01-reading-modal";
    backdrop.setAttribute("role", "presentation");
    var panel = communityElement("section", "g01-community-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-labelledby", "g01-reading-title");
    var header = communityElement("header", "g01-community-header");
    var title = communityElement("h2", "", page.label);
    title.id = "g01-reading-title";
    var close = communityElement("button", "g01-community-close", "Close");
    close.type = "button";
    close.addEventListener("click", closeReading);
    header.appendChild(title);
    header.appendChild(close);
    panel.appendChild(header);
    page.paragraphs.forEach(function (paragraph) {
      panel.appendChild(communityElement("p", "g01-community-intro", paragraph));
    });
    if (page.lines && page.lines.length) {
      var list = communityElement(page.ordered ? "ol" : "ul", "g01-community-intro");
      page.lines.forEach(function (line) {
        list.appendChild(communityElement("li", "", line));
      });
      panel.appendChild(list);
    }
    (page.closing || []).forEach(function (paragraph) {
      panel.appendChild(communityElement("p", "g01-community-intro", paragraph));
    });
    backdrop.appendChild(panel);
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) closeReading();
    });
    document.body.appendChild(backdrop);
    close.focus();
  }

  function ensureReadingPages() {
    var accountId = currentAccountId();
    READING_PAGES.forEach(function (page) {
      var existing = document.getElementById("g01-reading-" + page.id);
      if (!accountId) {
        var stale = document.getElementById("g01-reading-item-" + page.id);
        if (stale) stale.remove();
        return;
      }
      if (existing) return;
      var nav = document.querySelector("nav.woot-sidebar-menu, nav.woot-sidebar-main-w-g, nav");
      if (!nav) return;
      var list = nav.querySelector("ul");
      if (!list) return;
      var item = communityElement("li", "g01-community-item");
      item.id = "g01-reading-item-" + page.id;
      var button = communityElement("button", "g01-community-open");
      button.id = "g01-reading-" + page.id;
      button.type = "button";
      button.title = page.label;
      button.appendChild(communityElement("span", "g01-community-glyph", page.glyph));
      button.appendChild(communityElement("span", "g01-community-label", page.label));
      button.addEventListener("click", function () {
        openReading(page);
      });
      item.appendChild(button);
      list.appendChild(item);
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
    ensureReadingPages();
    ensureCommunitySearch();
    ensureCallsHidden();
    ensureAllConversations();
    ensureConversationToolsHidden();
    ensureConversationGroupFlat();
    ensureCaptainHidden();
    ensureContactsHidden();
    ensureBusinessToolsHidden();
    ensureProfileDocsHidden();
    ensureSilentToggle();
    ensureHelpCenterGuide();
    installMessageMenuGuard();
    ensureContactSectionsHidden();
    var communityPasses = [
      ensureCommunityButton,
      ensureReadingPages,
      ensureCommunitySearch,
      ensureCallsHidden,
      ensureAllConversations,
      ensureConversationToolsHidden,
      ensureConversationGroupFlat,
      ensureCaptainHidden,
      ensureContactsHidden,
      ensureBusinessToolsHidden,
      ensureProfileDocsHidden,
      ensureSilentToggle,
      ensureHelpCenterGuide,
      ensureMessageMenuTrimmed,
      ensureCollapsedConversationMenuHidden,
      ensureContactSectionsHidden,
    ];
    var communityPassQueued = false;
    function scheduleCommunityPasses() {
      if (communityPassQueued) return;
      communityPassQueued = true;
      window.requestAnimationFrame(function () {
        communityPassQueued = false;
        communityPasses.forEach(function (pass) {
          try {
            pass();
          } catch (error) {}
        });
      });
    }
    new MutationObserver(function (records) {
      if (composerOnly(records)) return;
      scheduleCommunityPasses();
    }).observe(document.body, { childList: true, subtree: true });
    window.addEventListener("popstate", ensureCommunityButton);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeCommunity();
        closeReading();
      }
      var typing = event.target && (event.target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName));
      if (!typing && event.altKey && !event.metaKey && !event.ctrlKey && !event.shiftKey && event.code === "KeyN") {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
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

  var emojiPickerDismissUntil = 0;

  function eventElement(target) {
    if (!target) return null;
    return target.nodeType === 1 ? target : target.parentElement;
  }

  // A tap on an emoji inserts it, but iPhone does not treat that tap as an
  // outside click, so the picker stays open. Close it with the same button
  // that opened it, after the editor has taken the character.
  function dismissOpenEmojiPicker() {
    if (!document.querySelector(".emoji-dialog")) return;
    var icon = document.querySelector(".reply-box .i-ph-smiley-sticker");
    var opener = icon && icon.closest("button");
    if (!opener) return;
    opener.click();
    emojiPickerDismissUntil = Date.now() + 500;
  }

  function installEmojiPickerDismiss() {
    document.addEventListener(
      "click",
      function (event) {
        var element = eventElement(event.target);
        if (!element || !element.closest) return;
        var opener = element.closest("button");
        if (
          event.isTrusted &&
          opener &&
          opener.querySelector(".i-ph-smiley-sticker") &&
          Date.now() < emojiPickerDismissUntil
        ) {
          event.preventDefault();
          event.stopImmediatePropagation();
          return;
        }
        var dialog = element.closest(".emoji-dialog");
        if (!dialog || !opener || !dialog.contains(opener)) return;
        window.setTimeout(dismissOpenEmojiPicker, 0);
      },
      true
    );
  }

  function bootCommunity() {
    try {
      installCollapsedConversationMenuGuard();
    } catch (error) {}
    try {
      installMessageMenuGuard();
    } catch (error) {}
    try {
      installEmojiPickerDismiss();
    } catch (error) {}
    try {
      loadSilentPreference();
    } catch (error) {}
    try {
      watchCommunity();
    } catch (error) {}
  }

  if (document.body) bootCommunity();
  else document.addEventListener("DOMContentLoaded", bootCommunity);
})();
