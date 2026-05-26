# Metro Station Design Module

This package is the source-of-truth layer for the future station layout editor.

The pattern is:

1. `StationDesignDocument` stores topology, levels, editable elements, queues, and constraints.
2. `templates.py` creates starting topology choices such as two-level island platform, three-level transfer, and single-level terminal.
3. `validation.py` checks hard design limits before any layout reaches simulation.
4. `react_flow_adapter.py` projects the document into React Flow nodes/edges for a drag-and-drop editor, then maps accepted position/edge edits back onto the document.

The simulation and visual demo should not read React Flow state directly. React Flow is the editor adapter; `StationDesignDocument` is the business document.

Useful validation check:

```powershell
python -c "from sandbox.metro_station_sandbox.design import create_design, validate_design; d=create_design(); print(d.as_dict()['schema_version']); print(validate_design(d))"
```
