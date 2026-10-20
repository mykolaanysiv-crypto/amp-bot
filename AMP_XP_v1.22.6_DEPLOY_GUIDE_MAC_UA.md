# AMP XP v1.22.6 RC — безпечна інтеграція на Mac

## 0. Передумови

ZIP створено **без підтвердженого SHA GitHub `main`**. Не перезаписуйте ним робочу директорію і не запускайте production деплой без пройдених тестів.

## 1. Перевірка актуального локального стану

```bash
cd ~/Downloads/amp-bot-v1220
git status --short
git branch --show-current
git fetch origin
git rev-parse origin/main
git show origin/main:VERSION.txt
```

Якщо `git status --short` не порожній — не міняйте гілку та спочатку збережіть незакомічені зміни окремим комітом або резервною копією.

## 2. Окреме чисте розпакування

```bash
mkdir -p ~/Downloads/AMP_XP_v1.22.6_RC_REVIEW
unzip -q ~/Downloads/AMP_XP_v1.22.6_RELEASE_CANDIDATE_FULL_SOURCE.zip -d ~/Downloads/AMP_XP_v1.22.6_RC_REVIEW
cd ~/Downloads/AMP_XP_v1.22.6_RC_REVIEW
cat VERSION.txt
python3 -m scripts.build_admin_css --check
```

## 3. Порівняння (не копіювати бездумно)

```bash
cd ~/Downloads/amp-bot-v1220
git diff --no-index --stat . ~/Downloads/AMP_XP_v1.22.6_RC_REVIEW || true
```

Перегляньте відмінності. Нові зміни треба переносити **вибірково**, щоб не стерти код, що з'явився в `main` після підготовки вихідного ZIP.

## 4. Гілка після підтвердження відмінностей

```bash
cd ~/Downloads/amp-bot-v1220
git switch -c release/v1.22.6 origin/main
```

Вручну інтегруйте узгоджені зміни з RC у цю гілку. Не переносіть усю архівну директорію через `rsync --delete`.

## 5. Перевірки у вашому встановленому .venv

```bash
source .venv/bin/activate
python -m scripts.build_admin_css --check
python -m compileall -q app scripts
python -m scripts.production_preflight
python -m scripts.release_consistency_check
python -m pytest -q --ignore=tests/integration
```

Інтеграційні тести запускайте лише на окремій PostgreSQL 18. Перед merge потрібні GitHub Actions, перегляд мобільних сторінок, резервна копія production БД і **перевірка відновлення в ізольовану БД**. Жоден із цих кроків у наданому RC не підтверджений.

Після всіх перевірок: `git diff --check`, коміт у release-гілку, PR у `main`, рев'ю, CI; деплой тільки після окремого погодження. Універсальна команда злиття тут навмисно не надана.
