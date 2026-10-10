# AMP XP Design System v1.20.3.1

## Typography and wrapping
- Natural text wraps only at spaces.
- `word-break: normal`, `overflow-wrap: normal`, `hyphens: none` for product UI text.
- Buttons, tabs, pills, badges and action controls use `white-space: nowrap` and never split words.

## Shadows
Patch release reduces elevation intensity:
- cards: `--shadow-sm`;
- hover: `--shadow-md`;
- modals: compact `--shadow-modal`;
- primary buttons use a small accent shadow rather than glow.

## Icons
System icons remain SVG, stroke-based and semantic. v1.20.3.1 adds dedicated icons for Dashboard, Tasks, XP, Opportunity, Streak, Season, Gamification and Notifications.

## Controls
Action groups use a 12px horizontal gap and 10px row gap. Controls keep one-line labels; the container wraps before the word does.

## Operations
Severity is communicated by left accent border + badge. The entire card is never filled with a severity color.
