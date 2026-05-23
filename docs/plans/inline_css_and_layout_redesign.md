# Plan - Inline CSS and Layout Redesign

## Problem Definition
The user wants to simplify the styling setup by completely deleting the external `src/index.css` file and inlining all CSS layout and typography properties. 

Additionally, they want the following layout improvements:
1. **Versions panel**: Add more space (gap) between the version rows.
2. **Last Operation field**: Change this to a 2-column inline layout (label on left, value on right) where the status message wraps naturally, with the timestamp appended at the end of the text in parentheses, e.g. `(timestamp)`.

## Architecture Overview
1. **CSS Deletion**:
   - Delete [src/index.css](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.css).
   - Remove `import "./index.css";` from [src/index.tsx](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/src/index.tsx).
   - Clean up `rollup.config.js` to remove the custom `cssInjectedPlugin()` from the plugins array.
2. **Versions Field Redesign**:
   - Set the versions list container `gap` from `"4px"` to `"8px"`.
   - Apply inline styles for layout: `style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "8px", minWidth: 0, textAlign: "left", fontSize: "12px", color: "#cbd5e1" }}`.
3. **Last Operation Redesign**:
   - Set the `Field` props:
     - Change `childrenLayout` from `"below"` to `"inline"`.
     - Change `childrenContainerWidth` from `"max"` to `"max"` (to let the children take up the remaining width).
     - Remove obsolete classes and positive/negative margins.
   - Refactor the inner value markup:
     - Render the message text and timestamp inline inside a single wrapper `div`.
     - Set the timestamp to render as a `span` appended to the text, wrapped in parentheses, e.g. `(HH:MM:SS)`.
     - Add inline style properties to allow wrapping: `style={{ fontSize: "12px", color: selectedHistory.status === "failed" ? "#f87171" : "#cbd5e1", whiteSpace: "normal", wordBreak: "break-word" }}`.
4. **Toggles Layout**:
   - Since we are deleting `src/index.css`, we must inline the styles for `.sdh-ludusavi-full-width-toggle`:
     - We can wrap each toggle or apply style prop to the toggle item, or wrap them in a container that applies the negative margins/padding.
     - Let's check how the full width toggle is rendered:
       ```tsx
       function FullWidthToggle({ children }: { children: ReactNode }) {
         return (
           <div
             style={{
               display: "block",
               marginLeft: "-32px",
               marginRight: "-32px"
             }}
           >
             <div style={{ boxSizing: "border-box", width: "100%", paddingLeft: "32px", paddingRight: "32px" }}>
               {children}
             </div>
           </div>
         );
       }
       ```
       This perfectly replaces `.sdh-ludusavi-full-width-toggle` and `.sdh-ludusavi-full-width-toggle > *` from `index.css`!

## Core Data Structures
None.

## Public Interfaces
None.

## Dependency Requirements
None.

## Testing Strategy
1. **Red**: Update [tests/test_frontend_static.py](file:///home/beallio/Dropbox/Scripts/SDH-ludusavi/tests/test_frontend_static.py):
   - Remove assertions checking for `.css` rules and strings.
   - Verify that the CSS file import `import "./index.css";` is not present in the source.
   - Assert the new inline layout properties:
     - `childrenLayout="inline"` on Last Operation.
     - `style={{ fontSize: "12px", color: selectedHistory.status === "failed"` or similar inline styling.
     - Parenthetical timestamp `({selectedHistory.timestamp` or equivalent in the inline text wrapper.
   - Verify test failure under `pytest`.
2. **Green**: Implement the layout changes in `src/index.tsx`, delete `src/index.css`, and update `rollup.config.js`.
3. **Refactor & Validate**: Run `./run.sh uv run pytest` and ensure all tests pass. Build the plugin and verify `out/SDH-Ludusavi.zip` packages successfully.
