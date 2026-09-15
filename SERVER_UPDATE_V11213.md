# AMP XP / «АМПасадори» v1.12.1.3 — Domain Import Startup Hotfix

Причина падіння GitHub release smoke: після доменного refactor у `app/domain_services/bootstrap.py` залишилися імпорти `from .settlements` і `from .donations`, хоча ці модулі знаходяться на рівні `app/`. Після виправлення вони використовують `from ..settlements` / `from ..donations`. Додатково виправлено аналогічні приховані імпорти в `gamification.py` і `events.py`.

Production preflight доповнений AST-перевіркою relative imports у `app/domain_services`. Схема БД та зовнішня поведінка без змін.
