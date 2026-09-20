from __future__ import annotations

from copy import copy, deepcopy
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import re
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection
from docx import Document

from .model_domains import Event, EventRegistration, User
from .profile_data import gender_label, media_consent_label
from .ui_labels import label, event_registration_status_label


# Human-friendly aliases used in donor forms. Matching is deliberately tolerant:
# punctuation, line breaks and repeated spaces are ignored.
HEADER_ALIASES: dict[str, set[str]] = {
    "number": {"№", "номер", "no", "n", "зп", "пп", "№ з/п", "№ п/п"},
    "amp_id": {"id amp", "amp id", "id амп", "амп id", "ід амп", "код учасника", "id учасника"},
    "full_name": {"піб", "п.і.б.", "прізвище ім'я", "прізвище та ім'я", "ім'я та прізвище", "full name", "name"},
    "last_name": {"прізвище", "surname", "last name"},
    "first_name": {"ім'я", "ім’я", "name first", "first name"},
    "birth_date": {"дата народження", "date of birth", "dob"},
    "age": {"вік", "age"},
    "gender": {"стать", "гендер", "gender"},
    "phone": {"телефон", "номер телефону", "phone", "phone number", "контактний телефон"},
    "email": {"email", "e-mail", "електронна пошта", "ел. пошта"},
    "settlement": {"населений пункт", "місце проживання", "громада", "settlement", "location"},
    "telegram": {"telegram", "телеграм", "нік telegram", "username"},
    "status": {"статус", "статус участі", "attendance status"},
    "registered_at": {"дата реєстрації", "реєстрація", "registered at"},
    "checkin_at": {"час відмітки", "відмітка", "check-in", "checkin"},
    "confirmed_at": {"підтверджено", "час підтвердження", "confirmed at", "attendance confirmed"},
    "signature": {
        "цифровий код", "код підтвердження", "цифровий код підтвердження",
        "sha код", "sha-256", "підпис", "signature", "attendance code", "digital confirmation code", "signature code",
    },
    "media_consent": {"згода на фото", "згода фото відео", "згода на фото/відео", "media consent"},
}

EVENT_PLACEHOLDERS = {
    "{{event_title}}": lambda e, count: e.title,
    "{{event_date}}": lambda e, count: e.starts_at.strftime("%d.%m.%Y"),
    "{{event_time}}": lambda e, count: e.starts_at.strftime("%H:%M"),
    "{{event_datetime}}": lambda e, count: e.starts_at.strftime("%d.%m.%Y %H:%M"),
    "{{event_location}}": lambda e, count: e.location or "АМП",
    "{{event_xp}}": lambda e, count: str(e.xp_reward),
    "{{participants_count}}": lambda e, count: str(count),
}


