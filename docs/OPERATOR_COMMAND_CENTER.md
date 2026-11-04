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
analyze polls
polls
poll <poll-id>
poll-create "What project should the community organize next?"
matches pending
match <match-id>
match-approve <match-id> "grounded in recorded goals"
match-reject <match-id> "not appropriate"
set ada.yard@example.com aesthetic 82
set ada.yard@example.com labor-hours 12
connect ada.yard@example.com bea.chenier@example.com "shared greenhouse"
rank ada.yard@example.com grow_lights
jobs referrals
localities
capabilities
```

`set`, `connect`, `poll-create`, `match-approve`, `match-reject`, and `jobs` can change data or send Chatwoot messages. The
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
docker compose exec jane python -m app.operator --yes \
  poll-create "What project should the community organize next?"
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
- `polls` compiles response rates, recurring terms, action candidates, and the
  attributed source answers. It never asks a model to invent a consensus.

Automatic match discovery compares recorded goals and poll answers only inside
the same locality. New proposals are operator-pending and contact no one.
`match-approve` privately pitches a reviewed proposal to both users;
`match-reject` records the decision without contacting either user. A shared
thread still requires both users to accept and both to pass identity verification.

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
| Homesteader connection | A user enters an exact username in **g01 Community**, or the operator uses `connect`; no member directory is published |
| Files and private notes | Work normally inside every conversation the user may access |
| Contacts | Normal Chatwoot CRM tools, scoped for homesteaders to contacts in their permitted inboxes; not a global member directory |
| Labels and custom fields | g01 thread types and public locality metadata are filterable in Chatwoot |
| Assignment, status, snooze, priority | Normal Chatwoot behavior remains available |
| Reports | Chatwoot administrators use normal messaging reports; the command center provides g01 analyses |
| Campaigns and help center | Administrators can use the normal Chatwoot workflows after configuring content and audiences |
| Email, WhatsApp, and social inboxes | Work normally only after each external provider is added and verified |
| North Star and ledger | Inspectable in the command center; not updated by live MS chat |
| Sponsors | Ranking can be previewed with `rank` |
| Jane polls | One rotating question is sent daily in each private Jane thread. `poll mode` starts the community-action question; `poll mode: <question>` broadcasts a supplied question. Operators use `polls`, `poll`, `poll-create`, and `analyze polls` |
| Automatic matchmaking | Discovery runs in Jane. Operators must review `matches` and confirm `match-approve` before users are contacted; both users and identity verification remain required |
| Legacy demand polls | Existing workflows can be run explicitly with `jobs polls`; Celery scheduling remains off |
| Stripe and identity | Operate only when production keys and webhooks are configured |

The `capabilities` command carries this boundary into the running system.
Provider-backed channels cannot be made operational without that provider's
account and credentials.

## Access and data handling

Run the command center only through a shell on the server. It displays email,
location, Chatwoot identifiers, ledger facts, KYC state, conversations, polls,
and matches. Do not expose it through Caddy or copy its JSON output into a
public log.
