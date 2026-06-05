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
    loadable: bool = False

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "navSlot": self.nav_slot,
            "enabled": self.enabled,
            "loadable": self.loadable,
        }


BUILTIN_PLUGINS = (
    PluginDefinition(
        id="kanban",
        name="Kanban",
        description="工作区级任务看板",
        icon="layout-dashboard",
        nav_slot="sidebar",
    ),
    PluginDefinition(
        id="project-docs",
        name="项目文档",
        description="工作区级文档编辑与模型读写",
        icon="file-text",
        nav_slot="sidebar",
        loadable=True,
    ),
)


def list_builtin_plugins() -> list[dict[str, object]]:
    return [plugin.to_payload() for plugin in BUILTIN_PLUGINS]


def get_builtin_plugin(plugin_id: str) -> PluginDefinition | None:
    normalized = plugin_id.strip()
    return next((plugin for plugin in BUILTIN_PLUGINS if plugin.id == normalized), None)
