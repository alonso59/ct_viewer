Update README_UX_UI_ARCHITECTURE.md to reflect the final UX discovery questionnaire decisions.

This is a documentation and product-architecture update first. Do not modify application code yet.

Context:
The previous UX architecture defined Workspace, Worklist, Clinical Review Shell, and Case Dossier as separate surfaces. The final product direction has changed. The WebUI should now behave as a focused two-screen medical curation product:

1. Dataset Load Screen
2. Main Review Screen

The /cases page should no longer be treated as a primary user-facing screen. The Main Review Screen contains the scrollable case navigator and all routine review actions.

Use these final UX decisions as source of truth:

User context:
- Primary user: medical researcher / medical doctor acting as data curator.
- Review volume: 5–10 cases per session.
- Review mode: individual.
- Hardware: 27-inch monitor or 14-inch laptop.
- Supported resolution: minimum 1280×720, target 1440×1000, maximum 2560×1440.
- Primary input: mouse.
- Training: minimal; UI must be self-explanatory.

Primary task:
- The most frequent and highest-priority task is phase determination/correction and comparison between original CT and VOIs.
- On case open, load scan 0 complete CT by default.
- Routine decisions must be possible without page-level scrolling:
  - phase correction
  - scan/VOI exclusion
  - QC decision
- Segmentation QC is one decision per case, not per label.
- Review focus: kidney and tumor.
- Flow: case by case.

Viewer layout:
- Default layout is fixed 2×2:
  - AXI
  - COR
  - SAG
  - 3D slot
- 2×2 must always be visible without page-level scrolling at 1440×1000.
- The panels do not disappear.
- 3D is available on demand, not dominant by default.
- Layout selector should use minimalist icons.
- The doctor may activate/deactivate AXI/COR/SAG individually, but the grid remains stable.
- Add Reset Layout.
- No separate “focus buttons” are required because the doctor interacts directly with each panel.

Viewer image rules:
- Always preserve image aspect ratio.
- Never stretch CT slices.
- Default fit mode: fit entire slice inside panel.
- Viewer panels should be square 1:1 containers.
- CT can be 4:3 internally but must be contained without deformation.
- Sliders have reserved fixed space, Slicer-like.
- Auto-center image when changing case, scan, phase, or scope.
- Zoom/pan is independent per panel.

Left panel:
The left panel is the most important non-image area.
It must be always visible and never collapsed.
Width target at 1440px: 300px full.
No vertical tabs.
No thumbnails in v1.

The left panel should contain:
- case navigator
- scan/source navigator
- phase/scope/side controls
- overlays/layers controls
- secondary QC-related actions
- Case Data access
- warning badges

Use clean collapsible menus, grouped sections, chips, simple icons, and lists.

Navigation hierarchy:
Use:
Case → Scan → Phase → Scope → Side

The doctor thinks first in terms of available sources, not technical dropdowns.

Show available phases always:
- NC
- CMP
- NP
- EXC

All source interaction should be in the left panel using a navigator with simple buttons/icons.
scan_idx should be inside the navigator, not an isolated technical dropdown.
Side L/R should use chips or toggle inside the navigator.
Provide quick CT ↔ VOI comparison within the 2×2 layout.

Overlays:
Available overlays:
- kidney
- tumor
- cyst

Overlay controls live in the left panel under Layers/Overlays.
Each overlay must support:
- show/hide
- opacity slider
- filled vs contour-only mode

Default overlay mode: filled.
Colors:
- kidney = light blue
- tumor = orange/red
- cyst = green

Viewer must include a fixed legend in a corner, not only tooltips.

Right QC panel:
The QC panel is fixed on the right and always visible.
Width target: 220px.
QC decision is one decision per case, not per individual scan or label.

Actions:
- Accept
- Needs correction
- Reject
- Cannot assess

Primary button:
- Save & Next

Add to correction queue:
- automatic when status = Needs correction

No confirmation modal for normal QC save.
Comment is optional in all states.
Comment is recommended but not blocking for Needs correction.
No comment templates in v1.

Warnings:
Critical warnings:
- Missing SEG
- Missing VOI
- Wrong phase suspected
- Wrong side suspected
- Duplicate scan
- Ambiguous phase

Warnings appear as visible badges in the left navigator.
Do not use blocking banners for routine warnings.
Only Missing SEG blocks QC.
All other warnings are informational.
The doctor cannot mark warnings as resolved in v1; this remains technical-team responsibility.

