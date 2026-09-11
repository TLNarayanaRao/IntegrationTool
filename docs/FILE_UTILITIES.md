# Data and file utilities

Open **Window → XML Viewer**, **Window → JSON Viewer**, or **Window → Compare Files**. These tools use a dedicated Studio workspace above the orchestration editor, so a utility can remain open without changing the active Task.

## Large-file behavior

The desktop application gives the UI an opaque file handle rather than unrestricted filesystem access. It reads only the selected 256 KB, 1 MB, or 4 MB window. Previous and Next move through the file without retaining earlier windows. Browser mode applies the same behavior with `Blob.slice()`.

Each active window is editable. Desktop saves stream the untouched prefix and suffix through a temporary file and then replace the original, so even a very large file is not assembled in renderer memory. Navigation is locked while edits are unsaved. Browser mode downloads the edited result because web pages cannot overwrite the selected local file directly.

Complete XML or JSON files up to 16 MB can be validated and pretty-printed as a whole. Larger files use a tolerant pretty printer for the current bounded window, avoiding an unbounded parse tree or full-file string in renderer memory.

## XML Viewer

- Opens XML, XSD, and WSDL files.
- Pretty-prints well-formed complete documents.
- **Decode &lt; and &gt;** changes `&amp;lt;` and `&amp;gt;` into visible angle brackets in the display.
- Wraps long or minified lines by default so payload content stays visible; wrapping can be toggled from the toolbar.
- Searches the current file window.
- Saves edits or formatting back to the selected desktop file and provides Revert for unsaved changes.

## JSON Viewer

- Opens JSON and JSON Lines files.
- Pretty-prints and validates complete JSON documents.
- Uses bounded-window formatting for very large payloads.
- Wraps long or minified lines by default.
- Searches the current file window.
- Saves edits or formatting back to the selected desktop file and provides Revert for unsaved changes.

## Compare Files

- Accepts any two file types.
- Uses side-by-side aligned text rows for text files.
- Marks added, removed, and changed rows separately.
- Automatically displays binary or unknown content as hexadecimal and printable ASCII.
- Supports a differences-only view and synchronized window navigation.
- Allows individual difference rows—or all differences in the current window—to be selected and copied left-to-right or right-to-left.
- Provides a two-pane editing mode and independent **Save left** and **Save right** actions.
- Detects external file changes before saving and refuses to overwrite newer content.
- Renders at most 10,000 comparison rows per window to prevent unusually short-line files from creating an unbounded number of UI elements.
