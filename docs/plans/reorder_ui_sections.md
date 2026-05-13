# Plan - Reorder UI Sections

Move the "Versions" section below the "Logs" section in the Decky plugin sidebar.

## Problem Definition
The user wants the "Logs" section to appear above the "Versions" section in the plugin's UI for better accessibility to frequent log viewing tasks.

## Architecture Overview
The frontend is a React component rendered within Decky Loader. The layout is defined in `src/index.tsx` using `@decky/ui` components like `PanelSection`.

## Proposed Solution
Swap the order of the two `<PanelSection>` components in the `Content` component's return statement in `src/index.tsx`.

## Key Files & Context
- `src/index.tsx`: Contains the main UI layout.

## Implementation Steps
1.  Locate the `<PanelSection title="Versions">` and `<PanelSection title="Logs">` blocks in `src/index.tsx`.
2.  Move the "Logs" section block before the "Versions" section block.

## Verification & Testing
1.  **Build Check**: Run `pnpm run build` (or the equivalent build command from `package.json`) to ensure the TypeScript/React code still compiles.
2.  **Lint Check**: Run any available frontend linting if applicable.
3.  **Manual Verification**: If a device or emulator were available, I would verify the visual order. Since it's a direct swap of independent components, the risk is minimal.
