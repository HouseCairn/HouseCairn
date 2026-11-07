# htmx (vendored)

- Version: 2.0.11
- Source: npm package `htmx.org@2.0.11`, file `dist/htmx.min.js`, unmodified.
- Tarball integrity, as published on the npm registry:
  `sha512-Thx/WtpeOQqSrqBCw/A1cwGJGg4UrVa3+sW0GmrM3p4gJgO89ecH4qtbnyzDDWFvBTqjnIMCgELTNt636dtamA==`
- `htmx.min.js` SHA-256: `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717`
- `htmx.min.js` subresource integrity (used in `templates/base.html`):
  `sha384-2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg`
- License: Zero-Clause BSD, see `LICENSE`.

The test `test_vendored_htmx_matches_its_recorded_hash` in
`tests/test_security.py` checks the SHA-256 above. To upgrade: download the new
tarball from the npm registry, check its integrity against the
registry, copy `dist/htmx.min.js`, then update this file, the template and the
test in the same pull request.
