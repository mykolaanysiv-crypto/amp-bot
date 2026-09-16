from __future__ import annotations

from io import BytesIO
from math import ceil
from typing import Any

def _safe_sheet_title(title: str, used: set[str]) -> str:
    cleaned = "".join(ch for ch in title if ch not in '[]:*?/\\').strip() or "Аналітика"
    base = cleaned[:31]
    candidate = base
    i = 2
    while candidate in used:
        suffix = f" {i}"
        candidate = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(candidate)
    return candidate

def analytics_excel(data: dict[str, Any], metric_key: str | None = None) -> bytes:
    """Create an aggregate analytics workbook, with a chart on every metric sheet."""
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill, Side, Border
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    default = wb.active
    wb.remove(default)
    used: set[str] = set()

    if metric_key is None:
        ws = wb.create_sheet(_safe_sheet_title("Зведення", used))
        ws.append(["АМПасадори — агрегована аналітика", ""])
        ws.append(["Сформовано", data["generated_at"].strftime("%d.%m.%Y %H:%M")])
        ws.append(["Примітка", data["privacy_note"]])
        ws.append([])
        ws.append(["Показник", "Значення"])
        summary_labels = [
            ("Зареєстровані учасники", "participants"),
            ("Нові цього місяця", "new_this_month"),
            ("Когорта — зареєструвалися", "cohort_registered"),
            ("Когорта — прийшли 1 раз", "cohort_first_visit"),
            ("Когорта — повернулися", "cohort_returned"),
            ("Когорта — регулярні", "cohort_regular"),
            ("Когорта — АМПасадори", "cohort_ambassadors"),
            ("Повернення за 30 днів, %", "retention_30_pct"),
            ("Повернення за 90 днів, %", "retention_90_pct"),
            ("Середній engagement score", "engagement_average"),
            ("Залученість 75–100", "engagement_high"),
            ("Активні за 30 днів", "active30"),
            ("Активні за 90 днів", "active90"),
            ("Підтверджені відвідування", "visits"),
            ("Середня відвідуваність події", "avg_attendance"),
            ("Зворотний зв’язок — відповідей", "feedback_responses"),
            ("Зворотний зв’язок — середня оцінка", "feedback_avg_rating"),
            ("Висока оцінка 4–5, %", "feedback_high_rating_pct"),
            ("Було корисно, %", "feedback_useful_pct"),
            ("Нові знання, %", "feedback_new_knowledge_pct"),
            ("Почувалися безпечно, %", "feedback_safe_pct"),
            ("Хочуть прийти ще, %", "feedback_return_pct"),
            ("Волонтерські години", "volunteer_hours"),
            ("Реалізовані ідеї", "implemented_ideas"),
            ("Нараховано XP", "total_xp_awarded"),
            ("Проходжень опитувань за 12 тижнів", "survey_responses_12w"),
            ("Отримано бейджів за 12 тижнів", "badges_12w"),
            ("Заморожених серій зараз", "frozen_streaks"),
            ("Днів заморозки використано цього кварталу", "freeze_days_quarter"),
        ]
        for title, key in summary_labels:
            ws.append([title, data["summary"][key]])
        ws.column_dimensions["A"].width = 36
        ws.column_dimensions["B"].width = 22
        ws.freeze_panes = "A5"

    keys = [metric_key] if metric_key else data["metric_order"]
    for key in keys:
        metric = data["metrics"].get(key)
        if not metric:
            continue
        ws = wb.create_sheet(_safe_sheet_title(metric["short"], used))
        ws.append([metric["title"], ""])
        ws.append(["Опис", metric["description"]])
        ws.append(["Сформовано", data["generated_at"].strftime("%d.%m.%Y %H:%M")])
        ws.append([])
        ws.append(["Категорія / період", metric["value_label"], "Додатково"])
        for row in metric["rows"]:
            ws.append([row.get("label", ""), row.get("display_value", row.get("value", 0)), row.get("secondary", "")])

        if metric["kind"] == "heatmap":
            from openpyxl.formatting.rule import ColorScaleRule
            start_row = ws.max_row + 2
            ws.cell(start_row, 1, "День / година")
            for col, hour in enumerate(metric.get("hours", []), 2):
                ws.cell(start_row, col, hour)
            for r_idx, day in enumerate(metric.get("days", []), start_row + 1):
                ws.cell(r_idx, 1, day)
                for c_idx, value in enumerate(metric.get("matrix", [])[r_idx - start_row - 1], 2):
                    ws.cell(r_idx, c_idx, value)
            if metric.get("hours") and metric.get("days"):
                first = ws.cell(start_row + 1, 2).coordinate
                last = ws.cell(start_row + len(metric["days"]), 1 + len(metric["hours"])).coordinate
                ws.conditional_formatting.add(f"{first}:{last}", ColorScaleRule(start_type="min", start_color="FFFFFF", mid_type="percentile", mid_value=50, mid_color="9DE5EA", end_type="max", end_color="06AEBB"))
                for col in range(2, 2 + len(metric["hours"])):
                    ws.column_dimensions[get_column_letter(col)].width = 7
        else:
            chart_cls = DoughnutChart if metric["kind"] == "doughnut" else (LineChart if metric["kind"] == "line" else BarChart)
            chart = chart_cls()
            chart.title = metric["title"]
            chart.height = 9
            chart.width = 18
            if metric["rows"]:
                data_ref = Reference(ws, min_col=2, min_row=5, max_row=5 + len(metric["rows"]))
                cats_ref = Reference(ws, min_col=1, min_row=6, max_row=5 + len(metric["rows"]))
                chart.add_data(data_ref, titles_from_data=True)
                chart.set_categories(cats_ref)
                if hasattr(chart, "y_axis"):
                    chart.y_axis.title = metric["value_label"]
            ws.add_chart(chart, "E5")
        ws.freeze_panes = "A6"
        ws.column_dimensions["A"].width = 42
        ws.column_dimensions["B"].width = 18
        ws.column_dimensions["C"].width = 24

    thin = Side(style="thin", color="D8E2E5")
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in ws[1]:
            cell.font = Font(bold=True, size=14)
        for row_num in [5]:
            if ws.max_row >= row_num:
                for cell in ws[row_num]:
                    if cell.value is not None:
                        cell.font = Font(bold=True)
                        cell.fill = PatternFill("solid", fgColor="DFF7F8")
                        cell.border = Border(bottom=thin)
        for col_idx in range(1, min(ws.max_column, 3) + 1):
            width = max(12, min(44, max((len(str(ws.cell(r, col_idx).value or "")) for r in range(1, min(ws.max_row, 100) + 1)), default=12) + 2))
            ws.column_dimensions[get_column_letter(col_idx)].width = width

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()

