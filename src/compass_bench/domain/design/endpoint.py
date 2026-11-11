"""How a model's endpoint is reached and routed: part of the configuration a position belongs to."""

from pydantic import PositiveFloat, PositiveInt

from compass_bench.domain.value import Value


class EndpointSettings(Value):
    """How to reach an OpenRouter endpoint and route its requests across OpenRouter's upstream providers.

    The settings carry no id: every mapping that holds them is keyed by EndpointId. `quantizations` lists the
    precisions a host may serve at, such as `bf16` or `fp8`; empty allows any. OpenRouter filters hosts by it and
    does not report the precision served, so it is recorded as the filter sent."""

    base_url: str
    api_key_env: str
    max_concurrency: PositiveInt
    timeout_seconds: PositiveFloat
    provider_order: tuple[str, ...]
    allow_fallbacks: bool
    require_parameters: bool
    quantizations: tuple[str, ...]
