# Expanded-state layout refinement

The project owner's screenshots revealed gaps in the October 31 implementation: legacy button styles overrode the workspace styles, selector focus rings overlapped labels, expanded forms lacked hierarchy, and tree controls occupied the graph viewport.

Changes:
- Separate tree controls from the scrollable graph; keep the selected-person summary in a stable footer instead of floating over it.
- Fit the hierarchy to actual card extents rather than the legacy minimum 1280px canvas. Preserve the time-aligned layout's coordinate system.
- Normalize finder buttons, focus outlines, section headings, and spacing above controls.
- Label all place fields permanently and use a responsive two-column form. Keep place editing full-width rather than reserving an empty side column.
- Extend browser checks to cover expanded view options, selector label clearance, small-tree centering/readability, and expanded mobile place forms.

The existing backend, form field names, authorization, and submission handlers are unchanged. This is a correction based on direct visual feedback, not a measured usability study. Screenshots use fictional local test records.

The owner preferred the original indigo-blue identity to the sage palette. Restored indigo headings, primary actions, selected navigation, and blue-tinted surfaces while retaining the warm canvas and corrected layouts. This color preference does not reinstate the old dashboard or duplicate calls to action.
