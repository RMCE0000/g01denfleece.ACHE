from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_brand_assets_are_gold_and_white():
    css = (ROOT / "branding" / "g01-brand.css").read_text(encoding="utf-8")
    logo = (ROOT / "branding" / "g01-logo.svg").read_text(encoding="utf-8")
    mark = (ROOT / "branding" / "g01-mark.svg").read_text(encoding="utf-8")
    script = (ROOT / "branding" / "g01-brand.js").read_text(encoding="utf-8")
    assert "#7a5e24" in css
    assert "#ffffff" in css
    assert "#7A5E24" in logo and "g01" in logo
    assert "#7A5E24" in mark
    assert "/g01-logo.svg" in script
    assert (ROOT / "branding" / "g01-mark.png").stat().st_size > 500
    initializer = (ROOT / "ops" / "g01_branding.rb").read_text(encoding="utf-8")
    assert "g01-brand.css" in initializer
    assert "/g01/signup" in initializer
    assert "Create an account" in script
    assert "thread with Jane" not in script
    assert "/g01/signup" in script
    assert "g01 Community" in script
    assert "window.axios" in script
    assert "X-G01-Requested-With" in script
    bootstrap = (ROOT / "ops" / "bootstrap_chatwoot.rb").read_text(encoding="utf-8")
    assert 'widget_color: "#7A5E24"' in bootstrap
    assert 'SITE_NAME = "g01denfleece.com"' in bootstrap
    assert 'SITE_URL = "https://g01denfleece.com"' in bootstrap
    assert "website_url: SITE_URL" in bootstrap
    assert "/g01-logo.svg" in bootstrap
    assert "platform.access_token" in bootstrap
    assert 'raise "g01 bridge secret is empty"' in bootstrap
    assert "CHATWOOT_INSTALLATION_ONBOARDING" in bootstrap
    assert "g01-connection" in bootstrap
    assert "custom_attribute_definitions" in bootstrap
    controller = (ROOT / "ops" / "g01_community_controller.rb").read_text(encoding="utf-8")
    assert "Api::V1::Accounts::BaseController" in controller
    assert "dashboard authentication required" in controller
    assert "G01_BRIDGE_SECRET" in controller
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "\n  RAILS_SERVE_STATIC_FILES: \"true\"" in compose
    assert "\n      RAILS_SERVE_STATIC_FILES:" not in compose
    assert "/app/public/g01-logo.svg" in compose
    assert "g01_branding.rb" in compose
    assert "g01_community_controller.rb" in compose
    assert "G01_BRIDGE_SECRET:" in compose
    assert "chatwoot_storage:/app/storage" in compose
    assert "axllent/mailpit@sha256:" in compose
    assert "SMTP_ADDRESS: ${SMTP_ADDRESS:-mailpit}" in compose
    assert 'SMTP_ENABLE_STARTTLS_AUTO: ${SMTP_ENABLE_STARTTLS_AUTO:-false}' in compose
