# Idea-family fixture: byte copies of Research's results

Source: `research/idea-family` at `a84bd641cc93efae5cee1a91c8d3f9f2241168a2`,
directory `handoff/research-20261107/evidence/idea-family/`. Copied with `git show <commit>:<path>`;
each copy's git blob id equals the source blob id (checked with `git hash-object`).

Used only by the idea-board tests (`tests/test_ideas.py`, `tests/ideas.test.mjs`). The demo page reads
Research's own directory through `GET /api/ideas` (`--ideas`, default
`handoff/research-20261107/evidence/idea-family`), never this copy.

| File | sha256 | Blob vs source |
|---|---|---|
| `dev_example/registration.json` | `7fa1f8953d5d5c5819653a1e5379faced745494d48a720013aad494efb68c5f4` | identical |
| `dev_example/results.json` | `3a65f95e3b8d492715abbfff10a6da872b16c42b0ec9466796dcd8f724bec72d` | identical |
| `synthetic_gamma030/registration.json` | `d2c15fa8cbf1f60b8626def75d23486eff5a64e3a964365fa83353bd94098013` | identical |
| `synthetic_gamma030/results.json` | `4cb627276c2e69c3c6b271db5997f0a481711b06293abc86b34ae06252517b46` | identical |
| `synthetic_gamma030/scoreboard.json` | `a91692c91578aadb32ccad2a2d6b2c41a20d818b0765412bc98afa78701954cc` | identical |
| `synthetic_gamma030/truth.json` | `a5df9a3daae399b736e9c10f7f8581aa90927214e1fa8dfd253190137796d32f` | identical |
| `synthetic_gamma0/registration.json` | `f7d86185c6086372dd736ef41737e4c53a413e6935809e89356b64022385608b` | identical |
| `synthetic_gamma0/results.json` | `66df5234d3c68cfa2f5f959e1f4c6f9d9487b3503514c9aed643ddc8d40fba22` | identical |
| `synthetic_gamma0/scoreboard.json` | `1ca4cae4a9dccbacb154f7562a33c59e8c76a11404ad76b9330a3ba39d7aa8dd` | identical |
| `synthetic_gamma0/truth.json` | `9ec987cc421085b514e63dd83159e2d08d74962ad853c1e974e8de6cffaecedb` | identical |
