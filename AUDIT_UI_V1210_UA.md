AMP XP v1.22.0 — retains historical v1.21.0 evidence and baseline.
# UI/UX Audit — AMP XP v1.21.0

## Виявлені проблеми бази v1.20.3.1
- Інформаційна архітектура sidebar змішувала product, management та system tools у великій кількості секцій.
- Dashboard був операційно насиченим і не мав чіткого product-first рівня.
- Події використовували довгу inline create-form замість короткого CTA + dialog flow.
- Реєстрації були функціональні, але не виглядали як цілісний approval workspace.
- Ideas мали компактний board, але не discovery-модель з imagery/status hierarchy.
- Багато старих сторінок мали різний visual rhythm, хоча design-system layer вже існував.
- У продукті є значно більше protected admin/superadmin tools, ніж показано у mockups; redesign не повинен їх видаляти.

## Рішення
- Role-aware navigation layers.
- Product-first dashboard + окремі management/system zones.
- Reusable Product Experience patterns з префіксом `.product-*`.
- Semantic SVG mapping замість випадкових UI icons.
- Dialog-based event creation.
- Wider table/card layouts для 1280–1920 px.
- Glass only for shell/floating surfaces; main work cards залишаються читабельними.
- No-letter-breaking policy для buttons/tabs/chips/navigation.
