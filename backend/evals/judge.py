"""The LLM judge: claude-sonnet-5, built in exactly one place.

Every metric in this suite that needs a model calls `judge()`. That is not tidiness,
it is a guard — see "the silent swap" below.

## The silent swap

deepeval autoloads a dotenv file from the *working directory*. Running this suite
from `backend/` means it picks up backend's, which supplies ANTHROPIC_API_KEY for
free — and also OPENAI_API_KEY, because that is what the application itself runs on.
deepeval's `initialize_model(None)` checks for an OpenAI key before anything else.

So a metric written as `GEval(name=..., criteria=...)`, with no `model=` argument,
does not fail. It quietly judges with GPT, bills the application's OpenAI key, and
reports a perfectly normal-looking score. Nothing in the output says which model
graded the run.

The rule that prevents it: **every LLM-backed metric passes `model=judge()`
explicitly.** `evals/metrics/judged.py` asserts this at construction rather than
trusting anyone to remember, and `README.md` names it as a greppable invariant.

## Why no temperature

claude-sonnet-5 removed `temperature`, `top_p` and `top_k` — sending one is a 400.
deepeval knows: it registers the model with `supports_temperature=False` and gates
the parameter behind that flag, so passing `temperature=0` here would be silently
dropped rather than fatal. Silently dropped is worse than fatal, because it would
leave this file *looking* like it had pinned determinism when it had not.

The consequence is real and shapes the metrics: **judge determinism cannot come from
a sampling parameter on this model.** It has to come from coarse rubrics and margin
between the score and the threshold. `judged.py` is written that way on purpose.

## Why max_tokens is raised

`AnthropicModel.DEFAULT_MAX_TOKENS` is 1024. GEval generates evaluation steps and
then a reasoned verdict as JSON; that can exceed 1024 on a long comparison. When it
does, the truncated JSON reaches deepeval's `trim_and_load_json` and surfaces as a
parse error that says nothing about token limits. 4096 is cheap insurance.
"""

from __future__ import annotations

import functools
import os

from deepeval.models import AnthropicModel

# The judge model. Sonnet rather than Opus because the questions put to it are
# narrow string comparisons, not reasoning problems — see judged.py, where each
# metric is one short semantic equivalence check on a pre-aligned pair.
JUDGE_MODEL = "claude-sonnet-5"

# Headroom for GEval's evaluation-steps and verdict JSON. See the module docstring.
JUDGE_MAX_TOKENS = 4096


@functools.lru_cache(maxsize=1)
def judge() -> AnthropicModel:
    """The judge, built once per process and reused.

    Cached because deepeval constructs metrics eagerly and a suite builds several;
    each `AnthropicModel()` otherwise opens its own client for no reason.

    Deliberately no `temperature=` argument — see the module docstring.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set, so the judge cannot be built. It is "
            "normally read out of backend's dotenv file by config/settings.py "
            "during django.setup(), which evals/conftest.py runs first — so seeing "
            "this usually means the key is missing from that file."
        )

    return AnthropicModel(
        model=JUDGE_MODEL,
        generation_kwargs={"max_tokens": JUDGE_MAX_TOKENS},
    )


def judge_name() -> str:
    """The judge's display name, for asserting a metric is actually using it."""
    return judge().get_model_name()
