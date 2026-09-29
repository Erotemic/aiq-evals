# OLMo Eval native fixtures

Captured at OLMo Eval `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`; see
`docs/planning/phase1-evidence.md` for commands and checksums.

- `generation/`: mock-provider `aiq_p1_local` scored generation.
- `tool/`: local HTTP LiteLLM/OpenAI Agents `aiq_p1_tool` run calling `double`.
- `failure/`: forced `HardFailureRateExceeded` after metrics were written.
- `multi/`: `aiq_p1_multi` suite expanded to two tasks (files exactly as written).

`generation/` and `tool/` were originally committed with the native
`<task>[_<hash6>]` prefix dropped from the prediction/request filenames. They
were renamed to the unhashed native form `<task>-predictions.jsonl` (content and
SHA256 unchanged) so that native import, which discovers files by that suffix,
reads them. The original 6-character task hashes were not preserved and are not
reconstructed.

`expected-normalized.json` holds engine-free regression goldens; regenerate with
`python dev/regenerate_native_regressions.py olmo` and review any diff.
