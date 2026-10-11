# Inference comparison

Eight fixed synthetic GitHub cases test easy documentation, easy tests, medium bugs,
hard concurrency, assigned issues, claim comments, inactive repositories and missing
guides. Both models get the same data and tools. Fixture availability is not a live
GitHub recommendation. Passing includes returning no match for ineligible candidates.
These checks measure difficulty and availability correctness, not subjective ranking
quality or live GitHub latency. Existing tests separately cover fresh availability checks.

Run from the repository root with the development environment:

```sh
.venv-runtime/bin/python evaluations/run.py --provider hackathon-chat --base-url https://ws.akamai-workshops.com/v1 --model hackathon-chat --env-file .env --output .local/evaluations/hackathon-chat.json
```

For GPT-OSS, configure its key privately as GPT_OSS_API_KEY, then use the same command
with `--provider gpt-oss --base-url https://YOUR_ENDPOINT/v1 --model YOUR_MODEL_ID
--key-env GPT_OSS_API_KEY`. The output contains pass/fail, error categories, latency,
model turns, verification steps and result count, without keys or provider error text.
Use `--case easy_docs` for a smoke test. Run each endpoint sequentially and repeat
trials; rate limits and load affect latency. Compare matching case IDs and include
failures, not only successful runs. There is no GPT-OSS result until a real endpoint
is configured. Don't interpret a simulated transport as a measured model comparison.
