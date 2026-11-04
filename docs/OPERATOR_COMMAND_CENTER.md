# Operator command center

The command center is the backend for g01 operations. It reads the same
Postgres data and environment as Jane, so it stays private on the server and
does not require another web dashboard.

Start it on the host:

```bash
docker compose exec jane python -m app.operator
```

It opens with a dashboard and a `g01>` prompt. Enter `help` to see the command
list. Commands containing spaces accept shell-style quotes.

```text
users
user ada.yard@example.com
chats
chat 3
analyze all
analyze engagement
analyze northstar
analyze network
set ada.yard@example.com aesthetic 82
set ada.yard@example.com labor-hours 12
connect ada.yard@example.com bea.chenier@example.com "shared greenhouse"
rank ada.yard@example.com grow_lights
jobs referrals
localities
capabilities
```

`set`, `connect`, and `jobs` can change data or send Chatwoot messages. The
interactive console asks before running them. `set` is limited to the fields
listed by `help`; arbitrary database columns cannot be changed.

## One-shot and JSON use

A command can be run without opening the prompt:

```bash
docker compose exec jane python -m app.operator users
docker compose exec jane python -m app.operator --json analyze network
```

Mutating one-shot commands require `--yes`:

```bash
docker compose exec jane python -m app.operator --yes \
  connect ada.yard@example.com bea.chenier@example.com "shared greenhouse"
```

This makes shell scripts fail closed instead of opening a connection by
accident.

## What the analyses mean

- `engagement` counts visible messages in each private Jane thread. It reports
  registrations with and without a homesteader message.
- `northstar` reads the five stored North Star dimensions and active goals. It
  does not ask a language model to infer a score.
- `network` counts provisioned homesteader connections and identifies people
  with no connection.

These are deterministic operational analyses. The minimum-showcase live chat
does not update the old MVP ledger or North Star values.

## Chatwoot boundary

Chatwoot remains a normally usable workspace: it owns the browser UI,
authentication, real-time messaging, files, private notes, contacts, labels,
assignment, status, snooze, priority, and password reset. g01 adds homestead
records and workflows without replacing those features.

| Area | Current behavior |
| --- | --- |
| Sign-in and reset | Active through Chatwoot and configured SMTP |
| g01 signup | Creates a Chatwoot agent, a property row, and a private Jane inbox |
| Private Jane chat | Active; Ollama receives the constitution and visible history |
| Homesteader connection | A user opens **g01 Community** in Chatwoot, or the operator uses `connect` |
| Files and private notes | Work normally inside every conversation the user may access |
| Contacts | Normal Chatwoot CRM; g01 mirrors only non-sensitive member/locality data because contacts are account-wide |
| Labels and custom fields | g01 thread types and public locality metadata are filterable in Chatwoot |
| Assignment, status, snooze, priority | Normal Chatwoot behavior remains available |
| Reports | Chatwoot administrators use normal messaging reports; the command center provides g01 analyses |
| Campaigns and help center | Administrators can use the normal Chatwoot workflows after configuring content and audiences |
| Email, WhatsApp, and social inboxes | Work normally only after each external provider is added and verified |
| North Star and ledger | Inspectable in the command center; not updated by live MS chat |
| Sponsors | Ranking can be previewed with `rank` |
| Polls and matchmaking | Existing workflows can be run explicitly with `jobs`; scheduling remains off |
| Stripe and identity | Operate only when production keys and webhooks are configured |

The `capabilities` command carries this boundary into the running system.
Provider-backed channels cannot be made operational without that provider's
account and credentials.

## Access and data handling

Run the command center only through a shell on the server. It displays email,
location, Chatwoot identifiers, ledger facts, KYC state, conversations, polls,
and matches. Do not expose it through Caddy or copy its JSON output into a
public log.
