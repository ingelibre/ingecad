# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The scenarios tools/qa_tour.py runs: one per feature of the release,
each done the way the user does it (see the tour's docstring)."""
from __future__ import annotations

import math

from qa_helpers import annotative_sheet, drive_modal, load_linetypes, red_pixels

CORPUS = "/home/sumaritux/Proyectos/externos/corpus-dwg"


def _close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def scenario_linetypes(t):
    """1.1/1.2 Tipos de línea: LINETYPE abre el administrador, Cargar...
    trae ACAD_ISO04W100, Actual la deja puesta y la línea nueva sale con
    trazos (Rafael no pudo poner ejes en la revisión 7)."""
    from views.linetype_dialog import LinetypeManagerDialog

    win = t.new_window()
    errors = []

    def inside(dialog):
        load_linetypes(dialog, "ACAD_ISO04W100")
        dialog.current_button.click()
        t.shot("manager", "LINETYPE: el administrador con ACAD_ISO04W100 cargado y actual",
               widget=dialog)
        dialog._ok()

    drive_modal(LinetypeManagerDialog, inside, errors)
    t.type("LINETYPE")
    t.wait(300)
    t.check(not errors, "el administrador se abrió y cargó el tipo", errors[:1])
    t.type("LINE")
    t.type("0,0")
    t.type("100,0")
    t.type("")
    line = win.document.modelspace().query("LINE")[-1]
    t.check(line.dxf.linetype == "ACAD_ISO04W100", "la línea nueva lleva el tipo actual",
            line.dxf.linetype)
    t.frame(-5, -20, 105, 20)
    t.shot("dashed", "La línea dibujada con el tipo de línea de eje (trazo-punto)")


def scenario_grip_shortens(t):
    """1.3 Un pinzamiento acorta una línea con REFENT (PER) encendido
    («no consigo menguar esto»)."""
    win = t.new_window()
    t.type("LINE")
    t.type("0,0")
    t.type("100,0")
    t.type("")
    t.frame(-10, -30, 110, 30)
    t.snaps("END", "PER", "MID")
    line = win.document.modelspace().query("LINE")[-1]
    t.click(50, 0)                       # select the line
    t.click(100, 0)                      # grab its end grip
    t.move(80, 0.4)
    t.move(60, 0.4)
    t.shot("dragging", "Arrastrando el pinzamiento del extremo hacia adentro")
    t.click(60, 0.4)
    t.check(abs(line.dxf.end.x - 60) < 1.0, "la línea quedó más corta",
            f"extremo en x={line.dxf.end.x:.3f}")
    t.esc()
    t.shot("shorter", "La línea acortada a ~60")


def scenario_tracking_distance(t):
    """2.1 Rastreo + distancia tecleada: pausa en el centro de un círculo,
    deslizar a la derecha, teclear 6 → el punto queda a 6 del centro."""
    win = t.new_window()
    tools = win.tools
    t.type("CIRCLE")
    t.type("50,50")
    t.type("10")
    t.frame(20, 20, 90, 80)
    t.snaps("CEN", "END")
    tools.otrack_on = True
    tools.polar_on = True
    t.type("LINE")
    t.move(50.6, 59.4)                    # over the circle
    t.move(50.3, 50.2)                    # the centre
    t.wait(900)                           # pause: acquire it
    t.move(57.0, 50.15)                   # slide right along the path
    t.wait(200)
    t.shot("path", "Rastreo desde el centro: la línea de alineación a 0°")
    t.type("6")
    t.check(_close(tools._recent_points[-1], (56.0, 50.0), 1e-6),
            "el punto tecleado mide 6 desde el centro", tools._recent_points[-1])
    t.esc()
    t.esc()


def scenario_assoc_dims(t):
    """6.3 Cotas asociativas: DIMLINEAR con clics en los extremos (REFENT
    Fin) de una pieza de 4 x 2 m; STRETCH de la pieza y la cota se vuelve a
    medir; deshacer la devuelve y sigue asociada."""
    from core import dimassoc

    win = t.new_window()
    t.type("RECTANG")
    t.type("0,0")
    t.type("4,2")
    t.frame(-1.5, -2.0, 7.5, 3.5)
    t.snaps("END")
    t.type("DIMLINEAR")
    t.click(0.03, 0.03)
    t.click(3.97, 0.03)
    t.snaps()
    t.click(2, -0.8)
    dim = win.document.modelspace().query("DIMENSION")[-1]
    t.check(dimassoc.of_dimension(dim) is not None, "la cota quedó asociada")
    t.shot("placed", "Cota de 4.00 puesta sobre los vértices del rectángulo")

    def stretch(dx):
        t.type("STRETCH")
        t.click(4.5, 2.5)                    # crossing, right to left
        t.click(3.5, -0.3)
        t.type("")
        t.type("0,0")
        t.type(f"{dx},0")

    stretch(1.5)
    t.check(abs(dim.get_measurement() - 5.5) < 1e-9, "la cota mide 5.50 tras STRETCH",
            dim.get_measurement())
    t.shot("stretched", "STRETCH del lado derecho 1.5 m: la cota dice 5.50")
    t.keys("Ctrl+Z")
    t.check(abs(dim.get_measurement() - 4) < 1e-9, "deshacer la devuelve a 4.00",
            dim.get_measurement())
    t.check(dimassoc.of_dimension(dim) is not None, "tras deshacer sigue asociada")
    stretch(0.5)
    t.check(abs(dim.get_measurement() - 4.5) < 1e-9, "y vuelve a seguir a la pieza (4.50)",
            dim.get_measurement())


def scenario_int_arcs(t):
    """#82 Intersección en arcos y círculos: el marcador INT aparece donde
    dos círculos se cortan."""
    win = t.new_window()
    t.type("CIRCLE")
    t.type("0,0")
    t.type("5")
    t.type("CIRCLE")
    t.type("6,0")
    t.type("5")
    t.frame(-8, -8, 14, 8)
    t.snaps("INT")
    t.type("LINE")
    t.move(3.25, 4.15)
    hit = win.tools.snap_hit
    t.check(hit is not None and hit.kind == "INT" and _close((hit.x, hit.y), (3, 4), 1e-9),
            "INT en (3, 4)", hit)
    t.shot("marker", "El marcador de intersección sobre el cruce de los dos círculos")
    t.esc()


def scenario_boundary_curves(t):
    """#83 BOUNDARY con un lado curvo: la polilínea sigue el arco exacto,
    sin huecos al acercarse."""
    win = t.new_window()
    for cmd in (("LINE", "0,0", "10,0", "10,5", ""), ("LINE", "0,5", "0,0", ""),
                ("ARC", "C", "5,5", "10,5", "0,5")):
        for text in cmd:
            t.type(text)
    t.frame(-2, -2, 12, 12)
    t.type("BOUNDARY")
    t.click(5, 2)
    t.type("")
    poly = win.document.modelspace().query("LWPOLYLINE")[-1]
    rows = list(poly.get_points("xyb"))
    t.check(len(rows) == 4 and sum(1 for r in rows if abs(r[2]) > 1e-9) == 1,
            "4 vértices y un tramo curvo", rows)
    t.frame(8.3, 7.6, 9.3, 8.6)          # zoom onto the arc
    t.shot("zoomed", "Muy de cerca sobre el arco: el contorno (BOUNDARY) coincide con el arco")


def scenario_zoom_window_snap(t):
    """#80 ZOOM Ventana con REFENT: las dos esquinas enganchan los extremos
    de una línea."""
    win = t.new_window()
    t.type("LINE")
    t.type("100,200")
    t.type("160,230")
    t.type("")
    t.frame(0, 0, 300, 300)
    t.snaps("END")
    t.type("ZOOM")
    t.type("W")
    t.check(win.tools.tool is not None and win.tools.tool.name == "ZOOMWINDOW",
            "ZOOM W pide la primera esquina")
    t.click(100.8, 199.4)
    t.move(150, 225)
    t.shot("rubber", "Primera esquina enganchada; el rectángulo sigue al cursor")
    t.click(159.3, 230.6)
    x0, y0, x1, y1 = win.viewport._view_world_rect()
    t.check(_close(((x0 + x1) / 2, (y0 + y1) / 2), (130, 215), 1e-6),
            "la vista quedó centrada en la línea", ((x0 + x1) / 2, (y0 + y1) / 2))
    t.shot("zoomed", "La vista encuadra exactamente la línea")


def scenario_tabs(t):
    """6.2 Pestañas: dos planos reales abiertos, ida y vuelta sin regenerar,
    Ctrl+Tab cambia, la × cierra."""
    win = t.new_window()
    a = f"{CORPUS}/0306_E-1 Y P-2 CIMENTACION FINAL YANAQUIHUA.dwg"
    b = f"{CORPUS}/1640_example_2004.dwg"
    t.open(a)
    t.open(b)
    names = [s.document.name for s in win.document_sessions()]
    t.check(len(names) == 2, "dos pestañas", names)
    t.shot("second", "Dos planos abiertos en pestañas; el segundo a la vista")
    t.keys("Ctrl+Tab")
    t.check(win.document.name == names[0], "Ctrl+Tab vuelve al primero", win.document.name)
    t.check(win._regen_worker is None, "volver no regeneró el plano")
    t.shot("first", "Ctrl+Tab: el primer plano, con sus capas y su vista")


def _annotative_sheet(t):
    """Rafael's case: annotative dimensions, a 1:1 and a 2:1 viewport."""
    import tempfile
    from pathlib import Path

    document, _dims = annotative_sheet()
    path = Path(tempfile.mkdtemp(dir=Path.home() / ".cache")) / "anotativo.dxf"
    document.doc.saveas(path)
    return path


def scenario_annotative_viewports(t):
    """5.x Escala anotativa en ventanas gráficas: la misma cota mide igual
    en papel en la ventana 1:1 y en la 2:1 («lo único que falla»)."""
    win = t.new_window()
    t.open(_annotative_sheet(t))
    win.switch_layout("Layout1")
    t.settle()
    t.frame(0, 30, 300, 170)
    t.shot("sheet", "Lámina con ventana 1:1 (izq.) y 2:1 (der.): textos de cota del mismo tamaño")
    a, b = red_pixels(win.document)
    t.check(a > 200 and abs(b / a - 1) < 0.12, "texto rojo igual en las dos ventanas",
            f"{a} / {b}")


def scenario_save_dwg_annotative_assoc(t):
    """5.5 + 6.3 Guardar como DWG y reabrir: las escalas anotativas y las
    cotas asociativas siguen ahí (LibreDWG del vendor)."""
    import tempfile
    from pathlib import Path

    from core import annotative as A
    from core import dimassoc

    win = t.new_window()
    t.open(_annotative_sheet(t))
    t.type("LINE")
    t.type("40,-40")
    t.type("70,-40")
    t.type("")
    t.frame(30, -50, 80, -20)
    t.snaps("END")
    t.type("DIMLINEAR")
    t.click(40.1, -39.9)
    t.click(69.9, -39.9)
    t.snaps()
    t.click(55, -45)
    out = Path(tempfile.mkdtemp(dir=Path.home() / ".cache")) / "guardado.dwg"
    _engine, warnings = win.document.save_as(out)
    t.check(not warnings, "Guardar como DWG sin avisos", warnings)
    t.open(out)
    doc = win.document
    dims = doc.doc.modelspace().query("DIMENSION")
    reps = [len(A.representations(d)) for d in dims if A.is_annotative(d)]
    # the four of the sheet carry 1:1 and 2:1; the one just drawn only the
    # current scale, as AutoCAD creates it
    t.check(sorted(reps) == [1, 2, 2, 2, 2], "las cotas anotativas traen sus escalas",
            reps)
    t.check(len(dimassoc.associations(doc)) == 1, "la cota asociativa volvió atada",
            len(dimassoc.associations(doc)))
    win.switch_layout("Layout1")
    t.settle()
    t.frame(0, 30, 300, 170)
    t.shot("reopened", "El DWG reabierto en otra pestaña: la lámina igual que antes de guardar")


def scenario_extend_arc(t):
    """4.1 EXTEND alarga un arco hasta una línea (antes sólo LINE/PLINE).
    Modo Estándar (el de fábrica)."""
    from core import trimmode

    trimmode.set_trimextendmode(0)       # the mode is remembered, as AutoCAD's
    win = t.new_window()
    t.type("LINE")
    t.type("-6,-1")
    t.type("6,-1")
    t.type("")
    t.type("ARC")
    t.type("C")
    t.type("0,0")
    t.type("5,0")
    t.type("0,5")
    t.frame(-7, -3, 7, 6)
    arc = win.document.modelspace().query("ARC")[-1]
    t.shot("before", "Un arco de 0° a 90° y una línea debajo")
    t.type("EXTEND")
    t.type("")
    t.click(4.33, 2.5)          # near the arc's 0° end
    t.type("")
    arc = win.document.modelspace().query("ARC")[-1]     # EXTEND replaces it
    want = (360 - math.degrees(math.asin(0.2))) % 360
    t.check(abs(arc.dxf.start_angle % 360 - want) < 0.01,
            "el arco llega a la línea", arc.dxf.start_angle)
    t.shot("after", "EXTEND: el arco alargado hasta tocar la línea")


def scenario_trim_quick(t):
    """4.3 TRIM modo Rápido (TRIMEXTENDMODE): sin elegir aristas, el clic
    recorta el tramo entre cruces. Se elige con la opción mOdo."""
    from core import trimmode

    trimmode.set_trimextendmode(0)       # start from the factory mode
    win = t.new_window()
    for pts in (("0,0", "10,0"), ("3,-2", "3,2"), ("7,-2", "7,2")):
        t.type("LINE")
        t.type(pts[0])
        t.type(pts[1])
        t.type("")
    t.frame(-1, -3, 11, 3)
    t.type("TRIM")
    t.shot("prompt", "TRIM: «Parámetros actuales … Modo=Estándar», como AutoCAD")
    t.type("")                           # every edge
    t.type("O")                          # mOde
    t.type("Q")                          # Quick
    t.click(5, 0.02)
    t.type("")
    t.check(trimmode.trimextendmode() == 1, "el modo Rápido queda recordado")
    lines = win.document.modelspace().query("LINE")
    xs = sorted(round(max(l.dxf.start.x, l.dxf.end.x), 6) for l in lines
                if abs(l.dxf.start.y) < 1e-9 and abs(l.dxf.end.y) < 1e-9)
    t.check(xs == [3.0, 10.0], "el tramo central se recortó", xs)
    t.shot("after", "Modo rápido: el tramo entre las dos verticales desapareció")
    trimmode.set_trimextendmode(0)


def scenario_multiple(t):
    """2.3 MULTIPLE repite el comando hasta Esc."""
    win = t.new_window()
    t.type("MULTIPLE")
    t.type("CIRCLE")
    for c in ("0,0", "10,0", "20,0"):
        t.type(c)
        t.type("2")
    t.check(len(win.document.modelspace().query("CIRCLE")) == 3,
            "tres círculos sin volver a escribir CIRCLE")
    t.check(win.tools.tool is not None, "el comando sigue activo")
    t.esc()
    t.frame(-4, -4, 24, 4)
    t.shot("circles", "MULTIPLE CIRCLE: tres círculos seguidos")


def scenario_snap_viewport_and_dimension(t):
    """3.1/3.2 REFENT engancha el borde de una ventana gráfica y la punta de
    flecha de una cota."""
    win = t.new_window()
    t.open(_annotative_sheet(t))
    win.switch_layout("Layout1")
    t.settle()
    t.frame(0, 30, 300, 170)
    t.snaps("END")
    t.type("LINE")
    t.move(10.6, 40.5)                   # the 1:1 viewport's lower-left corner
    hit = win.tools.snap_hit
    t.check(hit is not None and _close((hit.x, hit.y), (10, 40), 1e-6),
            "END en la esquina del marco de la ventana", hit)
    t.shot("vp_corner", "Marcador Fin sobre la esquina de la ventana gráfica")
    t.esc()
    win.switch_layout("Model")
    t.settle()
    t.frame(-30, -40, 40, 30)
    t.type("LINE")
    dim = [d for d in win.document.modelspace().query("DIMENSION")
           if d.dxf.dimtype & 7 == 0][0]
    p = dim.dxf.defpoint
    t.move(p.x + 0.3, p.y + 0.3)
    hit = win.tools.snap_hit
    t.check(hit is not None and hit.kind == "END", "END en la línea de cota", hit)
    t.shot("dim_end", "Marcador Fin en el extremo de la línea de cota")
    t.esc()


def scenario_copy_between_windows(t):
    """6.1 Copiar en una ventana y pegar en otra (#75)."""
    first = t.new_window()
    t.type("CIRCLE")
    t.type("0,0")
    t.type("3")
    t.frame(-5, -5, 25, 5)
    second = t.new_window()
    t.focus(first)
    first.tools.select_all()
    t.keys("Ctrl+C")
    t.wait(800)
    t.focus(second)
    t.keys("Ctrl+V")
    t.check(second.tools.tool is not None and second.tools.tool.name == "PASTECLIP",
            "Ctrl+V en la otra ventana pide el punto de inserción")
    t.type("10,0")
    t.check(len(second.document.modelspace().query("CIRCLE")) == 1,
            "el círculo llegó a la segunda ventana")
    t.frame(-5, -5, 25, 5)
    t.shot("pasted", "La segunda ventana con el círculo pegado")


def scenario_dimstyle_description(t):
    """1.6 La descripción del estilo de cota lista sólo lo que de verdad
    cambia respecto de ISO-25."""
    from views.dimstyle_dialog import DimStyleManagerDialog

    win = t.new_window()
    shots = []

    def inside(dialog):
        shots.append(t.shot("manager", "Administrador de estilos de cota con su descripción",
                            widget=dialog))
        dialog.reject()

    errors = []
    drive_modal(DimStyleManagerDialog, inside, errors)
    t.type("DIMSTYLE")
    t.wait(400)
    t.check(shots and not errors, "el administrador abrió", errors[:1])


def scenario_dyn_tooltip_left(t):
    """1.5 El globo de entrada dinámica no se sale por la izquierda en un
    lienzo angosto."""
    win = t.new_window(size=(900, 800))
    t.wait(600)                          # let the resize land before measuring
    win.tools.dyn_on = True
    t.type("LINE")
    t.type("0,0")
    t.move(0, 0)
    x0, y0, x1, y1 = win.viewport._view_world_rect()
    target = (x0 + (x1 - x0) * 0.02, (y0 + y1) / 2 + (y1 - y0) * 0.1)
    for _ in range(5):                   # the window may still be settling
        t.focus(win)
        t.move(target[0] + (x1 - x0) * 0.01, target[1])
        t.move(*target)
        t.wait(300)
        if win.tools._cursor is not None:
            break
    from views.viewport import dyn_tooltip_origin  # noqa: F401 -- the rule under test
    t.check(win.tools.dyn_on and win.tools._cursor is not None,
            "el cursor llegó al lienzo con DIN encendido", win.tools._cursor)
    t.shot("left_edge", "Cursor pegado al borde izquierdo: el globo con la distancia sigue visible")
    t.esc()


def scenario_saved_view(t):
    """Abrir un plano en la vista que guardó su autor (AutoCAD), no en la
    extensión: Yanaquihua tiene bloques en coordenadas UTM lejanas."""
    win = t.new_window()
    t.open(f"{CORPUS}/0306_E-1 Y P-2 CIMENTACION FINAL YANAQUIHUA.dwg")
    v = win.viewport.view
    t.check(abs(v.cx - 2825.50) < 0.01 and abs(v.height / v.scale - 1.825) < 0.01,
            "abre en la vista guardada (centro 2825.5, alto 1.83)",
            (round(v.cx, 2), round(v.cy, 2), round(v.height / v.scale, 3)))
    t.shot("opened", "El plano del colega abre en el detalle donde lo dejó")


def scenario_select_all(t):
    """MOVE, ALL, Enter: las opciones tecleadas en «Designe objetos»."""
    win = t.new_window()
    for start, end in (("0,0", "10,0"), ("0,5", "10,5")):
        for text in ("LINE", start, end, ""):
            t.type(text)
    for text in ("MOVE", "ALL"):
        t.type(text)
    t.check(any("2 encontrado" in l or "2 found" in l for l in t.last_lines(4)),
            "ALL encuentra los 2 objetos", t.last_lines(3))
    for text in ("", "0,0", "0,20"):
        t.type(text)
    ys = sorted(l.dxf.start.y for l in win.document.modelspace().query("LINE"))
    t.check(ys == [20.0, 25.0], "las dos líneas se movieron", ys)
    t.frame(-2, -2, 12, 27)
    t.shot("moved", "MOVE con ALL: las dos líneas subieron 20")


def scenario_sandbox_disks(t):
    """6.4 Dentro del Flatpak se ven los discos externos por su ruta real
    (/media, /run/media): un xref en un USB no queda como /run/flatpak/doc."""
    import os

    if not os.path.exists("/.flatpak-info"):
        t.note("Fuera del Flatpak: no aplica.")
        return
    info = open("/.flatpak-info").read()
    t.check("/media" in info and "/run/media" in info,
            "el sandbox declara /media y /run/media",
            [l for l in info.splitlines() if "filesystems" in l])
    seen = [p for p in ("/media", "/run/media") if os.path.isdir(p)]
    # Ubuntu mounts disks under /media, Fedora/Arch under /run/media: the
    # host has one of them, and the sandbox shows it
    t.check(bool(seen), "los discos externos son visibles dentro del sandbox", seen)
    if seen:
        t.note("Contenido de " + seen[0] + ": " + ", ".join(os.listdir(seen[0])[:10]))
