from datetime import date, datetime, timezone

from adapters.agenda import parse_bcb, parse_tradingview


def test_tradingview_keeps_medium_and_high_with_a_clock_time() -> None:
    payload = {
        "result": [
            {"date": "2026-09-24T12:30:00.000Z", "country": "US", "title": "Initial Jobless Claims",
             "importance": 0, "forecast": 201, "previous": 197, "actual": None},
            {"date": "2026-09-24T12:00:00.000Z", "country": "US", "title": "Building Permits",
             "importance": -1},
            {"date": "2026-09-24T00:00:00.000Z", "country": "US", "title": "Trump and Xi Summit",
             "importance": 1},
        ]
    }
    events = parse_tradingview(payload)
    assert [e.title for e in events] == ["Initial Jobless Claims"]
    assert events[0].at == datetime(2026, 9, 24, 12, 30, tzinfo=timezone.utc)
    assert events[0].forecast == "201"


def test_bcb_takes_only_the_president_items_open_to_the_press() -> None:
    descricao = (
        '<div><strong>Manhã</strong></div><div>11&#58;00 às 13&#58;00 – <div class="d-inline">'
        '<p class="d-inline">​Participa de coletiva de imprensa sobre política monetária, '
        '<a href="x">Canal do BC.</a> <strong>(aberto à imprensa)</strong><br></p></div></div>'
        "<div><strong>Tarde</strong></div><div>15&#58;00 às 17&#58;00 – <div><p><span>Participa\n"
        "da reunião do CMN. <strong>(fechado\nà imprensa)</strong></span><br></p></div></div>"
    )
    payload = {
        "conteudo": [
            {"identificacaoAutoridade": "01 - Presi - Gabriel Muricca Galípolo", "descricao": descricao},
            {"identificacaoAutoridade": "05 - Difis - Outro", "descricao": descricao},
        ]
    }
    events = parse_bcb(payload, date(2026, 9, 24))
    assert len(events) == 1
    assert events[0].at == datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)  # 11h BRT
    assert events[0].title.startswith("Galípolo: Participa de coletiva")