def _wrap_label(text: str, width: int = 28) -> str:
    words = str(text).split()
    if not words:
        return ""
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines)

def analytics_pdf(data: dict[str, Any], metric_key: str | None = None) -> bytes:
    """Create a printable multi-page PDF without clipping long KPI sets or labels."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    plt.rcParams["font.family"] = "DejaVu Sans"
    bio = BytesIO()

    def _footer(fig) -> None:
        fig.text(0.08, 0.035, f"АМПасадори • сформовано {data['generated_at'].strftime('%d.%m.%Y %H:%M')}", fontsize=8)

    with PdfPages(bio) as pdf:
        if metric_key is None:
            summary = data["summary"]
            rows = [
                ("Зареєстровані учасники", summary["participants"]),
                ("Нові цього місяця", summary["new_this_month"]),
                ("Когорта: прийшли 1 раз", summary["cohort_first_visit"]),
                ("Когорта: повернулися", summary["cohort_returned"]),
                ("Когорта: регулярні", summary["cohort_regular"]),
                ("Когорта: АМПасадори", summary["cohort_ambassadors"]),
                ("Повернення за 30 днів", f"{summary['retention_30_pct']:g}%"),
                ("Повернення за 90 днів", f"{summary['retention_90_pct']:g}%"),
                ("Індекс залученості — середній", f"{summary['engagement_average']:g}/100"),
                ("Залученість 75–100", summary["engagement_high"]),
                ("Активні за 30 днів", summary["active30"]),
                ("Активні за 90 днів", summary["active90"]),
                ("Підтверджені відвідування", summary["visits"]),
                ("Середня відвідуваність події", summary["avg_attendance"]),
                ("Зворотний зв’язок — відповідей", summary["feedback_responses"]),
                ("Зворотний зв’язок — середня оцінка", summary["feedback_avg_rating"]),
                ("Нові знання", f"{summary['feedback_new_knowledge_pct']:g}%"),
                ("Почувалися безпечно", f"{summary['feedback_safe_pct']:g}%"),
                ("Волонтерські години", summary["volunteer_hours"]),
                ("Реалізовані ідеї", summary["implemented_ideas"]),
                ("Нараховано XP", summary["total_xp_awarded"]),
                ("Опитування за 12 тижнів", summary["survey_responses_12w"]),
                ("Бейджі за 12 тижнів", summary["badges_12w"]),
                ("Заморожені серії", summary["frozen_streaks"]),
            ]
            # 12 rows/page guarantees readable spacing on A4 portrait.
            for page_idx in range(0, len(rows), 12):
                chunk = rows[page_idx:page_idx + 12]
                fig = plt.figure(figsize=(8.27, 11.69))
                title = "АМПасадори — агрегована аналітика" if page_idx == 0 else "Аналітика — продовження"
                fig.text(0.08, 0.93, title, fontsize=19, weight="bold")
                fig.text(0.08, 0.89, f"Сформовано: {data['generated_at'].strftime('%d.%m.%Y %H:%M')}", fontsize=10)
                if page_idx == 0:
                    fig.text(0.08, 0.845, data["privacy_note"], fontsize=8.5, wrap=True)
                    y = 0.76
                else:
                    y = 0.82
                for title_text, value in chunk:
                    fig.text(0.10, y, _wrap_label(title_text, 42), fontsize=10.5, va="center")
                    fig.text(0.87, y, str(value), fontsize=12, weight="bold", ha="right", va="center")
                    y -= 0.058
                _footer(fig)
                pdf.savefig(fig)
                plt.close(fig)

        keys = [metric_key] if metric_key else data["metric_order"]
        for key in keys:
            metric = data["metrics"].get(key)
            if not metric:
                continue
            labels = metric["labels"]
            values = metric["values"]
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            fig.suptitle(metric["title"], fontsize=17, weight="bold", y=0.97)
            fig.text(0.08, 0.91, _wrap_label(metric["description"], 125), fontsize=9, wrap=True)
            if metric["kind"] == "heatmap":
                matrix = metric.get("matrix") or [[0] * 24 for _ in range(7)]
                image = ax.imshow(matrix, aspect="auto", interpolation="nearest", cmap="YlGnBu")
                ax.set_yticks(range(len(metric.get("days", []))))
                ax.set_yticklabels(metric.get("days", []))
                ax.set_xticks(range(24))
                ax.set_xticklabels([f"{h:02d}" for h in range(24)], fontsize=8)
                ax.set_xlabel("Година")
                ax.set_ylabel("День тижня")
                cbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
                cbar.set_label("Кількість дій")
            elif not labels:
                ax.text(0.5, 0.5, "Даних поки немає", ha="center", va="center", fontsize=16)
                ax.axis("off")
            elif metric["kind"] == "doughnut":
                ax.pie(values, labels=[_wrap_label(x, 22) for x in labels], autopct=lambda p: f"{p:.0f}%" if p >= 3 else "", startangle=90, wedgeprops={"width": 0.45})
                ax.axis("equal")
            elif metric["kind"] == "line":
                x = list(range(len(labels)))
                ax.plot(x, values, marker="o", linewidth=2)
                ax.set_xticks(x)
                ax.set_xticklabels([_wrap_label(x, 16) for x in labels], rotation=35, ha="right")
                ax.set_ylabel(metric["value_label"])
                ax.grid(axis="y", alpha=0.2)
            else:
                horizontal = len(labels) > 7 or any(len(str(x)) > 22 for x in labels)
                if horizontal:
                    y = list(range(len(labels)))
                    ax.barh(y, values)
                    ax.set_yticks(y)
                    ax.set_yticklabels([_wrap_label(x, 28) for x in labels])
                    ax.invert_yaxis()
                    ax.set_xlabel(metric["value_label"])
                    ax.grid(axis="x", alpha=0.2)
                else:
                    x = list(range(len(labels)))
                    ax.bar(x, values)
                    ax.set_xticks(x)
                    ax.set_xticklabels([_wrap_label(x, 18) for x in labels], rotation=20, ha="right")
                    ax.set_ylabel(metric["value_label"])
                    ax.grid(axis="y", alpha=0.2)
            _footer(fig)
            fig.tight_layout(rect=[0.04, 0.06, 0.98, 0.88])
            pdf.savefig(fig)
            plt.close(fig)
    return bio.getvalue()

def analytics_bot_text(data: dict[str, Any]) -> str:
    s = data["summary"]
    return (
        "📊 <b>Аналітика АМП</b>\n"
        f"Станом на {data['generated_at'].strftime('%d.%m.%Y %H:%M')}\n\n"
        f"👥 Учасників: <b>{s['participants']}</b>\n"
        f"🆕 Нові цього місяця: <b>{s['new_this_month']}</b>\n"
        f"🔁 Повернення 30/90: <b>{s['retention_30_pct']:g}% / {s['retention_90_pct']:g}%</b>\n"
        f"📈 Індекс залученості: <b>{s['engagement_average']:g}/100</b>\n"
        f"⚡ Активні 30 днів: <b>{s['active30']}</b>\n"
        f"📈 Активні 90 днів: <b>{s['active90']}</b>\n"
        f"📅 Підтверджених відвідувань: <b>{s['visits']}</b>\n"
        f"👤 Середня відвідуваність: <b>{s['avg_attendance']}</b>\n"
        f"⭐ Зворотний зв’язок: <b>{s['feedback_avg_rating']:g}/5</b> • нові знання <b>{s['feedback_new_knowledge_pct']:g}%</b> • безпека <b>{s['feedback_safe_pct']:g}%</b>\n"
        f"⏱ Волонтерських годин: <b>{s['volunteer_hours']:g}</b>\n"
        f"✨ Нараховано XP: <b>{s['total_xp_awarded']}</b>\n"
        f"💡 Реалізованих ідей: <b>{s['implemented_ideas']}</b>\n"
        f"📋 Проходжень опитувань за 12 тижнів: <b>{s['survey_responses_12w']}</b>\n"
        f"🏅 Отримано бейджів за 12 тижнів: <b>{s['badges_12w']}</b>\n"
        f"🧊 Заморожених серій зараз: <b>{s['frozen_streaks']}</b>\n\n"
        "🔐 Категорії вразливості у звітах доступні лише в агрегованому вигляді."
    )

def analytics_png(data: dict[str, Any], metric_key: str | None = None) -> bytes:
    """Create a shareable PNG snapshot of one metric or the full dashboard."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = "DejaVu Sans"
    bio = BytesIO()

    def draw_metric(ax, metric: dict[str, Any], compact: bool = False) -> None:
        labels = metric["labels"]
        values = metric["values"]
        ax.set_title(metric['short'], fontsize=11 if compact else 15, weight="bold")
        if not labels:
            ax.text(0.5, 0.5, "Даних поки немає", ha="center", va="center")
            ax.axis("off")
            return
        if metric["kind"] == "heatmap":
            matrix = metric.get("matrix") or [[0] * 24 for _ in range(7)]
            ax.imshow(matrix, aspect="auto", interpolation="nearest", cmap="YlGnBu")
            ax.set_yticks(range(len(metric.get("days", []))))
            ax.set_yticklabels(metric.get("days", []), fontsize=7 if compact else 9)
            ax.set_xticks(range(24))
            ax.set_xticklabels([f"{h:02d}" for h in range(24)], fontsize=6 if compact else 8)
        elif metric["kind"] == "doughnut":
            ax.pie(values, labels=[_wrap_label(x, 16 if compact else 22) for x in labels], autopct=lambda p: f"{p:.0f}%" if p >= 4 else "", startangle=90, wedgeprops={"width": 0.45})
            ax.axis("equal")
        elif metric["kind"] == "line":
            x = list(range(len(labels)))
            ax.plot(x, values, marker="o", linewidth=2)
            ax.set_xticks(x)
            ax.set_xticklabels([_wrap_label(x, 10 if compact else 16) for x in labels], rotation=35, ha="right", fontsize=7 if compact else 9)
            ax.grid(axis="y", alpha=0.2)
        else:
            horizontal = len(labels) > 6 or any(len(str(x)) > 18 for x in labels)
            if horizontal:
                y = list(range(len(labels)))
                ax.barh(y, values)
                ax.set_yticks(y)
                ax.set_yticklabels([_wrap_label(x, 18 if compact else 28) for x in labels], fontsize=7 if compact else 9)
                ax.invert_yaxis()
                ax.grid(axis="x", alpha=0.2)
            else:
                x = list(range(len(labels)))
                ax.bar(x, values)
                ax.set_xticks(x)
                ax.set_xticklabels([_wrap_label(x, 11 if compact else 18) for x in labels], rotation=25, ha="right", fontsize=7 if compact else 9)
                ax.grid(axis="y", alpha=0.2)

    if metric_key:
        metric = data["metrics"].get(metric_key)
        if not metric:
            raise KeyError(metric_key)
        fig, ax = plt.subplots(figsize=(12, 7), dpi=150)
        draw_metric(ax, metric)
        fig.suptitle("АМПасадори • Аналітика", fontsize=18, weight="bold", y=0.98)
        fig.text(0.06, 0.02, f"Сформовано {data['generated_at'].strftime('%d.%m.%Y %H:%M')} • агреговані дані", fontsize=8)
        fig.tight_layout(rect=[0.03, 0.05, 0.98, 0.93])
    else:
        keys = data["metric_order"]
        cols = 2
        rows = ceil(len(keys) / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(14, rows * 4.4), dpi=130)
        axes_list = list(axes.flat) if hasattr(axes, "flat") else [axes]
        for ax, key in zip(axes_list, keys):
            draw_metric(ax, data["metrics"][key], compact=True)
        for ax in axes_list[len(keys):]:
            ax.axis("off")
        s = data["summary"]
        fig.suptitle(
            f"АМПасадори • Аналітика\nУчасники {s['participants']} • активні 30 днів {s['active30']} • відвідування {s['visits']} • години {s['volunteer_hours']:g}",
            fontsize=17, weight="bold", y=0.995,
        )
        fig.text(0.03, 0.008, f"Сформовано {data['generated_at'].strftime('%d.%m.%Y %H:%M')} • {data['privacy_note']}", fontsize=7)
        fig.tight_layout(rect=[0.02, 0.025, 0.98, 0.96])
    fig.savefig(bio, format="png", bbox_inches="tight")
    plt.close(fig)
    return bio.getvalue()
