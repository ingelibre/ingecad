import copy
import json
import math
from pathlib import Path
from PySide6.QtCore import Qt, QObject, Signal, Slot, QThread, QPointF, QTimer, QEvent, QSize, QRectF
from PySide6.QtGui import QColor, QPen, QVector3D, QPainter, QPalette
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QDoubleSpinBox,QCheckBox,
    QDialog,QDialogButtonBox,QTabWidget,QTableWidget,QTableWidgetItem,QFileDialog,QMessageBox,QPlainTextEdit,QHeaderView,
    QRadioButton,QButtonGroup,QGridLayout,QScrollArea,QFrame,QToolButton)
from .model import benchmark,validate
from .client import analyze
from .icons import icon,pixmap

from .theme import ThemeAware, apply_style
from .results import VERSION,is_current
from .inspector import Inspector
from . import visualization
from .examples import CATALOG, example as example_model
from .materials import PRESETS, NOTES, material_preset

KEY='go_structural_analysis'
FIELDS={
 'nodes':['id','x','z','support'], 'members':['id','i','j','type','material','section','release_i','release_j'],
 'materials':['id','E','G','nu','rho'], 'sections':['id','A','Iy','Iz','J'],
 'point_loads':['node','member','direction','value','x','case'],
 'distributed_loads':['member','direction','w1','w2','x1','x2','case']}
NUMERIC={'x','z','E','G','nu','rho','A','Iy','Iz','J','value','w1','w2','x1','x2'}
CHOICES={'support':['Free','Fixed','Pin','Roller','RollerX'],'type':['Beam','Frame','Truss'],'direction':['FX','FZ','MY']}
CHOICES.update(release_i=['','False','True'],release_j=['','False','True'])

