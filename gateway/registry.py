"""Model registry: model metadata, pricing, capabilities, fallbacks."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelDef:
    id: str
    provider: str
    display_name: str = ""
    context_window: int = 0
    input_price_per_1k: float = 0.0
    output_price_per_1k: float = 0.0
    capabilities: list = field(default_factory=list)
    enabled: bool = True
    priority: int = 100
    fallbacks: list = field(default_factory=list)


class ModelRegistry:
    def __init__(self, models: list):
        # models: list of ModelConfig (duck-typed)
        self._models: dict[str, ModelDef] = {}
        for m in models:
            self._models[m.id] = ModelDef(
                id=m.id,
                provider=m.provider,
                display_name=m.display_name or m.id,
                context_window=m.context_window,
                input_price_per_1k=m.input_price_per_1k,
                output_price_per_1k=m.output_price_per_1k,
                capabilities=list(m.capabilities or []),
                enabled=m.enabled,
                priority=m.priority,
                fallbacks=list(m.fallbacks or []),
            )

    def get(self, model_id: str) -> ModelDef | None:
        return self._models.get(model_id)

    def list(self, enabled_only: bool = False) -> list[ModelDef]:
        models = self._models.values()
        if enabled_only:
            models = [m for m in models if m.enabled]
        return sorted(models, key=lambda m: (m.priority, m.id))

    def resolve(self, model_id: str) -> list[ModelDef]:
        """Ordered attempt list: the model itself (if enabled) then its
        fallbacks (enabled only, in listed order, deduplicated)."""
        seen: set[str] = set()
        ordered: list[ModelDef] = []
        primary = self._models.get(model_id)
        candidates = ([primary] if primary else []) + [
            self._models.get(f) for f in (primary.fallbacks if primary else [])
        ]
        for m in candidates:
            if m is None or not m.enabled or m.id in seen:
                continue
            seen.add(m.id)
            ordered.append(m)
        return ordered
