# app/core/timeout_policy.py

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any

EndpointKey = tuple[str, str]


class TimeoutCategory(StrEnum):
    """Supported timeout groups for expensive CityRoute operations."""

    ROUTE = "route"
    ROUTE_COMPARE = "route_compare"
    MATRIX = "matrix"
    VRP_GREEDY = "vrp_greedy"
    VRP_COMPARE = "vrp_compare"
    VRP_ADVANCED = "vrp_advanced"
    DISPATCH = "dispatch"


@dataclass(frozen=True, slots=True)
class TimeoutRule:
    """
    Timeout configuration for one endpoint.

    `timeout_s=None` means the endpoint is recognized as protected but its
    timeout is explicitly disabled.
    """

    method: str
    path: str
    category: TimeoutCategory
    timeout_s: float | None

    def __post_init__(self) -> None:
        normalized_method = _normalize_method(self.method)
        normalized_path = _normalize_path(self.path)

        _validate_timeout(
            self.timeout_s,
            field_name=f"{normalized_method} {normalized_path}",
        )

        object.__setattr__(self, "method", normalized_method)
        object.__setattr__(self, "path", normalized_path)


@dataclass(frozen=True, slots=True)
class TimeoutDecision:
    """
    Result of resolving a request against the timeout policy.

    Attributes:
        protected:
            True when the endpoint is known to the reliability policy.

        enabled:
            True when a finite timeout is configured.

        timeout_s:
            Execution limit for the endpoint, or None when unprotected or
            explicitly disabled.
    """

    method: str
    path: str

    protected: bool
    enabled: bool

    category: TimeoutCategory | None
    timeout_s: float | None


@dataclass(frozen=True, slots=True)
class TimeoutPolicySnapshot:
    """Immutable policy snapshot for tests, metrics, and evidence probes."""

    rule_count: int
    enabled_rule_count: int
    disabled_rule_count: int
    rules: tuple[TimeoutRule, ...]


def _normalize_method(method: str) -> str:
    normalized = method.strip().upper()

    if not normalized:
        raise ValueError("HTTP method must not be empty")

    return normalized


def _normalize_path(path: str) -> str:
    """
    Normalize a request path for deterministic matching.

    Query strings are removed because timeout policy decisions are based on the
    endpoint contract, not on request parameter values.
    """

    normalized = path.strip().split("?", maxsplit=1)[0]

    if not normalized:
        normalized = "/"

    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    if len(normalized) > 1:
        normalized = normalized.rstrip("/")

    return normalized


def _validate_timeout(
    timeout_s: float | None,
    *,
    field_name: str,
) -> None:
    """
    Validate a timeout value.

    None explicitly disables timeout enforcement for a known endpoint.
    Enabled timeout values must be finite and strictly greater than zero.
    """

    if timeout_s is None:
        return

    if isinstance(timeout_s, bool):
        raise ValueError(
            f"Timeout for {field_name} must be a number or None, not bool"
        )

    if not isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError(
            f"Timeout for {field_name} must be finite and greater than 0"
        )


