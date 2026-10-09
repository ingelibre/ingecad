"""Export the native AI tool schemas from the actual MCP server declarations."""
import json
from pathlib import Path
from server import mcp

excluded = {"list_sessions", "screenshot", "open_drawing"}
point = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}
attributes = {"layer": {"type":"string"}, "color": {"type":"integer", "minimum":0,"maximum":256},
    "linetype":{"type":"string"}, "lineweight":{"type":"integer"}, "text":{"type":"string"},
    "height":{"type":"number","exclusiveMinimum":0}, "rotation":{"type":"number"},
    "radius":{"type":"number","exclusiveMinimum":0}, **{k:point for k in ("start","end","center","insert")}}
entity = {"type":"object", "required":["type"], "additionalProperties":False, "properties":{
    "type":{"type":"string","enum":["LINE","CIRCLE","LWPOLYLINE","TEXT","DIMENSION"]},
    **{k:v for k,v in attributes.items() if k not in {"color","linetype","lineweight","insert"}},
    "points":{"type":"array","items":point,"minItems":2}, "closed":{"type":"boolean"},
    "position":point,"location":point,"angle":{"type":"number"},"style":{"type":"string"},"dimstyle":{"type":"string"}}}
catalog = []
for tool in mcp._tool_manager.list_tools():
    if tool.name in excluded:
        continue
    parameters = json.loads(json.dumps(tool.parameters))
    parameters["properties"].pop("session_id", None)
    parameters["required"] = [k for k in parameters.get("required", []) if k != "session_id"]
    # Explicit properties avoid empty-object function schemas rejected by some providers,
    # and describe the native Bridge's supported CAD entity/attribute contract to the model.
    if tool.name == "create_entities":
        parameters["properties"]["entities"] = {"type":"array","items":entity,"minItems":1,"maxItems":1000}
    if tool.name == "update_entities":
        parameters["properties"]["attributes"] = {"type":"object","properties":attributes,"additionalProperties":False,"minProperties":1}
    catalog.append({"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": parameters}})
path = Path(__file__).resolve().parent/"plugin"/"tools.json"
path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Exported {len(catalog)} native AI tool schemas")