Case Data:
Replace “Case Dossier page” with “Case Data overlay modal”.

Case Data is activated by an icon in the left panel.
It is not a separate full page in v1.

Name:
- Case Data

Format:
- overlay modal
- clinical categorized report style
- not spreadsheet-like

Sections:
- Case Summary
- Imaging Availability
- Segmentation & VOI
- QC History

Case Data must support metadata search.
No export in v1.
Raw fields are hidden by default.
Always visible fields:
- case_id
- available phases
- QC status
- active warnings

Technical paths hidden by default.

Tabs/drawers:
Secondary tabs may include:
- Inventory
- Warnings
- History

Viewer, QC decision, active case identity, and loaded source must never be hidden behind tabs.

Bottom drawer:
- collapsible
- remembers last open tab

Worklist:
Remove /cases as a main product surface.
There are only two primary screens:
1. Dataset Load Screen
2. Main Review Screen

The Main Review Screen contains:
- scrollable full case navigator
- prominent Next Case button

Comparison:
v1:
- CT ↔ VOI comparison inside 2×2 layout

v2:
- phase comparison NP vs CMP
- L vs R comparison
- synchronized crosshair between compared panels
- dedicated compare-phases layout

Viewer interactions:
- Mouse wheel: slice
- Ctrl + wheel: zoom
- Shift + drag: pan
- Right drag: window/level

Keyboard shortcuts:
- N = Next case
- A = Accept
- C = Needs correction
- R = Reject
- Space = Next slice

Add:
- help overlay
- visible shortcut tooltip for users without extensive training

No review locked mode in v1.

Safety:
Highest scientific risk:
- wrong phase correction
- exclusion of valid scan

Phase correction requires a simple one-click confirmation:
Example: “Change phase from NP to CMP?”

Important:
There is a product decision conflict that must be explicitly documented:
The previous SRS/README said phase change should only create a proposal/flag and should not modify database.csv or move files.
The final questionnaire decision says phase correction modifies database.csv directly and moves VOI files to the corresponding folder, while leaving an audit log.

Update the architecture to resolve this as follows:
- Normal QC actions remain curation-state writes.
- Phase correction is a separate “Controlled Dataset Correction” action, not routine QC.
- It must be visually separated from the QC decision panel.
- It requires confirmation.
- It must write an audit log.
- It should support backup or rollback if feasible.
- It must not be silent.
- It must refresh database/path validation after execution.
- It must not be visually presented as a casual toggle.

Audit log:
- not visible in v1 UI
- recorded persistently

Save blocking:
- block Save QC if no source is loaded
- do not block queue when comment is missing

Visual style:
- dark theme
- verify contrast at 1280×720
- reduce overuse of blue buttons
- reserve blue for primary actions
- status badge colors:
  - green = accepted
  - yellow = needs correction
  - red = rejected
  - gray = unreviewed
- simple minimal iconography
- reduce borders and panel visual noise
- visual hierarchy:
  1. Viewer
  2. Left panel
  3. QC panel

Success criteria:
- At 1440×1000, the full review view shows:
  - 2×2 viewer
  - left panel
  - right QC panel
  - no page-level scroll
- Accepting a normal case takes ≤ 3 clicks.
- Switching CT → VOI takes ≤ 2 clicks.
- Warnings are visible with 0 clicks.
- Normal case review takes < 60 seconds.
- Validation test:
  - 1 medical doctor
  - 10 real cases
  - >80% of tasks completed without assistance.

Update the document sections accordingly:
- Product North Star
- Core Product Boundaries
- UX Principles
- Information Architecture
- Workspace / Dataset Load Screen
- Main Review Screen
- Left Panel
- Viewer Layout
- Right QC Panel
- Case Data overlay
- Warning model
- Controlled Dataset Correction
- Interaction rules
- Responsive behavior
- Acceptance criteria
- Implementation guidance
- Visual regression targets

Remove or de-emphasize:
- Worklist as a separate main screen
- Case Dossier as a separate route/page
- scan_idx dropdown as primary navigation
- raw metadata as primary UI
- source-data read-only rule as absolute, replacing it with:
  - routine QC is curation-state only
  - controlled dataset correction may modify database.csv and move VOI files only with confirmation and audit log

