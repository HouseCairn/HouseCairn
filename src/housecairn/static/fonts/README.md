# Fonts (self-hosted)

Both families are variable fonts under the SIL Open Font License 1.1, served by the
instance itself: no font is ever requested from another host (`docs/adr/0011`,
`docs/adr/0017`). The files are the Latin subset (English and French) as built by
the Fontsource project, unmodified.

| File | Family | Source file | SHA-256 | Licence |
| --- | --- | --- | --- | --- |
| `Manrope-latin-variable.woff2` | Manrope, weight 200 to 800 | Fontsource `manrope:vf`, `latin-wght-normal.woff2` | `a30ddcd349703aff7464c34bef3fffdff405ee50c113440d7c8693c02d210972` | `Manrope-OFL.txt` |
| `JetBrainsMono-latin-variable.woff2` | JetBrains Mono, weight 100 to 800 | Fontsource `jetbrains-mono:vf`, `latin-wght-normal.woff2` | `18be452724bfdc236c074ca94a249a7f41a86752c7d04ab258ce9ed5651f6a7e` | `JetBrainsMono-OFL.txt` |

The test `test_fonts_match_their_recorded_hash` fails if a file changes without
this table being updated.
