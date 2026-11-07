# Housecairn

[![CI](https://github.com/HouseCairn/HouseCairn/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/HouseCairn/HouseCairn/actions/workflows/ci.yml?query=branch%3Amain)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/HouseCairn/HouseCairn/badge)](https://securityscorecards.dev/viewer/?uri=github.com/HouseCairn/HouseCairn)
[![License: AGPL-3.0-only](docs/assets/license-badge.svg)](LICENSE)

Self-hosted planner for home maintenance and renovation projects: recurring
tasks, schedules, budgets and supplies, room by room. Integrates with Home
Assistant, Paperless-ngx and Sure.

> **Status: early development, not usable yet.** The application skeleton and
> its architecture are in place, without any feature screen. Do not deploy it.

## What it is for

Housecairn answers one question: what needs doing in the house, where, when,
with what and for how much. Recurring maintenance (the smoke detector battery,
the ventilation filter) and one-off projects (repainting a room) live in the
same tool, with a planned budget, supplies and a history of what was done.

## Principles

- **Self-hosted.** You run it on your own server, in a single container.
- **Works standalone.** Every feature works without any integration.
- **Optional integrations.** Home Assistant, Paperless-ngx and Sure are
  connectors you can enable; all are off by default. Housecairn links to their
  data instead of copying it.
- **Least privilege.** Integrations push to Housecairn (webhooks) wherever
  possible, rather than Housecairn holding their tokens.
- **No telemetry.** No data leaves your server, and no outgoing connection is
  made unless you configure it.

## Cost

Self-hosting Housecairn is free, for everyone, under the license below. An
official paid hosted offering may exist in the future; it would not change the
license of the code.

## How this project is built

Housecairn is developed with an AI coding agent, under human review. Each pull
request is reviewed by a second AI model, then read and merged by the human
maintainer, who is responsible for what enters the repository. Every pull
request states which AI tool and model were used.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions require signing the
[Contributor License Agreement](CLA.md) and a `Signed-off-by` line on each
commit. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

To report a vulnerability, see [SECURITY.md](SECURITY.md); do not open a public
issue.

## License

Copyright (C) 2026 Robvred.

Housecairn is licensed under the
[GNU Affero General Public License v3.0 only](LICENSE)
(`AGPL-3.0-only`), with the additional terms in [NOTICE](NOTICE): modified
versions must keep the attribution "Housecairn, by Robvred", and the
"Housecairn" name is not licensed as a trademark.
