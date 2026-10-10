# UI/UX Audit v1.20.3.1

Під час аудиту v1.20.3 виявлено системні причини, а не лише окремі візуальні дефекти:

1. `refinement.css` містив `overflow-wrap: break-word` та `hyphens:auto` для широкого набору елементів. Це дозволяло браузеру розривати українські слова всередині кнопок/чіпів.
2. Глобальні `.severity-high/.severity-critical` у visual layer застосовували background до будь-якого елемента з таким класом, включно з цілою OperationalIssue card.
3. Desktop sidebar мав два controls: один у sidebar header і дубль у topbar.
4. Старий toast logic дублював усі inline alerts і розміщував копії зверху праворуч незалежно від того, чи повідомлення transient або persistent.
5. Modal widths накопичили декілька override-шарів і могли бути завеликими.
6. Overview/KPI cards показували числа без semantic icon cue; частина навігації повторно використовувала ті самі іконки для різних сутностей.
7. Hover shadows на кількох шарах накладались одна на одну та створювали надмірний glow.

v1.20.3.1 виправляє ці причини централізовано через final polish layer, semantic icon additions, scoped severity selectors та один toast/dialog policy.
