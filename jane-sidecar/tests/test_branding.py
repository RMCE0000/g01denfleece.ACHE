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
    assert 'document.querySelectorAll(\'nav a[href*="/mentions/"]\')' in script
    assert ".g01-hidden-mentions" in css
    assert 'element.textContent.trim() === "All Conversations"' in script
    assert 'label.textContent = "Conversations"' in script
    assert 'if (label.textContent !== "Conversations")' in script
    assert "g01-hidden-conversation-filter" in script
    assert ".g01-conversations-single" in css
    assert ".g01-conversations-primary" in css
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