class Editor(ThemeAware,QDialog):
    def __init__(self,data,parent):
        super().__init__(parent); self.setObjectName('goEditor'); apply_style(self); self.setWindowIcon(icon()); self.setWindowTitle('Structural model — m, kN'); self.resize(850,560)
        self.data=copy.deepcopy(data); self.tables={}; box=QVBoxLayout(self)
        info=QLabel('XZ plane • E/G: kN/m² • A: m² • Iy/Iz/J: m⁴ • Iz: in-plane bending\nPin restrains X/Z; Roller restrains Z; RollerX restrains X. Truss loads at nodes.'); info.setWordWrap(True); box.addWidget(info)
        tabs=QTabWidget(); self.tabs=tabs; box.addWidget(tabs)
        for key,fields in FIELDS.items():
            page=QWidget(); layout=QVBoxLayout(page); table=QTableWidget(0,len(fields)); table.setHorizontalHeaderLabels(fields)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.tables[key]=table; layout.addWidget(table)
            if key=='materials':
                presets=QHBoxLayout(); self.material_presets=QComboBox(); self.material_presets.addItems(PRESETS)
                self.add_material_button=QPushButton('Add preset'); presets.addWidget(self.material_presets); presets.addWidget(self.add_material_button); layout.addLayout(presets)
                self.material_note=QLabel(NOTES['Steel']+' E/G: kN/m²; rho: kN/m³.'); self.material_note.setWordWrap(True); layout.addWidget(self.material_note)
                self.material_presets.currentTextChanged.connect(lambda name:self.material_note.setText(NOTES[name]+' E/G: kN/m²; rho: kN/m³.'))
                self.add_material_button.clicked.connect(self.add_material_preset)
            for row in data.get(key,[]): self.add_row(key,row)
            buttons=QHBoxLayout(); add=QPushButton('Add'); remove=QPushButton('Delete selected'); buttons.addWidget(add); buttons.addWidget(remove); layout.addLayout(buttons)
            add.clicked.connect(lambda _=False,k=key:self.add_row(k,{}))
            remove.clicked.connect(lambda _=False,t=table:self.remove_rows(t))
            tabs.addTab(page,key.replace('_',' ').title())
        self.tables['materials'].itemChanged.connect(lambda _=None:self.refresh_material_choices())
        self.cases=QPlainTextEdit('\n'.join(data['cases'])); self.cases.setMaximumHeight(65); box.addWidget(QLabel('Load cases (one per line)')); box.addWidget(self.cases)
        self.weight=QCheckBox('Self-weight in every case (rho in kN/m³)'); self.weight.setChecked(data.get('self_weight',False)); box.addWidget(self.weight)
        self.error=QLabel(); self.error.setWordWrap(True); box.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept_model); buttons.rejected.connect(self.reject); box.addWidget(buttons)
    def add_row(self,key,row):
        t=self.tables[key]; i=t.rowCount(); t.insertRow(i)
        for j,k in enumerate(FIELDS[key]):
            if k=='material':
                w=QComboBox(); w.setEditable(True); w.addItems([m['id'] for m in self.data['materials']]); w.setCurrentText(str(row.get(k,self.data['materials'][0]['id']))); t.setCellWidget(i,j,w)
            elif k in CHOICES:
                w=QComboBox(); w.addItems(CHOICES[k]); w.setCurrentText(str(row.get(k,CHOICES[k][0]))); t.setCellWidget(i,j,w)
            else: t.setItem(i,j,QTableWidgetItem(str(row[k]) if k in row else ''))
    def remove_rows(self,t):
        for i in sorted({v.row() for v in t.selectedIndexes()},reverse=True): t.removeRow(i)
        if t is self.tables['materials']: self.refresh_material_choices()
    def refresh_material_choices(self):
        table=self.tables['materials']; ids=[table.item(i,0).text().strip() for i in range(table.rowCount()) if table.item(i,0) and table.item(i,0).text().strip()]
        members=self.tables['members']; column=FIELDS['members'].index('material')
        for i in range(members.rowCount()):
            combo=members.cellWidget(i,column); old=combo.currentText(); combo.blockSignals(True); combo.clear(); combo.addItems(ids); combo.setCurrentText(old); combo.blockSignals(False)
    def add_material_preset(self):
        name=self.material_presets.currentText(); table=self.tables['materials']
        for i in range(table.rowCount()):
            if table.item(i,0) and table.item(i,0).text().strip()==name:
                table.selectRow(i); self.material_note.setText(name+' already exists; its edited values are preserved.'); return
        self.add_row('materials',material_preset(name)); self.refresh_material_choices(); table.selectRow(table.rowCount()-1)
    def accept_model(self):
        try:
            d={'schema':1,'self_weight':self.weight.isChecked(),'cases':[c.strip() for c in self.cases.toPlainText().splitlines() if c.strip()]}
            for key,fields in FIELDS.items():
                rows=[]
                for i in range(self.tables[key].rowCount()):
                    row={}; t=self.tables[key]
                    for j,k in enumerate(fields):
                        w=t.cellWidget(i,j); item=t.item(i,j); v=w.currentText() if w else (item.text().strip() if item else '')
                        if v: row[k]=(v=='True') if k in ('release_i','release_j') else (float(v) if k in NUMERIC else v)
                    if row: rows.append(row)
                d[key]=rows
            self.data=validate(d); self.accept()
        except Exception as exc: self.error.setText(str(exc))

class SolverTask(QObject):
    done=Signal(object)
    def __init__(self,model): super().__init__(); self.model=model
    @Slot()
    def run(self):
        try: payload={'ok':True,'result':analyze(self.model)}
        except Exception as exc: payload={'ok':False,'error':str(exc)}
        self.done.emit(payload)

