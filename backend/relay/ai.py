"""The two model calls the Showcase compares, each measured the same way.

Every call returns a ``Measured``: the answer, the provider's own token counts,
wall-clock latency of the HTTP round trip from this server, and cost computed
from the published price. Keys come from the environment (see ``env``) and never
leave the server.

Prices, checked 18 September 2026:

* Jev (TypeSafe) — $0.042 per million input tokens; output is not billed.
  https://docs.typesafe.ai/models
* Gemini 3.8 Flash — $0.75 per million input, $3.75 per million output, thinking
  tokens billed as output (standard tier, through 31 December 2026; doubles on
  1 January 2027). https://ai.google.dev/gemini-api/docs/pricing
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import httpx

from . import env

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
JEV_MODEL = "jev-latest"
GEMINI_MODEL = "gemini-3.8-flash"

PRICES = {
    # USD per million tokens
    "jev": {"input": 0.042, "output": 0.0, "source": "docs.typesafe.ai/models"},
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75, "source": "ai.google.dev/gemini-api/docs/pricing"},
}
TIMEOUT = httpx.Timeout(60.0, connect=10.0)

# One kept-alive connection pool per provider, as any production integration
# would hold. Without it every run pays a fresh TLS handshake, which is time
# spent on the setup of this demo rather than on either model.
_pools: dict[str, httpx.Client] = {}


def _pool(name: str) -> httpx.Client:
    if name not in _pools:
        _pools[name] = httpx.Client(timeout=TIMEOUT, http2=False)
    return _pools[name]


@dataclass
class Measured:
    provider: str
    model: str
    answer: Optional[str] = None
    probabilities: Optional[dict] = None       # Jev returns a distribution; an LLM does not
    confidence: Optional[float] = None
    # A Score's position on the scale, which can land between two levels. Kept
    # beside ``answer`` rather than replacing it: the nearest level is what the
    # interface shows, 2.7 is what it actually said.
    score: Optional[float] = None
    # A Noul's probability that the statement is true. Kept separate from
    # ``confidence``: a Noul returns no confidence value, and reading 0.5 as
    # "unsure" rather than "evens" is the mistake the docs warn about.
    noul: Optional[float] = None
    raw_text: Optional[str] = None             # what the LLM actually wrote, before parsing
    input_tokens: int = 0
    output_tokens: int = 0                     # visible answer tokens
    thinking_tokens: int = 0                   # billed as output, never shown
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    price: dict = field(default_factory=dict)
    request: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)   # use-case specifics: raw answers, parsed JSON, parts
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


def _cost(price: dict, input_tokens: int, billed_output: int) -> float:
    return (input_tokens * price["input"] + billed_output * price["output"]) / 1_000_000


def _fail(m: Measured, started: float, message: str) -> Measured:
    m.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    m.error = message
    return m


def jev_choice(state, question_id: str, question: dict, client: Optional[httpx.Client] = None) -> Measured:
    """One Choice question to Jev. ``question`` is the TypeSafe question object."""
    m = jev_ask(state, {question_id: question}, client)
    a = m.detail.get("answers", {}).get(question_id)
    if a:
        m.answer, m.probabilities, m.confidence = a.get("choice"), a.get("probabilities"), a.get("confidence")
    return m


def jev_score(state, question_id: str, question: dict, labels: Optional[list[str]] = None,
              client: Optional[httpx.Client] = None) -> Measured:
    """One Score question to Jev.

    A Score's levels are an ordered array, so the answer comes back as a
    position on that array — 0 to len-1, landing between levels when the
    probability is split — with a probability per level. This re-keys both onto
    the caller's own labels, because a service desk talks about a 1 to 5
    sentiment, not about level 0 of an array.
    """
    m = jev_ask(state, {question_id: question}, client)
    a = m.detail.get("answers", {}).get(question_id)
    if not a:
        return m
    names = labels or [str(i) for i in range(len(question.get("criteria", [])))]
    m.score = a.get("score")
    m.confidence = a.get("confidence")
    if m.score is not None:
        m.answer = names[min(range(len(names)), key=lambda i: abs(i - m.score))]
    m.probabilities = {
        names[int(level)]: p for level, p in (a.get("probabilities") or {}).items()
        if int(level) < len(names)
    }
    m.detail["legend"] = {names[int(k)]: v for k, v in (a.get("legend") or {}).items()
                          if int(k) < len(names)}
    return m


def jev_choices(state, questions: dict, client: Optional[httpx.Client] = None) -> Measured:
    """Several Choice questions over one state, in one request.

    The fan-out: asking about six candidates costs six questions but one round
    trip, and Jev evaluates them in parallel, so the sixth answer is nearly free
    in time. ``detail["choices"]`` holds each answer with its own distribution,
    for the caller to compose.
    """
    m = jev_ask(state, questions, client)
    answers = m.detail.get("answers", {})
    m.detail["choices"] = {
        qid: {"choice": a.get("choice"), "probabilities": a.get("probabilities") or {},
              "confidence": a.get("confidence")}
        for qid, a in answers.items() if a
    }
    return m


def jev_noul(state, question_id: str, question: dict, threshold: float = 0.5,
             client: Optional[httpx.Client] = None) -> Measured:
    """One Noul question to Jev: the probability that a statement is true.

    A Noul answers with a probability and nothing else — no confidence figure,
    because the probability already is the answer. Turning it into a yes or no
    is code's job, which is why ``threshold`` arrives as an argument from
    ``policy`` rather than being decided here.
    """
    m = jev_ask(state, {question_id: question}, client)
    a = m.detail.get("answers", {}).get(question_id)
    if not a:
        return m
    m.noul = a.get("noul")
    if m.noul is not None:
        m.answer = "yes" if m.noul >= threshold else "no"
        m.probabilities = {"yes": round(m.noul, 4), "no": round(1 - m.noul, 4)}
    return m


def jev_ask(state, questions: dict, client: Optional[httpx.Client] = None) -> Measured:
    """Several questions over one state, in one request: Jev evaluates them in
    parallel, so a second question costs tokens but barely any time. The raw
    answers land in ``detail["answers"]`` for the caller to compose."""
    body = {"model": JEV_MODEL, "state": state, "questions": questions}
    m = Measured(provider="TypeSafe", model=JEV_MODEL, price=PRICES["jev"], request=body)
    token = env.key("TYPESAFE_API_KEY")
    started = time.perf_counter()
    if not token:
        return _fail(m, started, "TYPESAFE_API_KEY is not set")
    try:
        r = (client or _pool("typesafe")).post(TYPESAFE_URL, headers={"Authorization": f"Bearer {token}"}, json=body)
        m.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        if r.status_code != 200:
            return _fail(m, started, f"TypeSafe answered {r.status_code}: {r.text[:200]}")
        data = r.json()
    except httpx.HTTPError as exc:
        return _fail(m, started, f"TypeSafe unreachable: {exc}")

    m.model = data.get("model", JEV_MODEL)
    m.detail["answers"] = data.get("answers", {})
    m.input_tokens = data.get("usage", {}).get("input_tokens", 0)
    m.output_tokens = data.get("usage", {}).get("output_tokens", 0)
    m.cost_usd = _cost(m.price, m.input_tokens, 0)
    return m


def gemini_json(system: str, user: str, schema: dict, answer_field: str,
                model: str = GEMINI_MODEL, client: Optional[httpx.Client] = None) -> Measured:
    """A prompt-and-parse call: instructions in, JSON constrained by ``schema`` out,
    with the model's default thinking — the way such calls are usually made."""
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema},
    }
    m = Measured(provider="Google", model=model, price=PRICES.get(model, PRICES[GEMINI_MODEL]), request=body)
    token = env.key("GOOGLE_API_KEY", "GOOGLE_AI_KEY", "GEMINI_API_KEY")
    started = time.perf_counter()
    if not token:
        return _fail(m, started, "GOOGLE_API_KEY is not set")
    try:
        r = (client or _pool("google")).post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": token}, json=body)
        m.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        data = r.json()
        if r.status_code != 200 or "error" in data:
            return _fail(m, started, f"Gemini answered {r.status_code}: {data.get('error', {}).get('message', r.text)[:200]}")
    except (httpx.HTTPError, ValueError) as exc:
        return _fail(m, started, f"Gemini unreachable: {exc}")

    usage = data.get("usageMetadata", {})
    m.model = data.get("modelVersion", model)
    m.input_tokens = usage.get("promptTokenCount", 0)
    m.output_tokens = usage.get("candidatesTokenCount", 0)
    m.thinking_tokens = usage.get("thoughtsTokenCount", 0)
    m.cost_usd = _cost(m.price, m.input_tokens, m.output_tokens + m.thinking_tokens)
    try:
        parts = data["candidates"][0]["content"]["parts"]
        m.raw_text = next(p["text"] for p in reversed(parts) if "text" in p and not p.get("thought"))
        m.detail["parsed"] = json.loads(m.raw_text)
        m.answer = m.detail["parsed"].get(answer_field)
    except (KeyError, IndexError, StopIteration, ValueError) as exc:
        m.error = f"could not read an answer from Gemini's reply: {exc}"
    return m