class TimeoutPolicy:
    """
    Immutable endpoint-specific timeout policy for CityRoute.

    Only explicitly registered expensive endpoints receive execution
    timeouts. Lightweight or unknown endpoints such as health, metrics,
    documentation, and OpenAPI remain unprotected unless a rule is added.

    Matching order:

        exact HTTP method + normalized path
            ↓
        wildcard method "*" + normalized path
            ↓
        unprotected endpoint

    The policy only decides the timeout. Actual enforcement belongs in
    `app/middleware/request_timeout.py`.
    """

    def __init__(
        self,
        rules: Mapping[EndpointKey, TimeoutRule],
    ) -> None:
        normalized_rules: dict[EndpointKey, TimeoutRule] = {}

        for supplied_key, rule in rules.items():
            if len(supplied_key) != 2:
                raise ValueError(
                    "Timeout rule keys must contain exactly "
                    "(method, path)"
                )

            supplied_method, supplied_path = supplied_key
            normalized_key = (
                _normalize_method(supplied_method),
                _normalize_path(supplied_path),
            )

            rule_key = (rule.method, rule.path)

            if normalized_key != rule_key:
                raise ValueError(
                    "Timeout rule key does not match the TimeoutRule: "
                    f"key={normalized_key!r}, rule={rule_key!r}"
                )

            if normalized_key in normalized_rules:
                raise ValueError(
                    f"Duplicate timeout rule for {normalized_key!r}"
                )

            normalized_rules[normalized_key] = rule

        self._rules: Mapping[EndpointKey, TimeoutRule] = MappingProxyType(
            normalized_rules
        )

    @classmethod
    def cityroute_defaults(
        cls,
        *,
        route_timeout_s: float | None = 5.0,
        route_compare_timeout_s: float | None = 10.0,
        matrix_timeout_s: float | None = 15.0,
        vrp_timeout_s: float | None = 20.0,
        advanced_vrp_timeout_s: float | None = 30.0,
        dispatch_timeout_s: float | None = 20.0,
    ) -> TimeoutPolicy:
        """
        Build the standard Phase 11 CityRoute timeout policy.

        These values should normally be provided from `app/config.py`.
        """

        rules = (
            TimeoutRule(
                method="GET",
                path="/route",
                category=TimeoutCategory.ROUTE,
                timeout_s=route_timeout_s,
            ),
            TimeoutRule(
                method="GET",
                path="/route/compare",
                category=TimeoutCategory.ROUTE_COMPARE,
                timeout_s=route_compare_timeout_s,
            ),
            TimeoutRule(
                method="POST",
                path="/matrix",
                category=TimeoutCategory.MATRIX,
                timeout_s=matrix_timeout_s,
            ),
            TimeoutRule(
                method="POST",
                path="/vrp/greedy",
                category=TimeoutCategory.VRP_GREEDY,
                timeout_s=vrp_timeout_s,
            ),
            TimeoutRule(
                method="POST",
                path="/vrp/compare",
                category=TimeoutCategory.VRP_COMPARE,
                timeout_s=vrp_timeout_s,
            ),
            TimeoutRule(
                method="POST",
                path="/vrp/compare/advanced",
                category=TimeoutCategory.VRP_ADVANCED,
                timeout_s=advanced_vrp_timeout_s,
            ),
            TimeoutRule(
                method="POST",
                path="/dispatch/compare",
                category=TimeoutCategory.DISPATCH,
                timeout_s=dispatch_timeout_s,
            ),
        )

        return cls(
            {
                (rule.method, rule.path): rule
                for rule in rules
            }
        )

    @classmethod
    def from_settings(cls, settings: Any) -> TimeoutPolicy:
        """
        Build the policy from the CityRoute settings object.

        Expected settings attributes:

            route_timeout_s
            route_compare_timeout_s
            matrix_timeout_s
            vrp_timeout_s
            advanced_vrp_timeout_s
            dispatch_timeout_s

        Using attribute access keeps this module independent from the concrete
        Pydantic settings class and avoids a circular import.
        """

        required_fields = (
            "route_timeout_s",
            "route_compare_timeout_s",
            "matrix_timeout_s",
            "vrp_timeout_s",
            "advanced_vrp_timeout_s",
            "dispatch_timeout_s",
        )

        missing_fields = [
            field_name
            for field_name in required_fields
            if not hasattr(settings, field_name)
        ]

        if missing_fields:
            joined = ", ".join(sorted(missing_fields))
            raise AttributeError(
                f"Settings object is missing timeout fields: {joined}"
            )

        return cls.cityroute_defaults(
            route_timeout_s=settings.route_timeout_s,
            route_compare_timeout_s=settings.route_compare_timeout_s,
            matrix_timeout_s=settings.matrix_timeout_s,
            vrp_timeout_s=settings.vrp_timeout_s,
            advanced_vrp_timeout_s=(
                settings.advanced_vrp_timeout_s
            ),
            dispatch_timeout_s=settings.dispatch_timeout_s,
        )

    def resolve(
        self,
        *,
        method: str,
        path: str,
    ) -> TimeoutDecision:
        """
        Resolve an HTTP request to a timeout decision.

        Unknown endpoints are deliberately left unprotected rather than being
        assigned a dangerous global timeout.
        """

        normalized_method = _normalize_method(method)
        normalized_path = _normalize_path(path)

        rule = self._rules.get(
            (normalized_method, normalized_path)
        )

        if rule is None:
            rule = self._rules.get(("*", normalized_path))

        if rule is None:
            return TimeoutDecision(
                method=normalized_method,
                path=normalized_path,
                protected=False,
                enabled=False,
                category=None,
                timeout_s=None,
            )

        return TimeoutDecision(
            method=normalized_method,
            path=normalized_path,
            protected=True,
            enabled=rule.timeout_s is not None,
            category=rule.category,
            timeout_s=rule.timeout_s,
        )

    def timeout_for_path(
        self,
        path: str,
        *,
        method: str = "GET",
    ) -> float | None:
        """
        Convenience method returning only the configured timeout.

        Returns None when the endpoint is unprotected or timeout enforcement is
        explicitly disabled for that endpoint.
        """

        return self.resolve(
            method=method,
            path=path,
        ).timeout_s

    def is_protected(
        self,
        *,
        method: str,
        path: str,
    ) -> bool:
        """Return whether an endpoint belongs to the timeout policy."""

        return self.resolve(
            method=method,
            path=path,
        ).protected

    def snapshot(self) -> TimeoutPolicySnapshot:
        """Return a deterministic immutable policy snapshot."""

        rules = tuple(
            sorted(
                self._rules.values(),
                key=lambda rule: (
                    rule.path,
                    rule.method,
                    rule.category.value,
                ),
            )
        )

        enabled_rule_count = sum(
            rule.timeout_s is not None
            for rule in rules
        )

        return TimeoutPolicySnapshot(
            rule_count=len(rules),
            enabled_rule_count=enabled_rule_count,
            disabled_rule_count=len(rules) - enabled_rule_count,
            rules=rules,
        )


__all__ = [
    "EndpointKey",
    "TimeoutCategory",
    "TimeoutDecision",
    "TimeoutPolicy",
    "TimeoutPolicySnapshot",
    "TimeoutRule",
]