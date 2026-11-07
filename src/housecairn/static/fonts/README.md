# Fonts (self-hosted)

| File | Family | Source | Licence |
| --- | --- | --- | --- |
| `Manrope-latin-variable.woff2` | Manrope, variable weight 200 to 800, Latin subset | `@fontsource-variable/manrope` (npm), file `latin-wght-normal.woff2`, unmodified | SIL OFL 1.1, `Manrope-OFL.txt` |
| `JetBrainsMono-latin-variable.woff2` | JetBrains Mono, variable weight 100 to 800, Latin subset | `@fontsource-variable/jetbrains-mono` (npm), file `latin-wght-normal.woff2`, unmodified | SIL OFL 1.1, `JetBrainsMono-OFL.txt` |

Both are served by the instance itself (see `docs/adr/0011` and `docs/adr/0017`):
no font is ever requested from another host.
