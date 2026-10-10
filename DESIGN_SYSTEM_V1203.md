# AMP XP v1.20.3 — Design System Refinement

Версія: 1.20.3

## Layout
- wide application container: 1720px;
- standard visual sections use full available content width;
- prose remains constrained by readable character lengths;
- responsive cards: 4/3/2/1 columns depending on viewport and component.

## Icons
Semantic SVG icon macro remains the single icon source. v1.20.3 adds registration, user-check, team, event, calendar-start/end, quest, volunteer, journey, catalog, reward, history and settings-section symbols. System UI must not use emoji as control icons.

## Components
Buttons: primary / secondary / danger / icon.
Cards: hero / KPI / module / item / status / reward / achievement.
Forms: consistent 46px controls, labels, helper/error spacing.
Modals: standard 760px, editor 860px, wide 980px maximum, all constrained to viewport.
Tables: full width, scroll containment, non-colliding action groups.

## Motion
Subtle entrance and hover motion uses `--motion-fast`, `--motion-base`, `--motion-slow`. `prefers-reduced-motion` disables non-essential motion.
