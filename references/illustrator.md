# Illustrator backend

Read only when the user specifies Illustrator or this editor needs to be checked. Actually create or edit native objects, save the result, and read it back. Record provenance separately for independently generated SVGs, SVG imports saved as AI, and SVGs exported from the application.

## Documents and objects

On macOS, AppleScript can invoke Illustrator JSX scripts. First verify connectivity, coordinates, and text creation on a small scale, then perform the task. Use a clearly identified task document and preserve the user's existing content.

Map stable object-model IDs, selection groups, and drawing order to native layers, GroupItems, paths, and text. Objects on the same layer still need selection groups. SVG group or layer metadata may not become native layers; use the actual imported object structure as the authority.

Check coordinate and unit conversions between the document, artboard, and source image. Use editable text and choose fonts from those actually installed. Check the rendered results of gradients, rotation, clipping, and opacity, rather than merely confirming successful property assignments.

## Optional reference layer

Coordinate-based reconstruction does not require simulated mouse tracing. When tracing over a faded reference image, place and proportionally align it, set opacity, confirm visibility, then lock the reference layer and draw above it. Embedding an image can change its object type and handle; recheck the object, bounds, and opacity. During comparison, verify that the background does not cover the reference. Hide the reference for delivery as required and disclose its presence.

## Saving and validation

- After a timeout, inspect task logs, document state, and output state first. Determine whether the original script is still running before retrying to avoid duplicate creation.
- Check the actual file and read back the saved result. Log the actual stage and errors. Restore temporarily changed application settings when finished.
- Actually move representative imported objects and edit their text. Check all members, neighboring objects, and underlays. Record script queries, rendering checks, and native interaction checks separately.
- Run the rendering through the same difference-review loop. Native file format does not replace fidelity or editability acceptance.
