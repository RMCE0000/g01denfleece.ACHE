"""Local demo sign-ins so the Chatwoot screen can be opened without a manual API call.

The passwords below are for the local stack only. Later boots do not change a
password Chatwoot already stored.
"""

import logging
import os
from pathlib import Path

from app.homesteaders import open_peer_conversation, provision_homesteader

log = logging.getLogger(__name__)

DEMO_HOMESTEADERS = (
    {
        "name": "Ada Yard",
        "email": "ada.yard@example.com",
        "password": "G01seed-Ada-70601",
        "zip_code": "70601",
    },
    {
        "name": "Bea Chenier",
        "email": "bea.chenier@example.com",
        "password": "G01seed-Bea-70605",
        "zip_code": "70605",
    },
)


def _credentials_path() -> Path | None:
    candidates = [Path("/bootstrap"), Path(__file__).resolve().parents[2] / ".chatwoot-bootstrap"]
    for directory in candidates:
        if directory.is_dir() and os.access(directory, os.W_OK):
            return directory / "homesteaders.txt"
    return None


def _write_credentials(lines: list[str]) -> None:
    path = _credentials_path()
    if path is None:
        log.info("homesteader credentials were not written; no writable bootstrap directory")
        return
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o644)


async def seed_signed_in_homesteaders(store) -> None:
    created = []
    for fields in DEMO_HOMESTEADERS:
        created.append(await provision_homesteader(store, fields))
    peer = await open_peer_conversation(
        store,
        DEMO_HOMESTEADERS[0]["email"],
        DEMO_HOMESTEADERS[1]["email"],
        "shared homestead",
    )
    lines = [
        "Local demo sign-ins. These passwords are not rotated after the first create.",
        f"Sign in at {created[0]['login_url']}",
        "",
    ]
    for fields, row in zip(DEMO_HOMESTEADERS, created):
        lines.extend(
            [
                f"{fields['name']} <{fields['email']}>",
                f"password: {fields['password']}",
                f"Jane conversation: {row.get('conversation_url')}",
                "",
            ]
        )
    lines.extend(
        [
            f"Conversation between them: {peer['conversation_url']}",
            "Inbox name: Ada Yard and Bea Chenier",
            "Jane stays quiet in that thread unless someone says her name.",
        ]
    )
    _write_credentials(lines)
    log.info("signed-in demo homesteaders are %s and %s", DEMO_HOMESTEADERS[0]["email"], DEMO_HOMESTEADERS[1]["email"])