def _norm(value: object) -> str:
    text = str(value or "").replace("’", "'").replace("ʼ", "'").lower().strip()
    text = re.sub(r"[\n\r\t]+", " ", text)
    text = re.sub(r"[^0-9a-zа-яіїєґ'№]+", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _field_for_header(value: object) -> str | None:
    n = _norm(value)
    if not n:
        return None
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            a = _norm(alias)
            if n == a or (len(a) >= 4 and a in n):
                return field
    return None


def _age(birth_date: date | None, on_date: date) -> int | None:
    if not birth_date:
        return None
    return on_date.year - birth_date.year - ((on_date.month, on_date.day) < (birth_date.month, birth_date.day))


def _participant_values(index: int, reg: EventRegistration, user: User, event: Event, *, include_sensitive: bool = True) -> dict[str, object]:
    return {
        "number": index,
        "amp_id": f"АМП-{user.id:04d}",
        "full_name": user.full_name or "",
        "last_name": user.last_name or "",
        "first_name": user.first_name or "",
        "birth_date": user.birth_date.strftime("%d.%m.%Y") if (include_sensitive and user.birth_date) else "",
        "age": _age(user.birth_date, event.starts_at.date()),
        "gender": gender_label(user.gender) if include_sensitive else "",
        "phone": (user.phone or "") if include_sensitive else "",
        "email": (user.email or "") if include_sensitive else "",
        "settlement": user.settlement or "",
        "telegram": f"@{user.username}" if user.username else "",
        "status": event_registration_status_label(reg.status),
        "registered_at": reg.registered_at.strftime("%d.%m.%Y %H:%M") if reg.registered_at else "",
        "checkin_at": reg.checkin_at.strftime("%d.%m.%Y %H:%M") if reg.checkin_at else "",
        "confirmed_at": reg.confirmed_at.strftime("%d.%m.%Y %H:%M") if reg.confirmed_at else "",
        "signature": reg.attendance_signature or "",
        "media_consent": media_consent_label(user.media_consent_status) if include_sensitive else "",
    }


def _replace_event_placeholders(text: str, event: Event, count: int) -> str:
    result = text
    for token, resolver in EVENT_PLACEHOLDERS.items():
        result = result.replace(token, resolver(event, count))
    return result


def _copy_excel_row_style(ws, source_row: int, target_row: int) -> None:
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(1, ws.max_column + 1):
        src = ws.cell(source_row, col)
        dst = ws.cell(target_row, col)
        if src.has_style:
            dst._style = copy(src._style)
        if src.number_format:
            dst.number_format = src.number_format
        dst.font = copy(src.font)
        dst.fill = copy(src.fill)
        dst.border = copy(src.border)
        dst.alignment = copy(src.alignment)
        dst.protection = copy(src.protection)


def fill_excel_template(raw: bytes, event: Event, registrations: list[tuple[EventRegistration, User]], *, include_sensitive: bool = True) -> bytes:
    wb = load_workbook(BytesIO(raw))
    count = len(registrations)

    # Event-level placeholders can live anywhere in the donor workbook.
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and "{{" in cell.value:
                    cell.value = _replace_event_placeholders(cell.value, event, count)

    target = None
    for ws in wb.worksheets:
        max_scan = min(max(ws.max_row, 1), 80)
        for row_idx in range(1, max_scan + 1):
            mapping: dict[int, str] = {}
            for col_idx in range(1, ws.max_column + 1):
                field = _field_for_header(ws.cell(row_idx, col_idx).value)
                if field:
                    mapping[col_idx] = field
            # At minimum we need a person-identifying column. One extra mapped
            # field makes accidental matching of prose much less likely.
            if ("full_name" in mapping.values() or ({"last_name", "first_name"} <= set(mapping.values()))) and len(mapping) >= 2:
                target = (ws, row_idx, mapping)
                break
        if target:
            break

    if not target:
        # Preserve the donor workbook and append a clearly named register sheet
        # instead of destroying an unrecognized layout.
        ws = wb.create_sheet("АМП — учасники")
        headers = ["№", "ID АМП", "ПІБ", "Дата народження", "Вік", "Населений пункт", "Статус участі", "Час відмітки", "Підтверджено", "Цифровий код підтвердження"]
        ws.append(headers)
        for idx, (reg, user) in enumerate(registrations, start=1):
            v = _participant_values(idx, reg, user, event, include_sensitive=include_sensitive)
            ws.append([v["number"], v["amp_id"], v["full_name"], v["birth_date"], v["age"], v["settlement"], v["status"], v["checkin_at"], v["confirmed_at"], v["signature"]])
        out = BytesIO(); wb.save(out); return out.getvalue()

    ws, header_row, mapping = target
    template_row = header_row + 1
    if count == 0:
        out = BytesIO(); wb.save(out); return out.getvalue()

    # Save row style before insertion. Inserting rows moves donor footers and
    # leaves their design intact. The first row below the header acts as the
    # donor's style template.
    if count > 1:
        ws.insert_rows(template_row + 1, amount=count - 1)
        for target_row in range(template_row + 1, template_row + count):
            _copy_excel_row_style(ws, template_row, target_row)

    for idx, (reg, user) in enumerate(registrations, start=1):
        values = _participant_values(idx, reg, user, event, include_sensitive=include_sensitive)
        row = template_row + idx - 1
        for col, field in mapping.items():
            ws.cell(row, col).value = values.get(field, "")

    out = BytesIO(); wb.save(out); return out.getvalue()


def _replace_docx_paragraph(paragraph, event: Event, count: int) -> None:
    original = paragraph.text
    replaced = _replace_event_placeholders(original, event, count)
    if replaced == original:
        return
    # Keep paragraph-level styling by replacing text in the first run and
    # clearing the rest. This avoids recreating the paragraph itself.
    if paragraph.runs:
        paragraph.runs[0].text = replaced
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.text = replaced


def _set_docx_cell_text(cell, value: object) -> None:
    text = "" if value is None else str(value)
    p = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    if p.runs:
        p.runs[0].text = text
        for run in p.runs[1:]:
            run.text = ""
    else:
        p.text = text


def fill_docx_template(raw: bytes, event: Event, registrations: list[tuple[EventRegistration, User]], *, include_sensitive: bool = True) -> bytes:
    doc = Document(BytesIO(raw))
    count = len(registrations)
    for paragraph in doc.paragraphs:
        _replace_docx_paragraph(paragraph, event, count)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _replace_docx_paragraph(paragraph, event, count)

    target = None
    for table in doc.tables:
        for row_idx, row in enumerate(table.rows[:12]):
            mapping: dict[int, str] = {}
            for col_idx, cell in enumerate(row.cells):
                field = _field_for_header(cell.text)
                if field:
                    mapping[col_idx] = field
            if ("full_name" in mapping.values() or ({"last_name", "first_name"} <= set(mapping.values()))) and len(mapping) >= 2:
                target = (table, row_idx, mapping)
                break
        if target:
            break

    if not target:
        # Do not discard donor design. Append a register after existing content.
        doc.add_paragraph()
        doc.add_heading("Реєстраційний список учасників", level=2)
        table = doc.add_table(rows=1, cols=8)
        headers = ["№", "ID АМП", "ПІБ", "Вік", "Населений пункт", "Статус", "Підтверджено", "Цифровий код підтвердження"]
        for i, h in enumerate(headers):
            table.rows[0].cells[i].text = h
        for idx, (reg, user) in enumerate(registrations, start=1):
            row = table.add_row()
            v = _participant_values(idx, reg, user, event, include_sensitive=include_sensitive)
            vals = [v["number"], v["amp_id"], v["full_name"], v["age"], v["settlement"], v["status"], v["confirmed_at"], v["signature"]]
            for i, value in enumerate(vals):
                row.cells[i].text = "" if value is None else str(value)
        out = BytesIO(); doc.save(out); return out.getvalue()

    table, header_idx, mapping = target
    if not registrations:
        out = BytesIO(); doc.save(out); return out.getvalue()

    # Use the first row after the header as a styling template. If the donor
    # supplied headers only, Word creates a new row as a fallback.
    if len(table.rows) <= header_idx + 1:
        template_row = table.add_row()
    else:
        template_row = table.rows[header_idx + 1]
    clean_xml = deepcopy(template_row._tr)

    for idx, (reg, user) in enumerate(registrations, start=1):
        if idx == 1:
            row = table.rows[header_idx + 1]
        else:
            new_tr = deepcopy(clean_xml)
            table._tbl.insert(header_idx + 1 + idx - 1, new_tr)
            row = table.rows[header_idx + idx]
        values = _participant_values(idx, reg, user, event, include_sensitive=include_sensitive)
        for col, field in mapping.items():
            if col < len(row.cells):
                _set_docx_cell_text(row.cells[col], values.get(field, ""))

    out = BytesIO(); doc.save(out); return out.getvalue()


def fill_registration_template(
    raw: bytes,
    filename: str,
    event: Event,
    registrations: list[tuple[EventRegistration, User]],
    *,
    include_sensitive: bool = True,
) -> tuple[bytes, str, str]:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".xlsx":
        return fill_excel_template(raw, event, registrations, include_sensitive=include_sensitive), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"
    if suffix == ".docx":
        return fill_docx_template(raw, event, registrations, include_sensitive=include_sensitive), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
    raise ValueError("Підтримуються лише шаблони .xlsx та .docx")
