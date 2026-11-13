"""Operator-only registry context kept separate from user configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ImageInventory:
    registry_name: str
    repository: str
    available_tags: frozenset[str]
    workload_image_tags: tuple[tuple[str, str], ...]
    orchestrator_image: str
    result_uploader_image: str

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], registry_name: str
    ) -> "ImageInventory":
        if not isinstance(value, Mapping):
            raise ValueError("image inventory must be an object")
        inventory_registry_name = value.get("registryName")
        if inventory_registry_name != registry_name:
            raise ValueError("image inventory registryName does not match selection")
        repository = value.get("repository")
        available_tags = value.get("availableTags")
        workload_tags = value.get("workloadImageTags")
        orchestrator_image = value.get("orchestratorImage")
        result_uploader_image = value.get("resultUploaderImage")
        if not isinstance(repository, str) or not repository:
            raise ValueError("image inventory repository is required")
        if not isinstance(available_tags, list) or any(
            not isinstance(tag, str) or not tag for tag in available_tags
        ):
            raise ValueError("image inventory availableTags must be a string list")
        if not isinstance(workload_tags, Mapping) or any(
            not isinstance(role, str) or not role or not isinstance(tag, str) or not tag
            for role, tag in workload_tags.items()
        ):
            raise ValueError("image inventory workloadImageTags must map roles to tags")
        if not isinstance(orchestrator_image, str) or not orchestrator_image:
            raise ValueError("image inventory orchestratorImage is required")
        if not isinstance(result_uploader_image, str) or not result_uploader_image:
            raise ValueError("image inventory resultUploaderImage is required")
        return cls(
            registry_name=registry_name,
            repository=repository,
            available_tags=frozenset(available_tags),
            workload_image_tags=tuple(sorted(workload_tags.items())),
            orchestrator_image=orchestrator_image,
            result_uploader_image=result_uploader_image,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "registryName": self.registry_name,
            "repository": self.repository,
            "availableTags": sorted(self.available_tags),
            "workloadImageTags": dict(self.workload_image_tags),
            "orchestratorImage": self.orchestrator_image,
            "resultUploaderImage": self.result_uploader_image,
        }


@dataclass(frozen=True)
class RegistryContext:
    registry_name: str
    inventory: ImageInventory

    @classmethod
    def create(
        cls, registry_name: str, inventory: Mapping[str, Any]
    ) -> "RegistryContext":
        if not isinstance(registry_name, str) or not registry_name.strip():
            raise ValueError("operator registry name must not be empty")
        return cls(
            registry_name=registry_name,
            inventory=ImageInventory.from_mapping(inventory, registry_name),
        )


def registry_context_from_sources(
    cli_registry_name: str | None,
    environ: Mapping[str, str] | None = None,
) -> RegistryContext | None:
    env = os.environ if environ is None else environ
    env_registry_name = env.get("KRKNAI_OPERATOR_REGISTRY_NAME") or None
    cli_registry_name = cli_registry_name or None
    if (
        cli_registry_name
        and env_registry_name
        and cli_registry_name != env_registry_name
    ):
        raise ValueError(
            "--operator-registry-name does not match KRKNAI_OPERATOR_REGISTRY_NAME"
        )
    registry_name = cli_registry_name or env_registry_name
    raw_inventory = env.get("KRKNAI_IMAGE_INVENTORY") or None
    if registry_name is None:
        if raw_inventory is not None:
            raise ValueError(
                "managed image context requires KRKNAI_OPERATOR_REGISTRY_NAME"
            )
        return None
    if raw_inventory is None:
        raise ValueError("managed operator registry requires KRKNAI_IMAGE_INVENTORY")
    try:
        inventory = json.loads(raw_inventory)
    except json.JSONDecodeError as exc:
        raise ValueError("KRKNAI_IMAGE_INVENTORY must be valid JSON") from exc
    return RegistryContext.create(registry_name, inventory)


def registry_context_from_request(
    registry_name: str | None,
    inventory: Mapping[str, Any] | None,
) -> RegistryContext | None:
    registry_name = registry_name or None
    if registry_name is None:
        if inventory is not None:
            raise ValueError("image context requires registryName")
        return None
    if inventory is None:
        raise ValueError("registryName requires imageInventory")
    return RegistryContext.create(registry_name, inventory)
