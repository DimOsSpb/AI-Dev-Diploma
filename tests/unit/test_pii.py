from app.services.security.pii import redact_pii


def test_redact_pii():
    text = "Мой email ivan@mail.ru, тел +7 (999) 123-45-67, карта 4111 1111 1111 1111"

    result = redact_pii(text)

    pii_map = {
        "EMAIL": {
            "label": "Мой e-mail:",
            "vars": ["ivan@mail.ru", "ivan.a.s@mail-1.com"],
        },
        "PHONE": {
            "label": "тел.",
            "vars": [
                "+7 (999) 123-45-67",
                "+79991234567",
                "8 999 123 45 67",
                "8(999)1234567",
            ],
        },
        "CARD": {
            "label": "карта",
            "vars": ["4111 1111 1111 1111", "4111111111111111"],
        },
    }

    text = "; ".join([
        f"{item['label']} + {' | '.join(item['vars'])}" for item in pii_map.values()
    ])

    print(f"\nTest value = {text}")

    result = redact_pii(text)

    print(f"Result = {result}")

    for variants in pii_map.values():
        for value in variants["vars"]:
            assert value not in result

    for mask in pii_map:
        assert mask in result
