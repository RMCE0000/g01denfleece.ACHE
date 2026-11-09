import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _value(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


def test_production_compose_publishes_only_the_website():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "caddy@sha256:" in compose
    assert '"127.0.0.1:8000:8000"' in compose
    assert "8000:8000\"" not in compose.replace('"127.0.0.1:8000:8000"', "")
    caddy = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "g01denfleece.com" in caddy
    assert "reverse_proxy rails:3000" in caddy
    assert "handle /webhooks/stripe" in caddy
    assert "reverse_proxy jane:8000" in caddy
    base = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SMTP_USERNAME:" not in base
    assert "SMTP_USERNAME: ${SMTP_USERNAME:-}" in compose
    assert 'FORCE_SSL: "true"' in compose
    assert "image: chatwoot/chatwoot@sha256:" in base
    assert "ollama/ollama" not in base
    assert "langchain-google-genai>=4.4.2" in (
        ROOT / "jane-sidecar" / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert "condition: service_healthy" in compose
    assert "git" in (
        ROOT / "deploy" / "google-cloud" / "cloud-init.yaml"
    ).read_text(encoding="utf-8")
    launch = (ROOT / "docs" / "GOOGLE_CLOUD_LAUNCH.md").read_text(encoding="utf-8")
    assert "us-central1" in launch
    assert "webhooks/stripe" in launch
    assert "create-vm.sh" in launch
    bootstrap = (ROOT / "ops" / "bootstrap_chatwoot.rb").read_text(encoding="utf-8")
    assert 'raise "g01 platform token is empty"' in bootstrap
    assert 'raise "g01 API token is empty"' in bootstrap
    assert "G01_CHATWOOT_WEBHOOK_SECRET" in bootstrap
    assert "where.not(url: WEBHOOK_URL).destroy_all" in bootstrap

    rendered = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.prod.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "ACME_EMAIL": "ops@g01denfleece.com"},
    )
    services = json.loads(rendered.stdout)["services"]
    published = []
    for name, service in services.items():
        for port in service.get("ports") or []:
            published.append(
                (
                    name,
                    str(port.get("host_ip") or ""),
                    str(port.get("published")),
                    str(port.get("target")),
                    str(port.get("protocol")),
                )
            )
    assert ("caddy", "", "80", "80", "tcp") in published
    assert ("caddy", "", "443", "443", "tcp") in published
    assert ("jane", "127.0.0.1", "8000", "8000", "tcp") in published
    for name, host_ip, public, _target, _protocol in published:
        if name == "caddy":
            assert public in {"80", "443"}
        elif name == "jane":
            assert host_ip == "127.0.0.1" and public == "8000"
        else:
            raise AssertionError(f"{name} publishes {host_ip}:{public}")


def test_production_env_check_rejects_local_secrets(tmp_path):
    script = ROOT / "deploy" / "check-prod-env.sh"
    example = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    bad = tmp_path / "bad.env"
    bad.write_text(example, encoding="utf-8")
    rejected = subprocess.run(["sh", str(script), str(bad)], capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "placeholder" in rejected.stderr.lower() or "SECRET_KEY_BASE" in rejected.stderr

    good_text = example
    replacements = {
        "SECRET_KEY_BASE": "a" * 64,
        "POSTGRES_PASSWORD": "b" * 24,
        "G01_ADMIN_TOKEN": "c" * 32,
        "G01_BRIDGE_SECRET": "d" * 32,
        "G01_CHATWOOT_WEBHOOK_SECRET": "e" * 32,
        "ACME_EMAIL": "ops@g01denfleece.com",
        "SMTP_ADDRESS": "smtp.example.net",
        "SMTP_USERNAME": "smtp-user",
        "SMTP_PASSWORD": "mailbox-secret",
        "G01_GEMINI_API_KEY": "google-ai-key",
        "G01_STRIPE_SECRET_KEY": "sk_test_launch",
        "G01_STRIPE_WEBHOOK_SECRET": "whsec_launch",
        "G01_STRIPE_SPONSOR_PRICE_ID": "price_launch",
    }
    lines = []
    for line in good_text.splitlines():
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in replacements:
            lines.append(f"{key}={replacements[key]}")
        elif key == "G01_DATABASE_URL":
            lines.append(
                "G01_DATABASE_URL=postgresql+asyncpg://g01:"
                + replacements["POSTGRES_PASSWORD"]
                + "@postgres:5432/chatwoot"
            )
        else:
            lines.append(line)
    good = tmp_path / "good.env"
    good.write_text("\n".join(lines) + "\n", encoding="utf-8")
    accepted = subprocess.run(["sh", str(script), str(good)], capture_output=True, text=True)
    assert accepted.returncode == 0, accepted.stderr
    assert "production env is ready" in accepted.stdout
