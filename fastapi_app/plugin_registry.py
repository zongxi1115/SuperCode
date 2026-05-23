from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PluginDefinition:
    id: str
    name: str
    description: str
    icon: str
    nav_slot: str
    enabled: bool = True

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "navSlot": self.nav_slot,
            "enabled": self.enabled,
        }


BUILTIN_PLUGINS = (
    PluginDefinition(
        id="kanban",
        name="Kanban",
        description="工作区级任务看板",
        icon="layout-dashboard",
        nav_slot="sidebar",
    ),
)


def list_builtin_plugins() -> list[dict[str, object]]:
    return [plugin.to_payload() for plugin in BUILTIN_PLUGINS]
