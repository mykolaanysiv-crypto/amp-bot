from app.donations import _jar_send_id, _normalize_jar_send_id


def test_monobank_send_id_formats_are_canonicalized():
    assert _jar_send_id("https://send.monobank.ua/jar/5S531LWQuc") == "5S531LWQuc"
    assert _normalize_jar_send_id("jar/5S531LWQuc") == "5S531LWQuc"
    assert _normalize_jar_send_id("5S531LWQuc") == "5S531LWQuc"
    assert _normalize_jar_send_id("https://send.monobank.ua/jar/5S531LWQuc/") == "5S531LWQuc"
