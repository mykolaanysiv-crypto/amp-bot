from .common import *  # noqa: F401,F403

def build_profile_qr_png(
    user: User,
    bot_username: str,
    *,
    total_xp: int = 0,
    level: str = "АМПасадор",
    profile_photo: bytes | None = None,
) -> bytes:
    """Create the print-ready personal QR badge (55 × 85 mm at 300 DPI)."""
    token = user.public_token or "missing"
    link = f"https://t.me/{bot_username}?start=profile_{token}"

    # 55 × 85 mm at 300 DPI = ~650 × 1004 px.
    W, H = 650, 1004
    canvas = Image.new("RGB", (W, H), "#EEF9FA")
    draw = ImageDraw.Draw(canvas)

    try:
        f_brand = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
        f_name = ImageFont.truetype("DejaVuSans-Bold.ttf", 31)
        f_id = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
        f_mid = ImageFont.truetype("DejaVuSans-Bold.ttf", 19)
        f_text = ImageFont.truetype("DejaVuSans.ttf", 17)
        f_small = ImageFont.truetype("DejaVuSans.ttf", 14)
        f_tiny = ImageFont.truetype("DejaVuSans.ttf", 12)
    except OSError:
        f_brand = f_name = f_id = f_mid = f_text = f_small = f_tiny = ImageFont.load_default()

    def fit_font(text: str, max_width: int, start_size: int, min_size: int = 10, *, bold: bool = True):
        """Return the largest DejaVu font that keeps text inside max_width."""
        family = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        for size in range(start_size, min_size - 1, -1):
            try:
                font = ImageFont.truetype(family, size)
            except OSError:
                return f_small
            if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
                return font
        try:
            return ImageFont.truetype(family, min_size)
        except OSError:
            return f_small

    # Outer badge and top brand panel.
    draw.rounded_rectangle((12, 12, W - 12, H - 12), radius=34, fill="white", outline="#BFE5E9", width=3)
    draw.rounded_rectangle((12, 12, W - 12, 290), radius=34, fill="#0B5B6C")
    draw.rectangle((12, 235, W - 12, 290), fill="#0B5B6C")
    draw.ellipse((480, -40, 720, 200), fill="#0AA8B6")
    draw.ellipse((-75, 835, 165, 1075), fill="#DDF5F7")

    # Brand logo on white plate.
    logo_path = Path("app/web/static/amp_logo.png")
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((240, 100), Image.Resampling.LANCZOS)
        plate_x = (W - logo.width - 34) // 2
        draw.rounded_rectangle((plate_x, 36, plate_x + logo.width + 34, 36 + logo.height + 22), radius=18, fill="white")
        canvas.paste(logo, (plate_x + 17, 47), logo)
    else:
        text = "АМПасадори"
        tw = draw.textbbox((0, 0), text, font=f_brand)[2]
        draw.text(((W - tw) / 2, 58), text, font=f_brand, fill="white")

    # Participant photo. The user photo is optional and is never cropped destructively outside the circular avatar.
    avatar_box = (52, 172, 216, 336)
    if profile_photo:
        try:
            photo = Image.open(BytesIO(profile_photo))
            photo = ImageOps.exif_transpose(photo).convert("RGB")
            photo = ImageOps.fit(photo, (156, 156), method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
            mask = Image.new("L", (156, 156), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 155, 155), fill=255)
            draw.ellipse((48, 168, 220, 340), fill="white")
            canvas.paste(photo, (56, 176), mask)
        except Exception:
            profile_photo = None
    if not profile_photo:
        draw.ellipse(avatar_box, fill="#D9F2F4", outline="white", width=5)
        initials = "".join(part[:1].upper() for part in (user.full_name or "АМП").split()[:2]) or "АМП"
        tw = draw.textbbox((0, 0), initials, font=f_brand)[2]
        th = draw.textbbox((0, 0), initials, font=f_brand)[3]
        draw.text(((avatar_box[0] + avatar_box[2] - tw) / 2, (avatar_box[1] + avatar_box[3] - th) / 2 - 4), initials, font=f_brand, fill="#0B5B6C")

    # Name and identity block.
    name = (user.full_name or "Учасник АМП").strip()
    max_name_w = 355
    words = name.split()
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if not current or draw.textbbox((0, 0), candidate, font=f_name)[2] <= max_name_w:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    lines = lines[:2]
    y = 178
    for line in lines:
        draw.text((245, y), line, font=f_name, fill="white")
        y += 39
    draw.rounded_rectangle((245, 264, 405, 306), radius=18, fill="#E7F8F9")
    draw.text((262, 274), f"АМП-{user.id:04d}", font=f_id, fill="#0B5B6C")
    level_clean = "".join(ch for ch in level if ch.isalpha() or ch.isspace() or ch in "—-").strip() or "АМПасадор"
    level_top_font = fit_font(level_clean, 190, 14, 9, bold=False)
    level_top_w = draw.textbbox((0, 0), level_clean, font=level_top_font)[2]
    draw.text((420 + (190 - level_top_w) / 2, 276), level_clean, font=level_top_font, fill="white")

    # QR panel.
    draw.rounded_rectangle((50, 372, 600, 776), radius=30, fill="#F8FDFE", outline="#BFE5E9", width=2)
    draw.text((0, 0), "", font=f_small, fill="#0B5B6C")
    title = "ПЕРСОНАЛЬНИЙ QR-БЕЙДЖ"
    tw = draw.textbbox((0, 0), title, font=f_mid)[2]
    draw.text(((W - tw) / 2, 396), title, font=f_mid, fill="#0B5B6C")

    qr = qrcode.QRCode(version=None, box_size=10, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(link)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#0B5B6C", back_color="white").convert("RGB").resize((292, 292), Image.Resampling.NEAREST)
    qr_x = (W - 292) // 2
    canvas.paste(qr_img, (qr_x, 438))
    hint = "Відскануй у Telegram — приватні дані не показуються"
    tw = draw.textbbox((0, 0), hint, font=f_tiny)[2]
    draw.text(((W - tw) / 2, 742), hint, font=f_tiny, fill="#607A80")

    # Compact metrics row.
    stat_y = 812
    stat_w, gap = 168, 14
    stat_x = 52
    stats = [
        ("XP", str(int(total_xp or 0))),
        ("ГОДИНИ", f"{float(user.volunteer_hours or 0):g}"),
        ("РІВЕНЬ", level_clean),
    ]
    for label_text, value in stats:
        draw.rounded_rectangle((stat_x, stat_y, stat_x + stat_w, stat_y + 90), radius=18, fill="#EAF8FA")
        lw = draw.textbbox((0, 0), label_text, font=f_tiny)[2]
        value_font = fit_font(value, stat_w - 22, 19, 10, bold=True)
        vw = draw.textbbox((0, 0), value, font=value_font)[2]
        draw.text((stat_x + (stat_w - lw) / 2, stat_y + 14), label_text, font=f_tiny, fill="#668188")
        draw.text((stat_x + (stat_w - vw) / 2, stat_y + 42), value, font=value_font, fill="#173B43")
        stat_x += stat_w + gap

    footer = "АМПасадори • Анисівський молодіжний простір"
    tw = draw.textbbox((0, 0), footer, font=f_tiny)[2]
    draw.text(((W - tw) / 2, 940), footer, font=f_tiny, fill="#0B5B6C")
    draw.rounded_rectangle((185, 970, 465, 976), radius=3, fill="#06B8C5")

    out = BytesIO()
    canvas.save(out, format="PNG", dpi=(300, 300), optimize=True)
    return out.getvalue()


