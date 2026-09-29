# HELM native import fixture

`mmlu-philosophy-gpt2/` is a byte-for-byte copy of the HELM run directory in
`every_eval_ever/tests/data/helm/mmlu-subject=philosophy,method=multiple_choice_joint,model=openai_gpt2`
at EEE revision `1eb9d39aed34505e15db637153de72318bd946d4`.

Its original execution environment and upstream HELM revision are unknown. The
fixture supports tests of native artifact reading and MAGNET materialization,
but does not prove fresh HELM execution or establish a supported HELM pin.
The Phase 1 test derives an incomplete copy by omitting
`per_instance_stats.json`; this is an explicit incomplete artifact experiment,
not an original native output.
