# Contributing to Housecairn

Thank you for your interest. Housecairn is in early development: before
starting significant work, please open an issue to discuss it.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before your pull request can be merged

1. **Sign the CLA.** Every contributor signs the
   [Contributor License Agreement](CLA.md) once. The CLA Assistant bot asks you
   to do so in your first pull request. You keep the copyright of your work.
2. **Sign off every commit** with the
   [Developer Certificate of Origin](https://developercertificate.org/):

   ```sh
   git commit -s -m "fix: handle empty schedules"
   ```

   This adds a `Signed-off-by: Your Name <you@example.com>` line. Pull requests
   with unsigned-off commits cannot be merged.

## Pull requests

- **Small and focused.** One topic per pull request. Unrelated refactoring or
  reformatting goes in its own pull request.
- **Title in [Conventional Commits](https://www.conventionalcommits.org/)
  format**, for example `feat: add yearly recurrence` or
  `fix(schedule): skip archived rooms`. Pull requests are merged by squash: the
  title and description become the commit message on `main`.
- **Documentation in the same pull request as the code** it describes.
- **Fill in the pull request template**, including what you actually ran to
  verify the change.
- All user-facing text is in English in the code and goes through translation
  functions; no hard-coded strings.

## AI-assisted contributions

AI tools are welcome, under these rules:

- **Declare the tool and model** you used in the pull request template.
- **A human is responsible for the pull request.** You must understand every
  line you submit, have reviewed it yourself, and be able to answer questions
  about it.
- **No unsolicited pull requests from autonomous agents.** Pull requests
  opened by an agent without a human author who answers for them will be
  closed.

## Security issues

Do not report vulnerabilities in public issues or pull requests. See
[SECURITY.md](SECURITY.md).
