# UI/UX Audit — AMP XP v1.20.3

## Виявлені першопричини
1. Частина legacy CSS використовувала descendant selectors на кшталт `.report-feature-grid span`, через що SVG wrapper `.icon` отримував стилі tile і перетворювався на порожній rounded block.
2. Різні покоління CSS задавали конкуруючі `max-width`, тому реєстрації, команда, ідеї, серії, сезони та адміністративні панелі іноді займали лише частину доступної ширини.
3. Chips/buttons у вузьких колонках успадковували агресивні wrapping rules, що спричиняло перенос окремих слів або букв.
4. Action groups мали різні gap/margin patterns; у складних картках кнопки могли виглядати «приклеєними» до сусідніх блоків.
5. Modal editing працював функціонально, але не мав єдиного sizing policy для коротких і великих форм.
6. Help Center quick cards реалізовували сценарій через заповнення search query, а не прямий перехід до категорії.
7. Reward cards без media мали порожню поверхню замість зрозумілого стандартного visual placeholder.

## Рішення
- Last-layer CSS module `refinement.css` із direct-child selectors, predictable wrapping та module-wide grid rules.
- Єдиний semantic icon layer через `_ui_macros.html`.
- Full-width layout policy з content-wide 1720px та окремими readable text limits.
- Unified modal/button/form/table/card policies.
- Progressive motion із reduced-motion fallback.
- Direct category navigation у Help Center.
