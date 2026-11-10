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
sponsors active
sponsor <sponsor-id>
sponsor-add "Lake Charles & Calcasieu Suburbs" "Bayou Makers" local_manufacturer \
  "tomato,produce,3d_printing,custom_widgets" \
  "Grows tomatoes and prints custom 3D widgets." 30.2266 -93.2174 active -
sponsor-edit <sponsor-id> homesteader ada.yard
sponsor-disable <sponsor-id>
rank ada.yard@example.com grow_lights
jobs referrals
localities
capabilities
```

`set`, `connect`, sponsor lifecycle commands, `poll-create`, `match-approve`,
`match-reject`, and `jobs` can change data or send g01 messages. The
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
- `economy` reads the profiles built from daily questions, conversation
  questions, and their recorded answers. A shared term is a concrete word that
  appears in answers from two homesteaders in the same ZIP. It is the opening
  for a group to economize. The analysis does not invent a need.

Automatic match discovery compares recorded goals and poll answers only inside
the same locality. New proposals are operator-pending and contact no one.
`match-approve` privately pitches a reviewed proposal to both users;
`match-reject` records the decision without contacting either user. A shared
thread still requires both users to accept and both to pass identity verification.

These are deterministic operational analyses. Live private Jane chat applies
only grounded values present in the homesteader's message to the ledger and
North Star record.

## Sponsor profiles

Every sponsor is a first-class profile. A standalone local company uses `-` as
the final `sponsor-add` argument. A homestead sponsor uses its username there.
The link is optional and may be added or removed later. A company may also be
linked when its owner operates a registered homestead, so “company” and
“homesteader” are independent facts rather than competing account types.

Only active profiles appear in Jane's recommendations. Product and service
tags are comma-separated slugs, but Jane also matches inflections and words in
the capability summary: `tomato` matches “tomatoes,” and `3d_printing` plus a
widget summary matches “3D printed widgets.” Ranking remains restricted to the
requester's locality and then applies sourcing tier, distance, referral
rotation, rating, and promotion weights.

## g01 boundary

g01 remains a normally usable workspace: it owns the browser UI,
authentication, real-time messaging, files, private notes, contacts, labels,
assignment, status, snooze, priority, and password reset. g01 adds homestead
records and workflows without replacing those features.

| Area | Current behavior |
| --- | --- |
| Sign-in and reset | Active through g01 and configured SMTP |
| g01 signup | Creates a g01 agent, a property row, and a private Jane inbox |
| Private Jane chat | Active with `G01_GEMINI_API_KEY`; LangChain routes ordinary turns to Gemini Flash and complex work to Gemini Pro |
| Homesteader connection | A user enters an exact username in **g01 Community**, or the operator uses `connect`; no member directory is published |
| Files and private notes | Work normally inside every conversation the user may access |
| Contacts | Normal g01 CRM tools, scoped for homesteaders to contacts in their permitted inboxes; not a global member directory |
| Labels and custom fields | g01 thread types and public locality metadata are filterable in g01 |
| Assignment, status, snooze, priority | Normal g01 behavior remains available |
| Reports | g01 administrators use normal messaging reports; the command center provides g01 analyses |
| Campaigns and help center | Administrators can use the normal g01 workflows after configuring content and audiences |
| Email, WhatsApp, and social inboxes | Work normally only after each external provider is added and verified |
| North Star and ledger | Grounded live Jane turns update the record; operators can inspect and correct whitelisted fields |
| Sponsors | Operators manage standalone or homestead-linked profiles and lifecycle status; `rank` previews Jane's local recommendations |
| Jane polls | One question goes to each ZIP once a day. Fewer than three homesteaders, or no shared recorded word, uses the 400-question list, which asks what the homesteader wants to do. Three or more with a shared word are asked whether they are interested in that word too. A live conversation can add one more question. Answers become ZIP profiles in `analyze economy`. `poll mode` still asks the other homesteads |
| Automatic matchmaking | Discovery runs in Jane. Operators must review `matches` and confirm `match-approve` before users are contacted; both users and identity verification remain required |
| 24-hour demand polls | The sidecar matures and reports them automatically; operators may also use `jobs polls` |
| Stripe and identity | Operate only when production keys and webhooks are configured |

The `capabilities` command carries this boundary into the running system.
Provider-backed channels cannot be made operational without that provider's
account and credentials.

## Access and data handling

Run the command center only through a shell on the server. It displays email,
location, g01 identifiers, ledger facts, KYC state, conversations, polls,
and matches. Do not expose it through Caddy or copy its JSON output into a
public log.
