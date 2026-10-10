# AMP XP v1.20.1 — Visual Experience Design System

Version: **1.20.1**.

## Напрямок

AMP XP використовує civic-tech / youth SaaS visual language: професійний, енергійний і впізнаваний, але не дитячий і не декоративно перевантажений.

## Design layers

```text
legacy.css       compatibility
    ↓
tokens.css       semantic variables / gradients / elevations
    ↓
base.css         typography / accessibility baseline
    ↓
layout.css       app shell / responsive layout
    ↓
components.css   reusable controls/components
    ↓
experience.css   v1.20.1 emotional + profile/help/dialog layer
    ↓
utilities.css    small helpers
```

`scripts/build_admin_css.py` детерміновано збирає `admin.css`.

## Brand accents

v1.20.1 використовує semantic AMP accents (`--color-accent-cyan`, `--color-accent-lime`, `--color-accent-violet`, `--color-accent-coral`) і gradients (`--gradient-brand`, `--gradient-brand-soft`, `--gradient-energy`, `--gradient-warm`). Акцент не повинен замінювати status semantics.

## Layout rules

- Загальний content max контролюється design tokens.
- `.page-shell` у v1.20.1 обмежено до 1480 px для комфортного читання.
- Довгі H1 використовують `clamp()` та safe wrapping.
- Action rows wrap-яться, а на mobile переходять у доступну stack/flex схему.
- Data-heavy tables можуть використовувати ширший container, але не повинні створювати body-level horizontal overflow.

## Dialog pattern

Use native `<dialog class="amp-modal">`:
- header + title + short context;
- body;
- footer/actions;
- explicit close button;
- system Esc behavior;
- focus return;
- backdrop;
- reduced motion;
- backend CSRF/permissions remain mandatory.

## User cabinet

Profile hero, avatar, bio, contacts, badge gallery, participation stats та security controls мають виглядати як один продукт. Avatar media — staff-private.

## Help Center

Task-oriented cards, quick-start actions, search, FAQ та release updates. Content remains server-rendered; JS лише фільтрує вже доступний DOM.

## Icons

Use `_ui_macros.html` inline SVG system. Emoji не використовуються як primary navigation/component icon. Historical user-generated/content emoji можуть залишатися як content, якщо це не control semantics.