class Workspace:
    allowed_tools={'select','pan','zoom'}
    def __init__(self,panel,data=None):
        from core.scene import Scene
        from core.history import History
        self.panel=panel; self.scene=Scene(); self.history=History(self.scene); self.path=None; self.saved=None
        if data: self.scene.plugin_data[KEY]=copy.deepcopy(data)
        self.camera={'target':[3,0,0],'distance':14,'yaw':-math.pi/2,'pitch':0,'perspective':False}
    def title(self): return 'GO Structural Analysis v'+VERSION+' — '+(self.path.name if self.path else 'Untitled')
    def is_dirty(self): return self.scene.plugin_data.get(KEY)!=self.saved
    def save(self):
        if self.path is None: return self.save_as()
        from formats.igz import save_scene
        try:
            save_scene(self.scene,self.path); self.saved=copy.deepcopy(self.scene.plugin_data.get(KEY)); return True
        except Exception as exc: QMessageBox.warning(self.panel,'Save failed',str(exc)); return False
    def save_as(self):
        path,_=QFileDialog.getSaveFileName(self.panel,'Save structural document','','IngeTrazo (*.igz)')
        if not path: return False
        self.path=Path(path).with_suffix('.igz'); return self.save()
    def confirm_leave(self):
        if self.panel.thread is not None:
            QMessageBox.information(self.panel,'Analysis running','Wait for the solver to finish.'); return False
        if not self.is_dirty(): return True
        choice=QMessageBox.question(self.panel,'Unsaved analysis','Save the structural workspace before leaving?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
        return self.save() if choice==QMessageBox.StandardButton.Save else choice==QMessageBox.StandardButton.Discard
    def left(self): self.panel.refresh()

class OverlayCanvas(QWidget):
    """Compatibility canvas: installed frozen builds may omit extension overlays.

    A transparent child of the viewport paints only this extension's data.
    No host methods are patched; the native API overlay remains registered.
    """
    def __init__(self,panel):
        super().__init__(panel.app.viewport); self.panel=panel
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(panel.app.viewport.rect()); panel.app.viewport.installEventFilter(self)
        self.timer=QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self.sync); self.timer.start(); self.show(); self.raise_()
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Resize: self.setGeometry(obj.rect())
        if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton and self.panel.tabs.currentIndex()==2:
            hit=visualization.pick(self.panel,event.position().x(),event.position().y())
            if hit:
                self.panel.select_member(*hit); return True
        return False
    def sync(self):
        ws=self.panel.app.workspace(); cam=self.panel.app.viewport.camera
        if getattr(ws,'panel',None) is self.panel and (cam.pitch!=0 or cam.yaw!=-math.pi/2 or cam.perspective):
            cam.pitch=0.0; cam.yaw=-math.pi/2; cam.perspective=False; self.panel.app.viewport.update()
        self.setVisible(bool(self.panel.model())); self.raise_(); self.update()
    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try: self.panel.paint(self.panel.app.viewport,painter)
        except Exception as exc: self.panel.status.setText('Diagram failed: '+str(exc))
        finally: painter.end()

class ModelRadio(QRadioButton):
    """Keep the reference's circular selector on Windows native Qt styles."""
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); cy=self.height()/2
        palette=self.palette(); text=palette.color(QPalette.ColorRole.WindowText); background=palette.color(QPalette.ColorRole.Window)
        p.setPen(QPen(text if self.isChecked() else palette.color(QPalette.ColorRole.PlaceholderText),1.3)); p.setBrush(text if self.isChecked() else background); p.drawEllipse(QPointF(11,cy),10,10)
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(background); p.drawEllipse(QPointF(11,cy),3,3)
        p.setFont(self.font()); p.setPen(text); p.drawText(QRectF(34,0,self.width()-34,self.height()),Qt.AlignmentFlag.AlignVCenter,self.text()); p.end()

