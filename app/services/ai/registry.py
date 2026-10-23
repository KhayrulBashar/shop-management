from collections.abc import Callable
from typing import Any
from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    name: str
    type: str  # "string", "integer", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None
    items: dict[str, Any] | None = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: list[ToolParameter]
    is_mutation: bool = False  # False = Read-only (auto-execute); True = Requires explicit user preview & confirmation
    require_admin: bool = False
    
    # Non-serialized execution hooks
    handler: Any = Field(default=None, exclude=True)
    preview_generator: Any = Field(default=None, exclude=True)

    def to_json_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required_fields: list[str] = []

        for p in self.parameters:
            prop: dict[str, Any] = {
                "type": p.type,
                "description": p.description,
            }
            if p.enum:
                prop["enum"] = p.enum
            if p.items:
                prop["items"] = p.items
            properties[p.name] = prop

            if p.required:
                required_fields.append(p.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required_fields,
            },
        }

    def to_gemini_declaration(self) -> dict[str, Any]:
        schema = self.to_json_schema()
        return {
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["parameters"],
        }


class ToolRegistry:
    """
    Authoritative registry of typed, validated application capabilities.
    Only explicitly registered tools can be invoked by the AI agent.
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def get_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_read_only_tools(self) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if not t.is_mutation]

    def get_mutation_tools(self) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if t.is_mutation]

    def to_json_schemas(self) -> list[dict[str, Any]]:
        return [t.to_json_schema() for t in self._tools.values()]

    def to_prompt_catalog(self) -> str:
        """
        Formats a human-readable text catalog of all tools with parameters,
        used for LLM system prompting or fallback parsing.
        """
        lines = []
        for t in self._tools.values():
            action_type = "MUTATION (Requires User Confirmation)" if t.is_mutation else "READ-ONLY (Direct)"
            lines.append(f"### Tool: `{t.name}` [{action_type}]")
            lines.append(f"Description: {t.description}")
            if t.parameters:
                lines.append("Parameters:")
                for p in t.parameters:
                    req_label = "REQUIRED" if p.required else "OPTIONAL"
                    enum_label = f", Options: {p.enum}" if p.enum else ""
                    lines.append(f"  - `{p.name}` ({p.type}, {req_label}{enum_label}): {p.description}")
            else:
                lines.append("Parameters: None")
            lines.append("")
        return "\n".join(lines)


# Global singleton instance
tool_registry = ToolRegistry()
