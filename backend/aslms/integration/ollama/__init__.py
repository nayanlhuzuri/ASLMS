"""The local Case Assistant model served by Ollama (design `assistant-ollama`, decisions 1, 11 and 12): the only package
where an Ollama HTTP call is made. Reached over HTTP with `httpx` at `ASSISTANT_OLLAMA_URL`, on the ASLMS host or a
server the Government controls. No model, model runtime or model library runs inside ASLMS's processes
(`no_local_model`), no cloud model (`no_cloud_model`), and no API key exists. Imports only the standard library, `httpx`
and `aslms`; only `services/assistant_ollama.py`, `services/service_checks.py`, `cli/assistant.py` and (design
`research-index`, decision 6) `services/research_embed.py`, `services/research_search.py` and `cli/research.py`
import it."""

from __future__ import annotations

from aslms.integration.ollama.client import (
    LOCAL_MIN_BYTES,
    MIN_VERSION,
    EmbedReply,
    ModelState,
    OllamaClient,
    OllamaReply,
    cloud_host,
    expires_label,
    model_name_ok,
    parse_embed,
    parse_version,
    too_long,
    url_problem,
)

__all__ = [
    "EmbedReply",
    "LOCAL_MIN_BYTES",
    "MIN_VERSION",
    "ModelState",
    "OllamaClient",
    "OllamaReply",
    "cloud_host",
    "expires_label",
    "model_name_ok",
    "parse_embed",
    "parse_version",
    "too_long",
    "url_problem",
]
