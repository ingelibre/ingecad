"""Standards-based IngeCAD MCP server: stdio or authenticated loopback HTTP."""
import argparse
import base64
import hmac
import os

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from bridge_client import request, sessions

mcp = FastMCP("IngeCAD", instructions="Control a local IngeCAD window. Call list_sessions first and use session_id explicitly. Coordinates use drawing units; paper sizes are mm. Check status/revision before mutations. Tool errors and timeouts are not proof that a mutation did not occur. No engineering sizes are inferred.", host="127.0.0.1")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
DELETE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


@mcp.tool(annotations=READ)
def list_sessions() -> list[dict]:
    """List live IngeCAD windows with document paths and session identifiers."""
    return sessions()


@mcp.tool(annotations=READ)
async def get_status(session_id: str | None = None) -> dict:
    """Read document revision, units, active space, history and layouts."""
    return await request("status", session_id=session_id)


@mcp.tool(annotations=READ)
async def get_drawing_tables(session_id: str | None = None) -> dict:
    """Read drawing layers, text styles, dimension styles and current style names before creating or editing entities."""
    return await request("get_drawing_tables", session_id=session_id)


@mcp.tool(annotations=WRITE)
async def open_drawing(path: str, session_id: str | None = None) -> dict:
    """Open an existing absolute DXF/DWG path in a NEW IngeCAD window and return its session_id. Leaves the original window intact. Parsing is synchronous and may temporarily block the GUI on large files; errors return via MCP."""
    return await request("open_drawing", {"path": path}, session_id, timeout=120)


@mcp.tool(annotations=READ)
async def query_entities(session_id: str | None = None, space: str = "Model", type: str | None = None,
                         layer: str | None = None, limit: int = 100, offset: int = 0) -> dict:
    """Read entity handles and DXF attributes, with pagination and optional filters."""
    return await request("query_entities", {"space": space, "type": type, "layer": layer, "limit": limit, "offset": offset}, session_id)


@mcp.tool(annotations=WRITE)
async def create_layer(name: str, color: int = 7, session_id: str | None = None, expected_revision: int | None = None) -> dict:
    """Create an undoable drawing layer. color is AutoCAD ACI 1..255."""
    return await request("create_layer", {"name": name, "color": color, "expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=WRITE)
async def create_text_style(name: str, font: str = "tahoma.ttf", session_id: str | None = None, expected_revision: int | None = None) -> dict:
    """Create an undoable text style referencing an installed TTF filename. Tahoma supports Thai on this Windows installation."""
    return await request("create_text_style", {"name": name, "font": font, "expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=WRITE)
async def create_dimension_style(name: str, text_style: str, text_height: float, arrow_size: float,
                                 measurement_factor: float = 1, session_id: str | None = None, expected_revision: int | None = None) -> dict:
    """Create an undoable dimension style. Heights use model units. measurement_factor=0.001 displays mm geometry as metres; it does not scale geometry."""
    return await request("create_dimension_style", {"name": name, "text_style": text_style, "text_height": text_height,
        "arrow_size": arrow_size, "measurement_factor": measurement_factor, "expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=WRITE)
async def create_entities(entities: list[dict], session_id: str | None = None, space: str = "Model", expected_revision: int | None = None) -> dict:
    """Create a single undoable batch (1..1000). Specs: LINE(start,end), CIRCLE(center,radius), LWPOLYLINE(points,closed), TEXT(position,text,height,rotation,style), DIMENSION(start,end,location,angle,text,dimstyle). Each accepts an existing layer (default 0). Points are [x,y] or [x,y,z]; sizes use drawing units."""
    return await request("create_entities", {"entities": entities, "space": space, "expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=WRITE)
async def update_entities(handles: list[str], attributes: dict, session_id: str | None = None, space: str = "Model", expected_revision: int | None = None) -> dict:
    """Undoable update of existing handles in one space. Supported attributes: layer,color,linetype,lineweight,text,height,rotation,radius,start,end,center,insert; must be valid for every target."""
    return await request("update_entities", {"handles": handles, "attributes": attributes, "space": space, "expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=DELETE)
async def delete_entities(handles: list[str], session_id: str | None = None, space: str = "Model", expected_revision: int | None = None) -> dict:
    """Delete explicit handles as one undoable operation. Rejects wrong-space handles."""
    return await request("delete_entities", {"handles": handles, "space": space, "expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=WRITE)
async def create_layout(name: str, project: str = "", title: str = "Plan", sheet: str = "S-01", width_mm: float = 420,
                        height_mm: float = 297, scale: float = 75, center: list[float] = [0, 0],
                        model_unit_mm: float | None = None, session_id: str | None = None, expected_revision: int | None = None) -> dict:
    """Create paper layout with border, title block and locked viewport. Default A3 landscape, 1:75. center is in model units. model_unit_mm is required for unitless/unsupported drawings; mm/cm/m drawing units are detected."""
    return await request("create_layout", {"name": name, "project": project, "title": title, "sheet": sheet,
        "width_mm": width_mm, "height_mm": height_mm, "scale": scale, "center": center,
        "model_unit_mm": model_unit_mm, "expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=WRITE)
async def switch_layout(name: str, session_id: str | None = None) -> dict:
    """Switch to Model or an existing paper layout."""
    return await request("switch_layout", {"name": name}, session_id)


@mcp.tool(annotations=WRITE)
async def undo(session_id: str | None = None, expected_revision: int | None = None) -> dict:
    """Undo the latest operation, including edits made manually by the user."""
    return await request("undo", {"expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=WRITE)
async def redo(session_id: str | None = None, expected_revision: int | None = None) -> dict:
    """Redo the latest undone operation."""
    return await request("redo", {"expected_revision": expected_revision}, session_id)


@mcp.tool(annotations=WRITE)
async def zoom_extents(session_id: str | None = None) -> dict:
    """Fit the current space into the IngeCAD viewport."""
    return await request("zoom_extents", session_id=session_id)


@mcp.tool(annotations=READ)
async def screenshot(session_id: str | None = None) -> Image:
    """Return a PNG of the CAD viewport as native MCP image content."""
    result = await request("screenshot", session_id=session_id)
    return Image(data=base64.b64decode(result["result"]["png_base64"]), format="png")


@mcp.tool(annotations=DELETE)
async def save_drawing(path: str, overwrite: bool = False, session_id: str | None = None, expected_revision: int | None = None) -> dict:
    """Save to an absolute .dxf/.dwg path. Existing output requires overwrite=true. Returns converter warnings; DWG fidelity must be checked. This updates the document save path."""
    return await request("save", {"path": path, "overwrite": overwrite, "expected_revision": expected_revision}, session_id, timeout=120)


@mcp.tool(annotations=DELETE)
async def export_pdf(path: str, layout: str, overwrite: bool = False, session_id: str | None = None) -> dict:
    """Export an existing paper layout as vector PDF at its exact sheet size. Requires an absolute path."""
    return await request("export_pdf", {"path": path, "layout": layout, "overwrite": overwrite}, session_id, timeout=120)


class BearerAuth:
    """Authenticate all HTTP routes; stdio relies on the local client process boundary."""
    def __init__(self, app, token):
        self.app, self.expected = app, ("Bearer " + token).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            supplied = dict(scope.get("headers", [])).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=4765)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        token = os.environ.get("INGECAD_MCP_TOKEN", "")
        if len(token) < 32:
            parser.error("HTTP requires INGECAD_MCP_TOKEN with at least 32 characters")
        import uvicorn
        uvicorn.run(BearerAuth(mcp.streamable_http_app(), token), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
