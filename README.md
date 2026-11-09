<p align="center"><img src="design/brand/housecairn-logo.svg" alt="HouseCairn" width="360"></p>

# HouseCairn

[![CI](https://github.com/HouseCairn/housecairn/actions/workflows/ci.yml/badge.svg?event=merge_group)](https://github.com/HouseCairn/housecairn/actions/workflows/ci.yml?query=event%3Amerge_group)
[![Image](https://github.com/HouseCairn/housecairn/actions/workflows/image.yml/badge.svg?branch=main)](https://github.com/HouseCairn/housecairn/actions/workflows/image.yml?query=branch%3Amain)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/HouseCairn/housecairn/badge)](https://securityscorecards.dev/viewer/?uri=github.com/HouseCairn/housecairn)
[![License: AGPL-3.0-only](docs/assets/license-badge.svg)](LICENSE)

Self-hosted planner for home maintenance and renovation projects: recurring
tasks, schedules, budgets and supplies, room by room. Integrates with Home
Assistant, Paperless-ngx and Sure.

> **Status: early development, not usable yet.** The application skeleton and
> its architecture are in place, without any feature screen. Do not deploy it.

## What it is for

HouseCairn answers one question: what needs doing in the house, where, when,
with what and for how much. Recurring maintenance (the smoke detector battery,
the ventilation filter) and one-off projects (repainting a room) live in the
same tool, with a planned budget, supplies and a history of what was done.

## Principles

- **Self-hosted.** You run it on your own server, in a single container.
- **Works standalone.** Every feature works without any integration.
- **Optional integrations.** Home Assistant, Paperless-ngx and Sure are
  connectors you can enable; all are off by default. HouseCairn links to their
  data instead of copying it.
- **Least privilege.** Integrations push to HouseCairn (webhooks) wherever
  possible, rather than HouseCairn holding their tokens.
- **No telemetry.** No data leaves your server, and no outgoing connection is
  made unless you configure it.

## Install

HouseCairn runs as a single container,
`ghcr.io/housecairn/housecairn`, for `linux/amd64` and `linux/arm64`, with
SQLite by default and PostgreSQL as an option. Every published image carries a
signed build provenance and SBOM. See [Installing with Docker
Compose](docs/getting-started/install.md) for the example `compose.yaml`, and
the administration pages for backups, updates, environment variables and how
to verify an image.

## Documentation

The documentation is at <https://docs.housecairn.app>, in English and French.
Its sources are in [docs/](docs/index.md); how to build it locally is in
[CONTRIBUTING.md](CONTRIBUTING.md#documentation).

## Cost

Self-hosting HouseCairn is free, for everyone, under the license below. An
official paid hosted offering may exist in the future; it would not change the
license of the code.

## How this project is built

HouseCairn is developed with an AI coding agent, under human review. Each pull
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

HouseCairn is licensed under the
[GNU Affero General Public License v3.0 only](LICENSE)
(`AGPL-3.0-only`), with the additional terms in [NOTICE](NOTICE): modified
versions must keep the author attribution given there, and the HouseCairn name
and logo are not licensed as a trademark.
