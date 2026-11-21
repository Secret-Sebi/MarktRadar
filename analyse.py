"""Regelmodell für den lokalen Beobachter.

Der Score ist kein Gewinnversprechen. Er bündelt nur RSI und gleitende
Durchschnitte zu einem nachvollziehbaren Hinweis.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class Kennzahlen:
    preis: float
    sma20: float | None
    sma50: float | None
    sma200: float | None
    rsi: float | None
    hoch_52w: float | None
    aenderung_5t_pct: float | None
    aenderung_20t_pct: float | None
    ist_etf: bool
    anzahl_kurse: int


@dataclass(frozen=True)
class Urteil:
    aktion: str
    score: int
    titel: str
    grund: str
    hinweis_broker: str


def sma(werte: Sequence[float], periode: int) -> float | None:
    if periode <= 0 or len(werte) < periode:
        return None
    fenster = werte[-periode:]
    return sum(fenster) / periode


def rsi(werte: Sequence[float], periode: int = 14) -> float | None:
    if periode <= 0 or len(werte) < periode + 1:
        return None
    aenderungen = tuple(werte[index] - werte[index - 1] for index in range(1, len(werte)))
    erste = aenderungen[:periode]
    gewinn = sum(wert for wert in erste if wert > 0) / periode
    verlust = sum(-wert for wert in erste if wert < 0) / periode
    for aenderung in aenderungen[periode:]:
        schritt_gewinn = aenderung if aenderung > 0 else 0.0
        schritt_verlust = -aenderung if aenderung < 0 else 0.0
        gewinn = (gewinn * (periode - 1) + schritt_gewinn) / periode
        verlust = (verlust * (periode - 1) + schritt_verlust) / periode
    if gewinn == 0 and verlust == 0:
        return 50.0
    if verlust == 0:
        return 100.0
    if gewinn == 0:
        return 0.0
    relativ = gewinn / verlust
    return 100.0 - (100.0 / (1.0 + relativ))


def abstand_prozent(preis: float, basis: float | None) -> float | None:
    if basis is None or basis == 0:
        return None
    return (preis / basis - 1.0) * 100.0


def kennzahlen_aus_schluessen(
    schluesse: Sequence[float],
    ist_etf: bool,
    hoch_52w: float | None,
) -> Kennzahlen:
    werte = tuple(float(wert) for wert in schluesse)
    anzahl = len(werte)
    preis = werte[-1] if werte else 0.0
    hoch = hoch_52w
    if hoch is None and werte:
        hoch = max(werte[-252:])
    return Kennzahlen(
        preis=preis,
        sma20=sma(werte, 20),
        sma50=sma(werte, 50),
        sma200=sma(werte, 200),
        rsi=rsi(werte, 14),
        hoch_52w=hoch,
        aenderung_5t_pct=_aenderung(werte, 5),
        aenderung_20t_pct=_aenderung(werte, 20),
        ist_etf=ist_etf,
        anzahl_kurse=anzahl,
    )


def aktion_bei_datenstatus(aktion: str, datenstatus: str) -> str:
    if datenstatus == "ok":
        return aktion
    if aktion in ("einstieg_pruefen", "sparplan"):
        return "unvollstaendig"
    return aktion


def ist_wichtig(
    fenster_text: str,
    tag_pct: float | None,
    datenstatus: str,
    kurszeit: int | None = None,
    jetzt: int | None = None,
    ungewoehnlich: str = "",
) -> bool:
    if datenstatus != "ok":
        return False
    if jetzt is not None:
        if isinstance(kurszeit, bool) or not isinstance(kurszeit, int):
            return False
        if int(jetzt) - int(kurszeit) > 36 * 3600:
            return False
    return bool(fenster_text or ungewoehnlich)


def markt_satz(tag_pct: float | None, index_pct: float | None, index_name: str) -> str:
    if not index_name or isinstance(tag_pct, bool) or isinstance(index_pct, bool):
        return ""
    if not isinstance(tag_pct, (int, float)) or not isinstance(index_pct, (int, float)):
        return ""
    tag = float(tag_pct)
    index = float(index_pct)
    if abs(tag) < 1 or abs(index) < 1 or tag * index <= 0 or abs(tag) > abs(index) * 2:
        return ""
    richtung = "gefallen" if index < 0 else "gestiegen"
    return (
        f"Der {index_name} ist heute um {de_zahl(abs(index), 1)} % {richtung}. "
        "Dieser Name geht mit dem Markt. Das ist kein einzelnes Firmenereignis."
    )


def ungewoehnlicher_tag(tag_pct: float | None, schluesse: Sequence[float]) -> tuple[str, str]:
    if tag_pct is None or isinstance(tag_pct, bool) or abs(float(tag_pct)) < 3:
        return "", ""
    vorher = _tagesbewegungen(schluesse)[:-1]
    bewegung = de_zahl(abs(float(tag_pct)), 1)
    richtung = "gefallen" if float(tag_pct) < 0 else "gestiegen"
    if len(vorher) < 8:
        return "", (
            f"Heute {richtung} um {bewegung} %. "
            f"Eigene Vergleichstage: {len(vorher)}. Für ungewöhnlich brauche ich mindestens 8."
        )
    schwelle = _neun_von_zehn(vorher)
    if abs(float(tag_pct)) > schwelle:
        return (
            f"Heute {richtung} um {bewegung} %. "
            f"Bei diesem Namen waren 9 von 10 Tagen kleiner als {de_zahl(schwelle, 1)} %."
        ), ""
    return "", (
        f"Heute {richtung} um {bewegung} %. "
        f"Für diesen Namen ist das normal: 9 von 10 Tagen gehen bis {de_zahl(schwelle, 1)} %. Kein Vorschlag."
    )


def _tagesbewegungen(schluesse: Sequence[float]) -> tuple[float, ...]:
    werte = tuple(float(wert) for wert in schluesse if wert)
    return tuple(
        (werte[index] / werte[index - 1] - 1.0) * 100.0
        for index in range(1, len(werte))
        if werte[index - 1]
    )


def _neun_von_zehn(werte: Sequence[float]) -> float:
    sortiert = sorted(abs(wert) for wert in werte)
    index = min(len(sortiert) - 1, max(0, math.ceil(0.9 * len(sortiert)) - 1))
    return sortiert[index]


def angezeigtes_fenster(zahlen: Kennzahlen | None, schluesse: Sequence[float]) -> tuple[str, str]:
    basis = kurzfenster(zahlen)
    if not basis:
        return "", ""
    faelle = tuple(_drei_tage(schluesse))
    if len(faelle) < 8:
        return "", (
            f"Das Fenster ist im aktuellen Kurs zu sehen, aber nur {len(faelle)}-mal mit einem späteren Kurs belegt. "
            "Für einen Vorschlag brauche ich mindestens 8 eigene Fälle."
        )
    median = _median(faelle)
    satz = (
        f"In den geladenen Kursen kam das Fenster {len(faelle)}-mal vor. "
        f"Der Median nach 3 Handelstagen lag bei {de_zahl(median, 1)} %."
    )
    if median <= 0:
        return "", f"Das Fenster ist im aktuellen Kurs zu sehen. {satz} Das reicht nicht für einen Vorschlag."
    return basis.replace("Das ist eine Lesart der geladenen Kurse, kein Auftrag.", f"{satz} Das ist kein Auftrag."), satz


def _drei_tage(schluesse: Sequence[float]) -> tuple[float, ...]:
    werte = tuple(float(wert) for wert in schluesse if wert)
    faelle = []
    for index in range(199, len(werte) - 3):
        reihe = werte[: index + 1]
        preis = reihe[-1]
        linie20 = sma(reihe, 20)
        linie200 = sma(reihe, 200)
        rsi_wert = rsi(reihe, 14)
        if linie20 is None or linie200 is None or rsi_wert is None or preis == 0:
            continue
        if preis > linie200 and preis <= linie20 and 30 <= rsi_wert <= 55:
            faelle.append((werte[index + 3] / preis - 1.0) * 100.0)
    return tuple(faelle)


def _median(werte: Sequence[float]) -> float:
    sortiert = sorted(werte)
    mitte = len(sortiert) // 2
    if len(sortiert) % 2:
        return sortiert[mitte]
    return (sortiert[mitte - 1] + sortiert[mitte]) / 2.0


def kurzfenster(zahlen: Kennzahlen | None) -> str:
    if zahlen is None or zahlen.anzahl_kurse < 50 or zahlen.sma20 is None or zahlen.sma200 is None or zahlen.rsi is None:
        return ""
    if _im_abwaertstrend(zahlen) or zahlen.rsi >= 68:
        return ""
    ruecksetzer = zahlen.preis > zahlen.sma200 and zahlen.preis <= zahlen.sma20 and 30 <= zahlen.rsi <= 55
    if not ruecksetzer and not _etf_ruecksetzer(zahlen, _score(zahlen)):
        return ""
    return (
        f"Kurzes Fenster, die nächsten 1–3 Handelstage: Rücksetzer im länger steigenden Kurs. "
        f"RSI {de_zahl(zahlen.rsi, 1)}. Das ist eine Lesart der geladenen Kurse, kein Auftrag."
    )


def urteilen(zahlen: Kennzahlen) -> Urteil:
    score = _score(zahlen)
    aktion = _aktion(zahlen, score)
    return Urteil(
        aktion=aktion,
        score=score,
        titel=_TITEL[aktion],
        grund=_grund(zahlen, aktion),
        hinweis_broker=_broker(aktion, zahlen.ist_etf),
    )


def fenster(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("Zeitzone fehlt")
    berlin = moment.astimezone(BERLIN)
    if berlin.weekday() >= 5:
        return "wochenende"
    minuten = berlin.hour * 60 + berlin.minute
    if 9 * 60 <= minuten < 17 * 60 + 30:
        return "xetra"
    if 7 * 60 + 30 <= minuten < 23 * 60:
        return "bestpreis"
    return "zu"


def soll_melden(vorher: str | None, aktion: str) -> bool:
    if vorher is None:
        return False
    return aktion == "einstieg_pruefen" and vorher != "einstieg_pruefen"


def handels_hinweis(moment: datetime) -> str:
    return _FENSTER_TEXT[fenster(moment)]


def fehler_urteil(meldung: str) -> Urteil:
    return Urteil("fehler", 0, _TITEL["fehler"], meldung[:160], _BROKER["fehler"])


def unvollstaendig_urteil(fehlend: Sequence[str]) -> Urteil:
    namen = ", ".join(fehlend) if fehlend else "wichtige Kurse"
    return Urteil(
        "unvollstaendig",
        0,
        "Daten unvollständig",
        f"Es fehlt: {namen}. Ohne diese Werte gibt es keine vollständige technische Bewertung.",
        "Mehr Handelstage abwarten.",
    )


def de_zahl(wert: float, stellen: int = 2) -> str:
    vorzeichen = "-" if wert < 0 else ""
    text = f"{abs(wert):.{stellen}f}"
    ganz, bruch = text.split(".")
    teile = []
    while ganz:
        teile.append(ganz[-3:])
        ganz = ganz[:-3]
    return vorzeichen + ".".join(reversed(teile)) + "," + bruch


def de_prozent(wert: float | None) -> str:
    if wert is None:
        return "ohne Wert"
    if wert > 0:
        return "+" + de_zahl(wert, 1) + " %"
    return de_zahl(wert, 1) + " %"


def _aenderung(werte: Sequence[float], tage: int) -> float | None:
    if len(werte) <= tage:
        return None
    basis = werte[-(tage + 1)]
    if basis == 0:
        return None
    return (werte[-1] / basis - 1.0) * 100.0


def _score(zahlen: Kennzahlen) -> int:
    punkte = 32.0
    if zahlen.sma200 is not None:
        punkte += 10 if zahlen.preis > zahlen.sma200 else -20
    if zahlen.sma50 is not None and zahlen.sma200 is not None:
        punkte += 6 if zahlen.sma50 > zahlen.sma200 else -8
    if _kurzer_ruecksetzer(zahlen):
        punkte += 8
    punkte += _rsi_punkte(zahlen)
    punkte += _ruecksetzer_punkte(zahlen)
    if zahlen.aenderung_5t_pct is not None and zahlen.aenderung_5t_pct <= -8:
        punkte -= 12
    return max(0, min(100, int(round(punkte))))  # noqa: RUF046


def _kurzer_ruecksetzer(zahlen: Kennzahlen) -> bool:
    if zahlen.sma20 is None or zahlen.sma200 is None:
        return False
    return zahlen.preis > zahlen.sma200 and zahlen.preis < zahlen.sma20


def _rsi_punkte(zahlen: Kennzahlen) -> float:
    wert = zahlen.rsi
    if wert is None:
        return 0.0
    im_aufwaerts = zahlen.sma200 is not None and zahlen.preis > zahlen.sma200
    if 35 <= wert <= 48 and im_aufwaerts:
        return 26.0
    if 30 <= wert < 35 and im_aufwaerts:
        return 16.0
    if 48 < wert <= 55 and im_aufwaerts:
        return 8.0
    if wert >= 70:
        return -24.0
    if wert >= 68:
        return -16.0
    if 55 < wert < 68:
        return -6.0
    if wert < 30 and im_aufwaerts:
        return 8.0
    if wert < 30:
        return -6.0
    return 0.0


def _ruecksetzer_punkte(zahlen: Kennzahlen) -> float:
    if zahlen.hoch_52w is None or zahlen.hoch_52w == 0:
        return 0.0
    abstand = (zahlen.preis / zahlen.hoch_52w - 1.0) * 100.0
    im_aufwaerts = zahlen.sma200 is not None and zahlen.preis > zahlen.sma200
    if im_aufwaerts and -20 <= abstand <= -6:
        return 10.0
    if abstand <= -35:
        return -10.0
    return 0.0


def _aktion(zahlen: Kennzahlen, score: int) -> str:
    if zahlen.anzahl_kurse < 50 or zahlen.sma50 is None or zahlen.rsi is None:
        return "unklar"
    if _etf_ruecksetzer(zahlen, score):
        return "einstieg_pruefen"
    if zahlen.ist_etf:
        return "sparplan"
    if _im_abwaertstrend(zahlen) and zahlen.rsi >= 32:
        return "vorsicht"
    if zahlen.rsi >= 68:
        return "abwarten"
    if score >= 68 and zahlen.preis > zahlen.sma50 and zahlen.rsi <= 55:
        return "einstieg_pruefen"
    if _im_abwaertstrend(zahlen):
        return "vorsicht"
    return "beobachten"


def _etf_ruecksetzer(zahlen: Kennzahlen, score: int) -> bool:
    if not zahlen.ist_etf or zahlen.rsi is None or zahlen.sma200 is None:
        return False
    return zahlen.preis > zahlen.sma200 and 30 <= zahlen.rsi <= 42 and score >= 75


def _im_abwaertstrend(zahlen: Kennzahlen) -> bool:
    if zahlen.sma200 is None or zahlen.sma50 is None:
        return False
    return zahlen.preis < zahlen.sma200 and zahlen.sma50 < zahlen.sma200


def _grund(zahlen: Kennzahlen, aktion: str) -> str:
    if aktion == "unklar":
        return "Zu wenig Kursdaten für das Modell."
    if aktion == "vorsicht":
        return (
            "Kurs und 50-Tage-Linie liegen unter der 200-Tage-Linie. "
            "Gefallen allein ist hier kein Einstiegsgrund."
        )
    if aktion == "abwarten":
        return (
            f"Der RSI ist {_rsi_text(zahlen.rsi)}. Der Kurs ist kurzfristig schon gelaufen. "
            "In diesem Modell ist das kein Moment, um hinterherzukaufen."
        )
    if aktion == "sparplan":
        return _sparplan_grund(zahlen)
    if aktion == "einstieg_pruefen":
        return (
            f"Rücksetzer im Aufwärtstrend. RSI {_rsi_text(zahlen.rsi)}. "
            f"Abstand zur 200-Tage-Linie {de_prozent(abstand_prozent(zahlen.preis, zahlen.sma200))}. "
            f"Die letzten 5 Handelstage: {de_prozent(zahlen.aenderung_5t_pct)}."
        )
    return (
        f"Kein klarer Vorteil. RSI {_rsi_text(zahlen.rsi)}, "
        f"Abstand zur 200-Tage-Linie {de_prozent(abstand_prozent(zahlen.preis, zahlen.sma200))}."
    )


def _sparplan_grund(zahlen: Kennzahlen) -> str:
    if zahlen.sma200 is not None and zahlen.preis < zahlen.sma200:
        return (
            "Breiter ETF und der Kurs liegt unter der 200-Tage-Linie. "
            "Für so ein Produkt ist ein monatlicher Sparplan der normale Weg, "
            "keine große Einmalanlage nur weil es gefallen ist."
        )
    return (
        "Breiter ETF. Der einzelne Kaufzeitpunkt ist zweitrangig. "
        "Ein monatlicher Sparplan in Trade Republic verteilt den Einstieg."
    )


def _broker(aktion: str, ist_etf: bool) -> str:
    if aktion == "einstieg_pruefen" and ist_etf:
        return (
            "In Trade Republic den ETF suchen. Sparplanrate prüfen oder eine kleine "
            "Einmalanlage per Limit-Order. Den Betrag entscheidest du."
        )
    return _BROKER[aktion]


def _rsi_text(wert: float | None) -> str:
    if wert is None:
        return "ohne RSI"
    return de_zahl(wert, 1)


_FENSTER_TEXT = {
    "wochenende": (
        "Wochenende. Im Bestpreis handelt Trade Republic Aktien und ETFs "
        "Montag bis Freitag, 7:30 bis 23:00 Uhr. Jetzt siehst du den letzten Kurs."
    ),
    "xetra": (
        "Xetra-Kernzeit (9:00–17:30) und das Bestpreis-Fenster von Trade Republic sind offen."
    ),
    "bestpreis": (
        "Bestpreis-Fenster von Trade Republic ist offen (Mo–Fr 7:30–23:00). "
        "Die Xetra-Kernzeit ist zu. Im Direktpreis gelten die Zeiten des gewählten Handelsplatzes."
    ),
    "zu": (
        "Außerhalb des Bestpreis-Fensters. Eine Limit-Order kannst du in Trade Republic "
        "trotzdem anlegen, eine Marktorder nicht."
    ),
}

_TITEL = {
    "einstieg_pruefen": "Prüfen",
    "sparplan": "Eher Sparplan",
    "beobachten": "Kein klarer Vorteil",
    "abwarten": "Nicht hinterherlaufen",
    "vorsicht": "Abwärtstrend",
    "unklar": "Zu wenig Daten",
    "fehler": "Nicht geladen",
}

_BROKER = {
    "einstieg_pruefen": (
        "In Trade Republic den Namen suchen und den Preis dort prüfen. "
        "Wenn du kaufst: Limit-Order. Das Programm nennt keinen Betrag."
    ),
    "sparplan": "In Trade Republic einen Sparplan auf diesen ETF anlegen oder laufen lassen.",
    "beobachten": "Auf der Liste lassen. Es gibt gerade keinen Vorteil gegenüber Abwarten.",
    "abwarten": "Nicht wegen dieses Laufs kaufen. Die Beobachtung läuft weiter.",
    "vorsicht": "Kein Einstiegssignal. Einen bestehenden Sparplan musst du deswegen nicht stoppen.",
    "unklar": "Mehr Kurshistorie abwarten.",
    "fehler": "Beim nächsten Durchgang erneut versuchen.",
}