Do not implement code in this step.
Return:
1. summary of changes made to README_UX_UI_ARCHITECTURE.md
2. unresolved product risks
3. any SRS contradictions that must be updated next

Cuestionario UX/UI — Respuestas Completas

1. Usuario y contexto clínico
Usuario principal: Médico investigador
Volumen por sesión: 5–10 casos
Modalidad: Revisión individual
Hardware: Monitor 27" o laptop 14"
Rango de resolución: 1280×720 mínimo — 2560×1440 máximo
Input principal: Mouse
Capacitación: Sin capacitación extensa; interfaz autoexplicativa

2. Tarea principal de revisión
Tarea más frecuente: Cambiar determinación de fase (prioridad máxima); comparar fases entre CT original y VOIs
Al abrir un caso en <10 s: Cargar scan 0 (CT completo) con toda su información visible y acceso inmediato a metadatos categorizados vía overlay
Decisión sin scroll: Cambio de fase, exclusión de scan/VOI, decisión QC
Juicio de segmentación: General — por scan y por caso, no por label individual
Revisión principal: Riñón y tumor
Vista por defecto: CT completo (scan 0); el médico decide si accede al VOI
Flujo: Caso por caso

3. Layout del viewer
Layout default: 2×2 fijo (AXI + COR + SAG + slot 3D), siempre visible, sin scroll
Selector de layout: Sí, con iconos minimalistas; el médico activa/desactiva AXI, COR, SAG individualmente
Layouts obligatorios: 2×2 fijo con slot 3D; los paneles no desaparecen
3D por defecto: Solo bajo demanda
— Icono verde = activo · color base = inactivo · gris = máscara no disponible
— Nomenclatura: CT vs VOI · Vistas: AXI, COR, SAG
Botones Focus por eje: No necesarios; el médico interactúa directamente con el panel
Botón Reset layout: Sí

4. Aspect ratio y fit de imagen
Conservar relación de aspecto: Siempre; sin deformación
Modo default: Fit entire slice inside panel
Paneles del viewer: Siempre cuadrados (1:1); el CT completo puede ser 4:3 internamente pero el panel lo contiene sin deformar
Sliders: Espacio fijo reservado, estilo 3D Slicer
Centrado automático: Sí — al cambiar scan, fase o caso
Sincronización zoom/pan entre paneles: Independiente por panel

5. Panel izquierdo
Contenido: Todo lo que no es imagen vive aquí — navigator de casos, selector de scan/phase/scope/side, overlays, acciones QC secundarias. Usar mejores prácticas: menús colapsables, tabs, listas
Pestañas verticales: No
Miniaturas: No
Siempre visible: Sí, nunca se puede esconder
Colapsable a iconos: No
Ancho (1440 px): 300 px full

6. Navegación por caso, fase, scan y VOI
Jerarquía: Case → Scan → Phase → Scope → Side
El médico piensa primero en: Source available (qué escaneos existen)
Fases disponibles: Mostrar siempre NC, CMP, NP, EXC
Toda la interacción: En el panel izquierdo mediante Navigator con botones e iconos simples
Navigator de casos: Lista scrolleable de todos los casos del dataset + botones Prev / Next
scan_idx: Dentro del navigator, no como dropdown técnico aislado
Side L/R: Chips o toggle dentro del navigator
Comparación rápida CT ↔ VOI: Sí, dentro del layout 2×2

7. Overlays y segmentación
Overlays disponibles: kidney · tumor · cyst
Ubicación de controles: Panel izquierdo (sección Layers/Overlays)
Control de opacidad: Sí, slider simple por overlay
Ocultar/mostrar por label: Sí
Contour only vs filled: Ambos modos, toggle por overlay; default: filled
Colores estándar: kidney = azul claro · tumor = naranja/rojo · cyst = verde
Leyenda: Fija en esquina del viewer, no solo tooltip

8. QC decision
Ubicación: Panel derecho fijo, siempre visible (220 px)
Acciones: Accept · Needs correction · Reject · Cannot assess
Add to correction queue: Automático cuando status = Needs correction
Confirmación antes de guardar: No (flujo rápido, sin modal)
Botón principal: Save & Next
Comentario: Opcional en todos los estados; recomendado pero no bloqueante en Needs correction
Templates de comentario: No en v1

9. Warnings y errores
Warnings críticos: Missing SEG · Missing VOI · Wrong phase suspected · Wrong side suspected · Duplicate scan · Ambiguous phase
Ubicación: Badge visible en navigator del panel izquierdo; sin banner bloqueante
Bloquea QC: Solo Missing SEG
Solo informa: Todos los demás warnings
El médico puede marcar warning como resuelto: No — responsabilidad del equipo técnico

10. Case Data (Dossier)
Formato: Overlay modal, activado por icono en panel izquierdo; no página separada
Nombre: Case Data
Secciones: Case Summary · Imaging Availability · Segmentation & VOI · QC History
Estilo: Reporte clínico categorizado, no spreadsheet
Búsqueda dentro de metadata: Sí
Exportación: No en v1
Raw fields: Ocultos por defecto
Campos siempre visibles: case_id · fases disponibles · QC status · warnings activos
Paths técnicos: Ocultos por defecto

11. Tabs, drawers y navegación secundaria
Tabs disponibles: Inventory · Warnings · History (en drawer inferior colapsable)
No va en tabs: Viewer principal · QC decision primaria · identidad del caso activo · source cargado
Drawer inferior: Colapsable, recuerda el último tab abierto

12. Worklist
Página /cases: Eliminada. Existen solo dos pantallas:

Dataset load screen — carga de database.csv
Main review screen — toda la revisión sucede aquí


13. Comparación y multi-layout
Comparación CT ↔ VOI: Sí en v1, dentro del layout 2×2 lado a lado
Comparación entre fases (NP vs CMP): v2
Comparación L vs R: v2
Crosshair sincronizado entre paneles: v2
Layout "Compare phases" dedicado: v2

14. Interacciones del viewer
GestoAcciónMouse wheelCambiar sliceCtrl + wheelZoomShift + dragPanRight dragWindow / Level
Atajos de teclado:
TeclaAcciónNNext caseAAcceptCNeeds correctionRRejectSpaceNext slice
Instrucciones visibles: Help overlay activable + tooltip de atajos siempre visible para usuarios sin capacitación
Modo review locked: No en v1

15. Seguridad y prevención de errores
Acción de mayor riesgo científico: Cambio de fase incorrecto o exclusión de scan válido
Requiere confirmación simple (1 click): Cambio de fase — ej. "¿Cambiar fase de NP a CMP?"
Cambio de fase: Genera propuesta/flag; no modifica database.csv directamente
Audit log visible: No en v1; registrado en base de datos
Bloquear Save QC sin source cargado: Sí
Bloquear queue sin comentario: No
Indicador source-data read-only: No en v1

16. Visual style
Tema: Dark
Contraste: Suficiente; verificar en 1280×720
Botones azules: Reducir uso; reservar azul para acciones primarias únicamente
Badges consistentes: verde = accepted · amarillo = needs correction · rojo = rejected · gris = unreviewed
Iconografía: Simple, minimalista, sin texto
Borders y paneles: Reducidos al mínimo
Jerarquía visual: Viewer > panel izquierdo > panel QC

17. Criterios de éxito
CriterioTargetVista completa sin scroll1440×1000: viewer 2×2 + panel izq + panel QCClicks para aceptar un caso≤ 3Clicks para cambiar CT → VOI≤ 2Clicks para ver warnings0 (visibles en navigator)Tiempo por caso normal< 60 segundosPrueba suficiente1 médico · 10 casos reales · >80% tareas sin asistencia


3 items pendientes de confirmación tuya antes de generar el README_UX_UI_ARCHITECTURE.md:

¿QC se guarda por scan individual o una sola decisión por caso completo?
¿El cambio de fase modifica database.csv directamente o genera propuesta pendiente?
¿El navigator muestra lista completa scrolleable o solo Prev/Next sin lista?

 una sola desicionuna sola desicionModifica el database y mueve el archivo VOI a su carpeta correspondiente pero deja registro.Muestra una lista scrollable y un boton de next case.3:03 PM: Respuestas finales registradasCompiló respuestas finales y validó cuestionario completoCompiló respuestas finales y validó cuestionario completoRespuestas finales registradas
1. QC decision: Una sola decisión por caso completo — no por scan individual.
2. Cambio de fase: Modifica database.csv directamente y mueve el archivo VOI a la carpeta correspondiente. La operación deja registro en audit log (guardado en base de datos, no visible en UI en v1).
3. Navigator: Lista scrolleable de todos los casos del dataset + botón "Next Case" prominente.