from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_brand_assets_are_gold_and_white():
    css = (ROOT / "branding" / "g01-brand.css").read_text(encoding="utf-8")
    logo = (ROOT / "branding" / "g01-logo.png").read_bytes()
    mark = (ROOT / "branding" / "g01-mark.svg").read_text(encoding="utf-8")
    script = (ROOT / "branding" / "g01-brand.js").read_text(encoding="utf-8")
    assert "#7a5e24" in css
    assert "#f7f5f0" in css
    assert logo.startswith(b"\x89PNG\r\n\x1a\n") and len(logo) > 10_000
    assert "#7A5E24" in mark
    assert "/g01-logo.png" in script
    favicon = (ROOT / "branding" / "g01-favicon.png").read_bytes()
    assert favicon.startswith(b"\x89PNG\r\n\x1a\n") and len(favicon) > 10_000
    assert "/g01-favicon.png" in script
    assert "Sign in to g01" in script
    assert "uppercase, lowercase, a number, and a special character" in script
    assert "g01-field-help" in css
    assert "g01-login-page" in script
    assert "g01-login-page img" in css
    assert (ROOT / "branding" / "g01-mark.png").stat().st_size > 500
    initializer = (ROOT / "ops" / "g01_branding.rb").read_text(encoding="utf-8")
    assert "g01-brand.css" in initializer
    assert 'gsub("Login to Chatwoot", "Sign in to g01")' in initializer
    assert "/g01/signup" in initializer
    assert "Create an account" in script
    assert "thread with Jane" not in script
    assert "/g01/signup" in script
    assert "g01 Community" in script
    assert 'communityElement("li", "g01-community-item")' in script
    assert 'communityElement("span", "g01-community-glyph", "g01")' in script
    assert 'communityElement("span", "g01-community-label", "Community")' in script
    assert 'button.title = "Community"' in script
    assert "height: 2.625rem" in css
    assert "align-self: start" in css
    assert '"g01-community-label", "g01 Community"' not in script
    assert "Username" in script
    assert "Enter the username of a peer to start a conversation." in script
    assert "Search conversations you have already opened through Community." in script
    assert "Search by peer name or username" in script
    assert 'label.textContent = "Search…"' in script
    assert "white-space: nowrap" in css
    assert 'openCommunitySearch(link)' in script
    assert 'connection.conversation_path' in script
    assert "g01-hidden-compose" in script
    assert ".g01-hidden-compose" in css
    assert 'document.querySelectorAll(\'a[href*="/calls"]\')' in script
    assert ".g01-hidden-calls" in css
    assert '"Mentions", "Participating", "Unattended", "Folders", "Teams", "Channels", "Labels"' in script
    assert "g01-hidden-conversation-tool" in script
    assert ".g01-hidden-conversation-tool" in css
    assert 'document.querySelectorAll("nav .i-woot-captain")' in script
    assert 'hideSidebarEntries(["Captain", "Captain AI"], "g01-hidden-captain")' in script
    assert ".g01-hidden-captain" in css
    assert 'label.textContent = "Conversations"' not in script
    assert "ensureComposerHint" not in script
    assert '.reply-box .empty-node::before' in css
    assert 'content: "Shift + enter for new line."' in css
    assert ".actions--container > .resolve-actions" in css
    assert ".conversations-list-wrap > .h-10.w-full.px-3.-mt-1" in css
    assert "function ensureAllConversations" in script
    assert 'assigneeTabLabel(link) === "All"' in script
    assert "all.click()" in script
    assert 'event.code === "KeyN"' in script
    assert "function insideComposer" in script
    assert "function composerOnly" in script
    assert "function scheduleCommunityPasses" in script
    assert '.ProseMirror, .reply-box' in script
    assert "composerOnly(records)" in script
    assert "height: 100dvh !important" in css
    assert "max-height: 100dvh !important" in css
    assert "def resize_with_keyboard" in initializer
    assert "interactive-widget=resizes-content" in initializer
    assert "def strip_chatwoot_icons" in initializer
    assert "def paint_phone_chrome" in initializer
    assert 'name="theme-color" content="#7a5e24"' in initializer
    assert "html {\n  background: #7a5e24 !important;\n}" in css
    assert 'font-family: "G01 Login"' in css
    assert "/g01-login-serif-500.woff2?v=49" in css
    assert "/g01-login-serif-600.woff2?v=49" in css
    assert "color: #8e98a6 !important" in css
    assert (ROOT / "branding" / "fonts" / "g01-login-serif-500.woff2").read_bytes().startswith(b"wOF2")
    assert (ROOT / "branding" / "fonts" / "g01-login-serif-600.woff2").read_bytes().startswith(b"wOF2")
    assert "function dismissOpenEmojiPicker" in script
    assert "function installEmojiPickerDismiss" in script
    assert 'element.closest(".emoji-dialog")' in script
    assert '".reply-box .i-ph-smiley-sticker"' in script
    assert "function applyColorScheme" in script
    assert "function savedColorScheme" in script
    assert "function systemIsDark" in script
    assert '"(prefers-color-scheme: dark)"' in script
    assert 'selected === "dark"' in script
    assert 'selected === "auto" || !selected' in script
    assert "function light(" not in script
    assert 'localStorage.setItem(key, "light")' not in script
    assert "--slate-12: 42 36 24;" in css
    assert "--slate-12: 244 239 230;" in css
    assert "body.dark," in css
    assert "background: #16130f !important;" in css
    assert "color: #e4c98a !important;" in css
    assert "function ensureProfileDocsHidden" in script
    assert "g01-hidden-profile-docs" in script
    assert ".g01-hidden-profile-docs" in css
    assert ".n-dropdown-item:has(.i-lucide-book)" in css
    assert 'a[href*="chatwoot.com/hc"]' in css
    assert ".n-dropdown-item:has(.i-lucide-scroll-text)" in css
    assert 'a[href*="chatwoot.com/changelog"]' in css
    assert "function ensureSilentToggle" in script
    assert "function dashboardSoundIsSilent" in script
    assert "function saveSilent" in script
    assert "var silentChosen = false" in script
    assert "silentChosen = true" in script
    assert "function withoutNotificationBanners" in script
    assert "enable_audio_alerts: silent ? \"none\" : \"all\"" in script
    assert ".i-lucide-volume-2" in script
    assert 'title.textContent = "Silent"' in script
    assert 'heading.textContent = "Notifications"' in script
    assert "g01-hidden-notification-preferences" in script
    assert ".g01-hidden-notification-form" in css
    assert ".g01-silent-row" in css
    assert "v=72" in initializer
    assert "v=71" not in initializer
    assert "Core Tenets" in script
    assert "Score Card" in script
    assert "10 Core Tenets" not in script
    assert "Central Score Card" not in script
    assert 'glyph: "1"' in script
    assert 'glyph: "0"' in script
    assert "Every homestead ought be," in script
    assert "Clean - The central difference between a company and homesteader" in script
    assert "Integrated - A homestead ought contribute to its city's sovereignty" in script
    assert "The property ought produce and profit off of its own energy, indefinitely." in script
    assert "homesteaders and all assets ought be insured." in script
    assert "The ten core tenets will be written on this page." not in script
    assert "local homestead + 0" in script
    assert "company abroad + 7" in script
    assert "0 is the target." in script
    assert "The central score card will be written on this page." not in script
    assert 'communityElement("button", "g01-community-open")' in script
    assert "function ensureReadingPages" in script
    assert "function openReading" in script
    assert "function signupDetail" in script
    assert "def signup_error_body" in initializer
    assert "Password must be 72 characters or fewer." in script
    assert "function shapeThinking" in script
    assert "function showThinking" in script
    assert "function janeWillAnswer" in script
    assert 'row.className = "g01-thinking-row g01-thinking-live"' in script
    assert 'pill.appendChild(document.createTextNode("Jane is thinking"))' in script
    assert ".g01-thinking-live" in css
    assert 'img[alt="Someone is typing"]' in css
    assert 'row.classList.add("g01-thinking-row")' in script
    assert 'replace(/\\bis typing\\b/gi, "is thinking")' in script
    assert ".g01-thinking-row" in css
    assert "@keyframes g01-think" in css
    assert "function pinTabIcon" in script
    assert "function pinTabTitle" in script
    assert 'link.classList.remove("favicon")' in script
    assert 'var TAB_TITLE = "g01denfleece"' in script
    assert "title.replace(/chatwoot/gi, TAB_TITLE)" in script
    assert 'next === "Sign in · g01"' in script
    assert "def name_the_tab" in initializer
    assert 'attributeFilter: ["href", "rel", "class"]' in script
    assert "function contactListItem" in script
    assert "function ensureContactSectionsHidden" in script
    assert '"conversation actions": true' in script
    assert "macros: true" in script
    assert ".g01-hidden-contact-section" in css
    assert ".woot-banner.secondary" in css
    assert "function installCollapsedConversationMenuGuard" in script
    assert 'title !== "conversations"' in script
    assert 'label === "conversations"' in script
    assert 'indexOf("all conversations")' in script
    assert "g01-hidden-conversation-flyout" in script
    assert ".g01-hidden-conversation-flyout" in css
    assert ".fixed.z-\\[100\\].min-w-\\[200px\\]:has(.uppercase.tracking-wider)" in css
    assert "function ensureMessageMenuTrimmed" in script
    assert "function installMessageMenuGuard" in script
    assert '"add to canned responses"' in script
    assert "translate: true" in script
    assert "M16.953 5.303" in script
    assert "M12.022 3a6.473" in script
    assert "g01-hidden-message-menu-item" in script
    assert ".g01-hidden-message-menu-item" in css
    assert 'path[d^="M16.953 5.303"]' in css
    assert 'path[d^="M12.022 3a6.473"]' in css
    assert ".conversations-list-wrap" in css
    assert "> .flex.items-center.gap-2.flex-shrink-0" in css
    assert "> .absolute:has(> .flex.items-center.justify-between)" in css
    assert "> .bg-n-amber-2" in css
    assert "width: fit-content !important" in css
    assert ".reply-box button:has(.i-ph-sparkle-fill)" in css
    assert "button:has(.i-woot-captain)" in css
    assert ".reply-box .copilot-editor-menu" in css
    assert 'document.querySelectorAll("nav .i-lucide-contact")' in script
    assert ".g01-hidden-contacts" in css
    assert '".i-lucide-building-2", "g01-hidden-companies"' in script
    assert '".i-lucide-bolt", "g01-hidden-settings"' in script
    assert ".g01-hidden-companies" in css
    assert ".g01-hidden-settings" in css
    assert 'document.querySelectorAll(\'nav a[href*="/portals"]\')' in script
    assert 'label.textContent = "Product Guide"' in script
    assert 'window.location.assign("/hc/g01-guide/en")' in script
    assert ".g01-hidden-help-center-control" in css
    assert "exact username" not in script
    assert "public member directory" not in script
    assert "member_id" not in script
    assert "window.axios" in script
    assert "X-G01-Requested-With" in script
    bootstrap = (ROOT / "ops" / "bootstrap_chatwoot.rb").read_text(encoding="utf-8")
    assert 'widget_color: "#7A5E24"' in bootstrap
    assert 'SITE_NAME = "g01denfleece.com"' in bootstrap
    assert 'SITE_URL = "https://g01denfleece.com"' in bootstrap
    assert "website_url: SITE_URL" in bootstrap
    assert "/g01-logo.png" in bootstrap
    assert '"LOGO_THUMBNAIL" => "/g01-favicon.png"' in bootstrap
    assert ".right-bubble" in css
    assert ".left-bubble" in css
    assert "#eef2f3" in css
    assert ".g01-own-message .right-bubble" in css
    assert ".g01-other-message .right-bubble" in css
    assert ".conversation-wrap .right .message-content" not in css
    assert 'window.axios.get("/auth/validate_token")' in script
    assert '"/api/v1/accounts/"' in script
    assert '"/conversations/"' in script
    assert '"/messages"' in script
    assert 'message.getAttribute("data-message-id")' in script
    assert 'message.classList.toggle("g01-own-message", own)' in script
    assert "Number(senderId) === Number(currentUserId)" in script
    assert "response.data.payload.data.id" in script
    assert "response.data.payload || []" in script
    assert "__vueParentComponent" not in script
    assert "WOOT.$store" not in script
    assert "nav ul.items-center .g01-community-label" in css
    assert "min-height: 1.25rem" in css
    assert '[data-bubble-name="audio"] > audio.g01-native-audio' in css
    assert '.message-bubble-container[data-bubble-name="audio"]' in css
    assert ".g01-audio-message.right-bubble" in css
    assert "enhanceAudioPlayers" in script
    assert '"/rails/active_storage/blobs/proxy/"' in script
    assert 'audio.classList.remove("hidden")' in script
    assert 'audio.nextElementSibling.classList.add("g01-audio-custom-controls")' in script
    assert 'message.classList.add("g01-audio-message")' in script
    assert ".fetch(playbackUrl" in script
    assert 'credentials: "same-origin"' in script
    assert "URL.createObjectURL(blob)" in script
    assert "installAudioPlaybackRecovery" not in script
    assert "installFastAudioRecorder" in script
    assert '"audio/webm;codecs=opus"' in script
    assert 'form.append("attachments[]", file)' in script
    assert 'form.append("is_voice_message", "true")' in script
    assert "audioBitsPerSecond: 48000" in script
    assert "Stop and send audio" in script
    assert r".*\/conversations?\/(\d+)" in script
    assert "activeRecorder.button === button" not in script
    assert 'activeRecorder.recorder.state === "recording"' in script
    assert "platform.access_token" in bootstrap
    assert 'raise "g01 bridge secret is empty"' in bootstrap
    assert "CHATWOOT_INSTALLATION_ONBOARDING" in bootstrap
    assert "g01-connection" in bootstrap
    assert "custom_attribute_definitions" in bootstrap
    assert 'slug: "g01-guide"' in bootstrap
    assert 'channel_web_widget: channel' in bootstrap
    assert 'status: :published' in bootstrap
    assert 'title: "Welcome to g01"' in bootstrap
    assert 'title: "Working with Jane"' in bootstrap
    assert 'title: "Messages, audio, and files"' in bootstrap
    assert 'title: "Community conversations"' in bootstrap
    assert 'title: "Local sponsors and recommendations"' in bootstrap
    assert 'title: "Buying a sponsorship"' in bootstrap
    assert "start sponsorship" in bootstrap
    assert "turns on after Stripe marks the payment paid" in bootstrap
    assert 'title: "Your account and privacy"' in bootstrap
    assert "has not appeared earlier in your chat" in bootstrap
    assert "internal score" not in bootstrap.lower()
    assert "tier_weight" not in bootstrap
    controller = (ROOT / "ops" / "g01_community_controller.rb").read_text(encoding="utf-8")
    assert "Api::V1::Accounts::BaseController" in controller
    assert "dashboard authentication required" in controller
    assert "G01_BRIDGE_SECRET" in controller
    contacts_scope = (ROOT / "ops" / "g01_contacts_scope.rb").read_text(encoding="utf-8")
    assert "g01_visible_contacts" in contacts_scope
    assert "InboxMember.where(user_id: Current.user.id)" in contacts_scope
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "\n  RAILS_SERVE_STATIC_FILES: \"true\"" in compose
    assert "\n      RAILS_SERVE_STATIC_FILES:" not in compose
    assert "/app/public/g01-logo.png" in compose
    assert "/app/public/g01-favicon.png" in compose
    assert "g01_branding.rb" in compose
    assert "g01_audio_playback.rb" not in compose
    assert "g01_community_controller.rb" in compose
    assert "g01_contacts_scope.rb" in compose
    assert "G01_BRIDGE_SECRET:" in compose
    assert "chatwoot_storage:/app/storage" in compose
    assert "axllent/mailpit@sha256:" in compose
    assert "SMTP_ADDRESS: ${SMTP_ADDRESS:-mailpit}" in compose
    assert 'SMTP_ENABLE_STARTTLS_AUTO: ${SMTP_ENABLE_STARTTLS_AUTO:-false}' in compose