class Panel(ThemeAware,QWidget):
    def __init__(self,app):
        super().__init__(); self.app=app; self.thread=None; self.task=None; self.result=None; self.last_data=None
        self.setObjectName('goPanel'); apply_style(self); self.setWindowIcon(icon()); self.pending_type='Beam'
        layout=QVBoxLayout(self); layout.setContentsMargins(14,14,14,12); layout.setSpacing(12)
        header=QHBoxLayout(); logo=QLabel(); logo.setProperty('go_icon','extension'); logo.setProperty('go_icon_size',32); logo.setPixmap(pixmap('extension',32)); header.addWidget(logo)
        heading=QLabel('GO Structural Analysis'); heading.setObjectName('goTitle'); heading.setWordWrap(True); header.addWidget(heading,1)
        badge=QLabel('v'+VERSION); badge.setObjectName('goBadge'); header.addWidget(badge); layout.addLayout(header)
        self.tabs=QTabWidget(); self.tabs.setDocumentMode(True); self.tabs.setUsesScrollButtons(False); self.tabs.tabBar().setDrawBase(False); self.tabs.tabBar().setExpanding(True); layout.addWidget(self.tabs,1)
        self.tab_layouts=[]
        for title in ['Model','Loads','Results']:
            scroll=QScrollArea(); scroll.setWidgetResizable(True); page=QWidget(); page.setObjectName('goPage'); content=QVBoxLayout(page); content.setContentsMargins(0,12,0,8); content.setSpacing(10); scroll.setWidget(page); self.tabs.addTab(scroll,title); self.tab_layouts.append(content)
        model_box,loads_box,results_box=self.tab_layouts
        title=QLabel('Model Type'); title.setObjectName('goSection'); model_box.addWidget(title)
        self.types=QButtonGroup(self); self.type_buttons={}
        for kind in ['Beam','Frame','Truss']:
            radio=ModelRadio('2D '+kind); self.types.addButton(radio); self.type_buttons[kind]=radio; model_box.addWidget(radio)
            radio.clicked.connect(lambda _=False,k=kind:self.choose_type(k))
        self.type_buttons['Beam'].setChecked(True)
        cards=QGridLayout(); cards.setSpacing(9); model_box.addLayout(cards)
        for i,(title,subtitle,glyph,key) in enumerate([('Nodes','Create / Edit','nodes','nodes'),('Members','Beam / Frame / Truss','members','members'),('Sections','Area / Inertia','sections','sections'),('Supports','Fixed / Pin / Roller','supports','nodes')]):
            cards.addWidget(self.card(title,subtitle,glyph,lambda k=key:self.edit_section(k)),i//2,i%2)
        for text,glyph,fn in [('Materials · E / G / Density','materials',lambda:self.edit_section('materials'))]:
            button=QPushButton(text); button.setProperty('go_icon',glyph); button.setIcon(icon(glyph)); button.clicked.connect(fn); model_box.addWidget(button)
        self.add_examples_controls(model_box)
        self.model_info=QLabel('No structural model yet'); self.model_info.setObjectName('goMuted'); self.model_info.setWordWrap(True); model_box.addWidget(self.model_info); model_box.addStretch()
        title=QLabel('Load Definition'); title.setObjectName('goSection'); loads_box.addWidget(title)
        load_cards=QGridLayout(); load_cards.setSpacing(9); loads_box.addLayout(load_cards)
        for i,(title,subtitle,glyph,key) in enumerate([('Point Loads','Node / Member','point','point_loads'),('Distributed','Uniform / Varying','distributed','distributed_loads'),('Load Cases','Manage cases','cases','cases')]):
            load_cards.addWidget(self.card(title,subtitle,glyph,lambda k=key:self.edit_section(k)),i//2,i%2)
        self.weight=QCheckBox('Include self-weight'); self.weight.clicked.connect(self.set_weight); loads_box.addWidget(self.weight)
        note=QLabel('m · kN · kN/m\nSelf-weight uses material density in kN/m³ and applies to every case.'); note.setObjectName('goMuted'); note.setWordWrap(True); loads_box.addWidget(note); loads_box.addStretch()
        results_box.addWidget(QLabel('Load Case')); self.case=QComboBox(); self.case.currentTextChanged.connect(self.redraw); results_box.addWidget(self.case)
        results_box.addWidget(QLabel('Viewport Diagram')); self.diagram=QComboBox(); self.diagram.addItems(['Model','N','V','M','D','Reaction','Deformed']); self.diagram.currentTextChanged.connect(self.redraw); results_box.addWidget(self.diagram)
        self.diagram_scale=QDoubleSpinBox(); self.diagram_scale.setRange(0.01,100); self.diagram_scale.setValue(1); self.diagram_scale.setPrefix('Diagram × '); self.diagram_scale.valueChanged.connect(self.redraw); results_box.addWidget(self.diagram_scale)
        self.scale=QDoubleSpinBox(); self.scale.setRange(0.001,1e6); self.scale.setValue(100); self.scale.setPrefix('Deformation × '); self.scale.valueChanged.connect(self.redraw); results_box.addWidget(self.scale)
        visibility=QHBoxLayout(); self.labels=QCheckBox('Labels'); self.legend=QCheckBox('Legend'); self.show_loads=QCheckBox('Loads')
        for check in [self.labels,self.legend,self.show_loads]: check.setChecked(check is not self.show_loads); check.toggled.connect(self.redraw); visibility.addWidget(check)
        results_box.addLayout(visibility)
        self.inspector=Inspector(self); results_box.addWidget(self.inspector)
        self.summary=QPlainTextEdit(); self.summary.setReadOnly(True); self.summary.setPlaceholderText('Run Analysis to view reactions and member results.'); self.summary.setMinimumHeight(80); self.summary.setMaximumHeight(130); results_box.addWidget(self.summary)
        self.run_button=QPushButton('Run Analysis'); self.run_button.setObjectName('goRun'); self.run_button.setProperty('go_icon','run'); self.run_button.setIcon(icon('run')); self.run_button.clicked.connect(self.run); layout.addWidget(self.run_button)
        self.status=QLabel('PyNite solver ready · 2D XZ · m / kN'); self.status.setObjectName('goStatus'); self.status.setWordWrap(True); layout.addWidget(self.status)
        actions=QHBoxLayout(); actions.setSpacing(7)
        for text,glyph,tip,fn in [('Workspace','workspace','Enter the 2D XZ workspace',self.enter),('Return','back','Return to the parked model',self.leave),('Save','save','Save the structural .igz document',self.save)]:
            b=QPushButton(text); b.setProperty('go_icon',glyph); b.setIcon(icon(glyph)); b.setToolTip(tip); b.clicked.connect(fn); actions.addWidget(b)
        layout.addLayout(actions)
        store=QPushButton('Store analysis in current document'); store.setToolTip('Explicitly copy workspace analysis data to the original model'); store.clicked.connect(self.store); layout.addWidget(store)
        app.on_document_changed(self.refresh); app.add_overlay(self.paint); self.refresh()
        self.canvas=OverlayCanvas(self)
        app.add_pickable(lambda vp,x,y:self.native_pick(x,y),on_select=lambda mid:self.select_member(mid) if mid is not None else None)
    def native_pick(self,x,y):
        hit=visualization.pick(self,x,y); return hit[0] if hit else None
    def select_member(self,mid,ratio=None):
        self.last_picked_member=mid; self.tabs.setCurrentIndex(2); self.inspector.select(mid,ratio)
    def card(self,title,subtitle,glyph,fn):
        b=QPushButton(); b.setObjectName('goCard'); b.setAccessibleName(title); b.setToolTip(title+' — '+subtitle)
        box=QVBoxLayout(b); box.setContentsMargins(12,10,8,10); box.setSpacing(5)
        image=QLabel(); image.setProperty('go_icon',glyph); image.setProperty('go_icon_size',21); image.setPixmap(pixmap(glyph,21)); text=QLabel(title); text.setStyleSheet('font-weight: 600;'); detail=QLabel(subtitle); detail.setObjectName('goMuted'); detail.setWordWrap(True)
        for label in [image,text,detail]: label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); box.addWidget(label)
        b.clicked.connect(lambda _=False:fn()); return b
    def choose_type(self,kind):
        self.pending_type=kind
        m=self.model()
        if m:
            m=copy.deepcopy(m)
            for member in m['members']: member['type']=kind
            try: self.put(m)
            except Exception as exc: self.status.setText(str(exc)); self.refresh_types()
    def refresh_types(self):
        model=self.model(); kinds={m['type'] for m in model['members']} if model else set()
        for kind,radio in self.type_buttons.items():
            radio.blockSignals(True); radio.setChecked(kind==(next(iter(kinds)) if len(kinds)==1 else self.pending_type)); radio.blockSignals(False)
    def set_weight(self,checked):
        m=self.model()
        if not m: self.weight.setChecked(False); self.status.setText('Create a model before enabling self-weight.'); return
        m=copy.deepcopy(m); m['self_weight']=checked; self.put(m)
    def edit_section(self,key): self.edit(key)
    def data(self): return self.app.document_data({}) or {}
    def model(self): return (self.last_data if self.last_data is not None else self.data()).get('model')
    def refresh(self):
        d=self.data()
        if d!=self.last_data:
            self.last_data=copy.deepcopy(d); self.result=d.get('result'); cases=d.get('model',{}).get('cases',[])
            old=self.case.currentText(); self.case.blockSignals(True); self.case.clear(); self.case.addItems(cases); self.case.setCurrentText(old if old in cases else (cases[0] if cases else '')); self.case.blockSignals(False)
        self.redraw()
        if hasattr(self,'type_buttons'):
            self.refresh_types(); self.weight.setChecked(d.get('model',{}).get('self_weight',False))
            m=d.get('model'); self.model_info.setText(f"{len(m['nodes'])} nodes · {len(m['members'])} members · XZ plane" if m else 'No structural model yet')
    def put(self,model,result=None):
        previous=self.data().get('result')
        self.app.set_document_data({'version':VERSION,'model':validate(model),'result':result if result is not None else previous}); self.refresh()
        if self.result and not is_current(self.model(),self.result): self.status.setText('Results out of date — Run Analysis required')
    def enter(self):
        if self.app.workspace() is not None: self.status.setText('A workspace is already active.'); return
        ws=Workspace(self,self.data() or None)
        if self.app.enter_workspace(ws): self.refresh(); self.status.setText('2D workspace active; original model parked.'); self.fit()
    def leave(self): self.app.leave_workspace(); self.refresh()
    def edit(self,key=None):
        if self.thread is not None: return
        model=self.model() or benchmark()
        if not self.model():
            model['members'][0]['type']=self.pending_type
            if self.pending_type=='Truss': model['distributed_loads']=[]
        dialog=Editor(model,self)
        if key in FIELDS: dialog.tabs.setCurrentIndex(list(FIELDS).index(key))
        elif key=='cases': dialog.cases.setFocus()
        if dialog.exec(): self.put(dialog.data); self.fit()
    def example(self):
        return self.load_example('simple_udl')
    def add_examples_controls(self,box):
        box.addWidget(QLabel('Engineering Examples / Benchmarks'))
        self.examples=QComboBox()
        for key,title,description in CATALOG: self.examples.addItem(title,key)
        box.addWidget(self.examples)
        self.example_note=QLabel(); self.example_note.setWordWrap(True); self.example_note.setObjectName('goMuted'); box.addWidget(self.example_note)
        self.examples.currentIndexChanged.connect(lambda _=0:self.example_note.setText(CATALOG[self.examples.currentIndex()][2]))
        self.example_note.setText(CATALOG[0][2])
        self.example_button=QPushButton('Load selected example'); self.example_button.clicked.connect(lambda _=False:self.load_example(self.examples.currentData())); box.addWidget(self.example_button)
    def load_example(self,key):
        if self.thread is not None: return
        model=example_model(key)
        if self.app.workspace() is None: self.enter()
        ws=self.app.workspace()
        if getattr(ws,'panel',None) is self:
            if self.model() and ws.is_dirty():
                choice=QMessageBox.question(self,'Replace structural example?','The current structural workspace has unsaved changes. Replace it with the selected example?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if choice!=QMessageBox.StandardButton.Yes: return
            self.put(model); self.fit(); self.tabs.setCurrentIndex(0)
            self.status.setText('Example loaded — Run Analysis. '+next(row[2] for row in CATALOG if row[0]==key))
    def store(self):
        # User-requested explicit commit only; never done by installation/tests.
        ws=self.app.workspace()
        if getattr(ws,'panel',None) is not self: self.status.setText('Changes are already stored in the current .igz document.'); return
        d=copy.deepcopy(self.data())
        if self.app.leave_workspace(): self.app.set_document_data(d); self.status.setText('Analysis data stored in model; save .igz to persist.')
    def save(self):
        ws=self.app.workspace()
        if getattr(ws,'panel',None) is self: ws.save_as()
        else: self.status.setText('Use IngeTrazo File → Save to save current document data.')
    def fit(self):
        m=self.model()
        if not m: return
        xs=[n['x'] for n in m['nodes']]; zs=[n['z'] for n in m['nodes']]
        cam=self.app.viewport.camera; cam.target=QVector3D((min(xs)+max(xs))/2,0,(min(zs)+max(zs))/2)
        cam.yaw=-math.pi/2; cam.pitch=0.0; cam.perspective=False; cam.distance=max(max(xs)-min(xs),max(zs)-min(zs),2)*2.5; self.app.viewport.update()
    def run(self):
        if self.thread is not None: return
        try: model=validate(self.model()); self.analysis_model=copy.deepcopy(model); self.analysis_scene=self.app.scene
        except Exception as exc: self.status.setText(str(exc)); return
        self.status.setText('Analyzing with PyNite worker…'); self.run_button.setEnabled(False)
        self.thread=QThread(self); self.task=SolverTask(model); self.task.moveToThread(self.thread)
        self.thread.started.connect(self.task.run); self.task.done.connect(self.complete,Qt.ConnectionType.QueuedConnection)
        self.task.done.connect(self.thread.quit); self.thread.finished.connect(self.task.deleteLater); self.thread.finished.connect(self.finished); self.thread.start()
    @Slot(object)
    def complete(self,payload):
        if self.app.scene is not self.analysis_scene or self.data().get('model')!=self.analysis_model:
            self.status.setText('Document changed; stale solver results discarded.'); return
        if not payload['ok']: self.status.setText('Analysis failed: '+payload['error']); return
        self.put(self.analysis_model,payload['result']); self.status.setText('Analysis complete — PyNiteFEA '+payload['result']['version'])
        self.tabs.setCurrentIndex(2)
    @Slot()
    def finished(self):
        self.thread.deleteLater(); self.thread=None; self.task=None; self.run_button.setEnabled(True)
    def redraw(self,*args):
        self.app.viewport.update()
        if hasattr(self,'inspector'): self.inspector.refresh()
        if not is_current(self.model(),self.result) or self.case.currentText() not in self.result['cases']:
            self.summary.setPlainText('RESULTS OUT OF DATE — Run Analysis' if self.result else ''); return
        r=self.result['cases'][self.case.currentText()]; lines=['Reactions (kN; kN·m)']
        for n,v in r['nodes'].items(): lines.append(f"{n}: Rx={v['Rx']:.5g}, Rz={v['Rz']:.5g}, My={v['My']:.5g}")
        for mid,v in r['members'].items():
            for key,extrema in v['extrema'].items():
                units='m' if key=='d' else ('kN·m' if key=='M' else 'kN')
                lines.append(f"{mid} {key}: min {extrema['min']['value']:.6g}, max {extrema['max']['value']:.6g} {units}")
        self.summary.setPlainText('\n'.join(lines))
    def paint(self,viewport,painter):
        visualization.draw(self,viewport,painter)

def setup(app):
    if getattr(app,'api_version',0)!=2: raise RuntimeError('GO Structural Analysis requires IngeTrazo Plugin API v2')
    existing=getattr(app.window,'_go_structural_panel',None)
    if existing is not None: return existing
    panel=Panel(app); dock=app.add_panel('GO Structural',panel); dock.setWindowIcon(icon())
    action=app.add_menu_action('GO Structural Analysis v'+VERSION,lambda:app.show_panel(dock),tip='2D beam, frame and truss analysis')
    if action is not None: action.setIcon(icon())
    panel.menu_action=action; panel.dock=dock
    app.window._go_structural_panel=panel
    return panel
