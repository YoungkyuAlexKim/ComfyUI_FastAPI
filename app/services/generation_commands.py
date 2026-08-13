"""Provider-neutral generation commands and legacy web request adapter.

The current web API still sends ``workflow_id``.  This module turns that
legacy shape into a capability command, resolves the command through one
authoritative registry, and only then emits the payload consumed by the
existing generation processor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
import ipaddress
import os
import uuid

from ..workflow_configs import WORKFLOW_CONFIGS


@dataclass(frozen=True)
class GenerationContext:
    principal_id: str
    source: str
    client_ip: str
    client_ip_source: str = "socket"
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    idempotency_key: str = field(default_factory=lambda: f"web-{uuid.uuid4().hex}")


@dataclass(frozen=True)
class GenerationCommand:
    capability: str
    variant: str
    parameters: Mapping[str, Any]
    context: GenerationContext
    request_version: int = 1


@dataclass(frozen=True)
class ResolvedGenerationCommand:
    command: GenerationCommand
    workflow_id: str
    provider: str
    model: str | None
    payload: dict[str, Any]


class CapabilityDispatcher:
    """Maps stable public intent to replaceable internal workflows."""

    def __init__(self, routes: Mapping[tuple[str, str], str]):
        self._routes = dict(routes)
        self._legacy_routes = {workflow_id: route for route, workflow_id in self._routes.items()}
        if len(self._legacy_routes) != len(self._routes):
            raise ValueError("Each workflow must have exactly one capability route")
        self._validate_routes()

    def _validate_routes(self) -> None:
        for (capability, _variant), workflow_id in self._routes.items():
            config = WORKFLOW_CONFIGS.get(workflow_id)
            if not isinstance(config, dict):
                raise ValueError(f"Unknown workflow in capability registry: {workflow_id}")
            configured_capability = str(config.get("capability") or "").strip()
            if configured_capability != capability:
                raise ValueError(
                    f"Capability mismatch for {workflow_id}: "
                    f"registry={capability}, config={configured_capability}"
                )

    def route_for_legacy_workflow(self, workflow_id: str) -> tuple[str, str]:
        route = self._legacy_routes.get(str(workflow_id or "").strip())
        if route is None:
            raise ValueError(f"Unsupported workflow: {workflow_id}")
        return route

    def resolve(self, command: GenerationCommand) -> ResolvedGenerationCommand:
        route = (command.capability, command.variant)
        workflow_id = self._routes.get(route)
        if not workflow_id:
            raise ValueError(
                f"Unsupported capability variant: {command.capability}/{command.variant}"
            )

        config = WORKFLOW_CONFIGS[workflow_id]
        provider = str(config.get("provider") or "comfyui").strip().lower()
        provider_config = config.get("openrouter") if provider == "openrouter" else None
        default_model = (
            str(provider_config.get("model") or "").strip()
            if isinstance(provider_config, dict)
            else ""
        )
        requested_model = str(command.parameters.get("image_model") or "").strip()
        model = requested_model or default_model or None

        # Start with the legacy fields needed by the current processor, then
        # overwrite every routing/audit field with server-owned values.
        payload = dict(command.parameters)
        payload.update(
            {
                "workflow_id": workflow_id,
                "capability": command.capability,
                "capability_variant": command.variant,
                "request_version": command.request_version,
                "request_source": command.context.source,
                "principal_id": command.context.principal_id,
                "client_ip": command.context.client_ip,
                "client_ip_source": command.context.client_ip_source,
                "request_id": command.context.request_id,
                "idempotency_key": command.context.idempotency_key,
                "resolved_workflow_id": workflow_id,
                "resolved_provider": provider,
                "resolved_model": model,
            }
        )
        return ResolvedGenerationCommand(
            command=command,
            workflow_id=workflow_id,
            provider=provider,
            model=model,
            payload=payload,
        )


CAPABILITY_ROUTES: dict[tuple[str, str], str] = {
    ("create_image", "generate"): "NanoBanana",
    ("create_image", "edit"): "NanoBanana_Img2Img",
    ("create_game_ui_assets", "default"): "GameUI_Elements",
    ("create_character_sheet", "turnaround"): "NanoBanana_TurnaroundSheet",
    ("create_character_sheet", "expressions"): "NanoBanana_ExpressionPortraitSheet",
    ("create_storyboard", "default"): "NanoBanana_StoryboardCutboard",
    ("internal_image_preset", "chainsaw_juice_king"): "NanoBanana_ChainsawJuiceKingCharacter",
    ("remove_background", "default"): "RMBG2",
    ("separate_layers", "default"): "seethrough-basic",
    ("generate_music", "default"): "AceStep15XL",
}


DEFAULT_CAPABILITY_DISPATCHER = CapabilityDispatcher(CAPABILITY_ROUTES)


def command_from_legacy_web_request(
    request_payload: Mapping[str, Any],
    context: GenerationContext,
    *,
    dispatcher: CapabilityDispatcher = DEFAULT_CAPABILITY_DISPATCHER,
) -> GenerationCommand:
    """Adapt the existing ``GenerateRequest`` payload without changing its API."""

    parameters = dict(request_payload)
    workflow_id = str(parameters.pop("workflow_id", "") or "").strip()
    capability, variant = dispatcher.route_for_legacy_workflow(workflow_id)
    return GenerationCommand(
        capability=capability,
        variant=variant,
        parameters=parameters,
        context=context,
    )


def dispatch_legacy_web_request(
    request_payload: Mapping[str, Any],
    context: GenerationContext,
    *,
    dispatcher: CapabilityDispatcher = DEFAULT_CAPABILITY_DISPATCHER,
) -> ResolvedGenerationCommand:
    command = command_from_legacy_web_request(request_payload, context, dispatcher=dispatcher)
    return dispatcher.resolve(command)


def _parse_trusted_proxy_networks(raw_value: str | None) -> tuple[ipaddress._BaseNetwork, ...]:
    networks = []
    for raw_part in str(raw_value or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def resolve_client_ip(
    peer_ip: str | None,
    forwarded_for: str | None,
    trusted_proxy_cidrs: str | None,
) -> tuple[str, str]:
    """Resolve a client IP without trusting caller-controlled headers by default.

    When the immediate peer is trusted, the chain is walked from right to left
    and the closest untrusted hop is used.  This resists spoofed values prepended
    by a client while supporting one or more trusted reverse proxies.
    """

    try:
        peer = ipaddress.ip_address(str(peer_ip or "").strip())
    except ValueError:
        return (str(peer_ip or "unknown").strip() or "unknown", "socket")

    trusted_networks = _parse_trusted_proxy_networks(trusted_proxy_cidrs)

    def is_trusted(address: ipaddress._BaseAddress) -> bool:
        return any(address in network for network in trusted_networks)

    if not trusted_networks or not is_trusted(peer):
        return (str(peer), "socket")

    forwarded_addresses = []
    for raw_part in str(forwarded_for or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            forwarded_addresses.append(ipaddress.ip_address(part))
        except ValueError:
            # A malformed trusted-proxy header is safer to ignore entirely.
            return (str(peer), "socket")

    if not forwarded_addresses:
        return (str(peer), "socket")

    chain = forwarded_addresses + [peer]
    for address in reversed(chain):
        if not is_trusted(address):
            return (str(address), "forwarded")
    return (str(forwarded_addresses[0]), "forwarded")


def generation_context_from_http_request(request: Any, principal_id: str) -> GenerationContext:
    peer_ip = getattr(getattr(request, "client", None), "host", None)
    forwarded_for = None
    try:
        forwarded_for = request.headers.get("x-forwarded-for")
    except Exception:
        pass
    client_ip, client_ip_source = resolve_client_ip(
        peer_ip,
        forwarded_for,
        os.getenv("TRUSTED_PROXY_CIDRS"),
    )
    try:
        request_id = str(getattr(request.state, "request_id", "") or "").strip()
    except Exception:
        request_id = ""
    if not request_id:
        request_id = uuid.uuid4().hex

    try:
        supplied_key = str(request.headers.get("idempotency-key") or "").strip()
    except Exception:
        supplied_key = ""
    idempotency_key = supplied_key[:128] if len(supplied_key) >= 8 else f"web-{uuid.uuid4().hex}"

    return GenerationContext(
        principal_id=principal_id,
        source="web",
        client_ip=client_ip,
        client_ip_source=client_ip_source,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )
