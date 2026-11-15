"""Technische Kennzahlen auf bereinigten Schlusskursen.

Der angezeigte Marktkurs bleibt davon getrennt. Fehlende Pflichtreihen
ergeben keine neutrale Note, sondern eine unvollständige Bewertung.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from analyse import rsi, sma


@dataclass(frozen=True)
class Technik:
    vollstaendig: bool
    fehlend: Tuple[str, ...]
    hinweise: Tuple[str, ...]
    muster: Tuple[str, ...]
    macd: Optional[float]
    macd_signal: Optional[float]
    atr: Optional[float]
    trendstaerke: Optional[float]
    volatilitaet: Optional[float]
    rendite_1: Optional[float]
    rendite_5: Optional[float]
    rendite_20: Optional[float]
    rendite_60: Optional[float]
    stuetze: Optional[float]
    widerstand: Optional[float]
    relativ: Optional[float]
    index_titel: str
    hoch_52: Optional[float]
    tief_52: Optional[float]


def vergleichsindex(symbol: str) -> str:
    if symbol.upper().endswith(".DE"):
        return "^GDAXI"
    return "^GSPC"


def ema_reihe(werte: Sequence[float], periode: int) -> Optional[Tuple[Optional[float], ...]]:
    if periode <= 0 or len(werte) < periode:
        return None
    glatt = sum(werte[:periode]) / periode
    reihe: Tuple[Optional[float], ...] = (None,) * (periode - 1) + (glatt,)
    faktor = 2 / (periode + 1)
    for wert in werte[periode:]:
        glatt = (wert - glatt) * faktor + glatt
        reihe = reihe + (glatt,)
    return reihe


def ema_letzter(werte: Sequence[float], periode: int) -> Optional[float]:
    reihe = ema_reihe(werte, periode)
    if not reihe:
        return None
    return reihe[-1]


def macd(werte: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    kurz = ema_reihe(werte, 12)
    lang = ema_reihe(werte, 26)
    if kurz is None or lang is None:
        return None
    linie = tuple(a - b for a, b in zip(kurz, lang) if a is not None and b is not None)
    signal_reihe = ema_reihe(linie, 9)
    if not linie or signal_reihe is None or signal_reihe[-1] is None:
        return None
    signal = signal_reihe[-1]
    return linie[-1], signal, linie[-1] - signal


def atr(hochs: Sequence[float], tiefs: Sequence[float], schluesse: Sequence[float], periode: int = 14) -> Optional[float]:
    spannen = _true_ranges(hochs, tiefs, schluesse)
    return _wilder_letzter(spannen, periode)


def adx(hochs: Sequence[float], tiefs: Sequence[float], schluesse: Sequence[float], periode: int = 14) -> Optional[float]:
    if len(schluesse) <= periode * 2:
        return None
    plus, minus, spannen = _richtungsbewegungen(hochs, tiefs, schluesse)
    atr_reihe = _wilder_reihe(spannen, periode)
    plus_reihe = _wilder_reihe(plus, periode)
    minus_reihe = _wilder_reihe(minus, periode)
    dx = _dx_werte(atr_reihe, plus_reihe, minus_reihe)
    return _wilder_letzter(dx, periode)


def volatilitaet(werte: Sequence[float], tage: int = 20) -> Optional[float]:
    if len(werte) <= tage:
        return None
    fenster = werte[-(tage + 1) :]
    renditen = tuple(fenster[i] / fenster[i - 1] - 1 for i in range(1, len(fenster)) if fenster[i - 1])
    if len(renditen) < tage:
        return None
    mittel = sum(renditen) / len(renditen)
    varianz = sum((wert - mittel) ** 2 for wert in renditen) / len(renditen)
    return (varianz ** 0.5) * (252 ** 0.5) * 100


def zonen(
    hochs: Sequence[float],
    tiefs: Sequence[float],
    preis: float,
    abstand: int = 5,
) -> Tuple[Optional[float], Optional[float]]:
    stuetzen = []
    widerstaende = []
    for index in range(abstand, len(hochs) - abstand):
        tief_fenster = tiefs[index - abstand : index + abstand + 1]
        hoch_fenster = hochs[index - abstand : index + abstand + 1]
        if tiefs[index] == min(tief_fenster) and tiefs[index] < preis:
            stuetzen.append(tiefs[index])
        if hochs[index] == max(hoch_fenster) and hochs[index] > preis:
            widerstaende.append(hochs[index])
    stuetze = max(stuetzen) if stuetzen else None
    widerstand = min(widerstaende) if widerstaende else None
    return stuetze, widerstand


def relativ(aktie: Sequence[float], index: Sequence[float], tage: int = 60) -> Optional[float]:
    if len(aktie) <= tage or len(index) <= tage or aktie[-(tage + 1)] == 0 or index[-(tage + 1)] == 0:
        return None
    aktie_rendite = (aktie[-1] / aktie[-(tage + 1)] - 1) * 100
    index_rendite = (index[-1] / index[-(tage + 1)] - 1) * 100
    return aktie_rendite - index_rendite


def vorzeichenwechsel(frueher: float, jetzt: float) -> bool:
    if frueher == 0 or jetzt == 0:
        return False
    return (frueher > 0) != (jetzt > 0)


def trend_kreuzt(preise: Sequence[float], fenster: int = 5) -> bool:
    if fenster <= 0 or len(preise) < 200 + fenster:
        return False
    jetzt = _spread(preise)
    frueher = _spread(preise[:-fenster])
    if jetzt is None or frueher is None:
        return False
    return vorzeichenwechsel(frueher, jetzt)


def muster(
    preis: float,
    sma50: Optional[float],
    sma200: Optional[float],
    rsi: Optional[float],
    rendite_1: Optional[float],
    rendite_5: Optional[float],
    rendite_20: Optional[float],
    index_20: Optional[float],
    volumen: Optional[float],
    volumen_schnitt: Optional[float],
    bricht_widerstand_aus: bool,
    kreuzt_trend: bool,
) -> Tuple[str, ...]:
    namen = []
    if _ist_ruecksetzer(preis, sma50, sma200, rsi):
        namen.append("Rücksetzer im Aufwärtstrend")
    if rsi is not None and rsi >= 70:
        namen.append("Überkauft")
    if rsi is not None and rsi <= 30:
        namen.append("Überverkauft")
    if kreuzt_trend:
        namen.append("Möglicher Trendwechsel")
    if _starker_verlust(rendite_1, rendite_5):
        namen.append("Ungewöhnlich starker Verlust")
    if bricht_widerstand_aus and _volumen_hebt_ab(volumen, volumen_schnitt):
        namen.append("Ausbruch nach oben")
    if index_20 is not None and rendite_20 is not None and index_20 > 2 and rendite_20 <= -2:
        namen.append("Schwach trotz steigendem Markt")
    return tuple(namen)


def berechne(balken, preis: float, index_balken, hat_bereinigt: bool, index_titel: str = "", hoch_52=None, tief_52=None) -> Technik:
    schluesse = tuple(bar.bereinigt for bar in balken)
    hochs, tiefs, roh = _markt_reihen(balken)
    fehlend = _fehlende_pflicht(schluesse)
    hinweise = _fehlende_hinweise(hat_bereinigt, index_balken)
    rsi_wert = rsi(schluesse, 14)
    macd_werte = macd(schluesse)
    rendite_1 = _rendite(schluesse, 1)
    rendite_5 = _rendite(schluesse, 5)
    rendite_20 = _rendite(schluesse, 20)
    rendite_60 = _rendite(schluesse, 60)
    stuetze, widerstand, bricht = _zonen_fuer_kurs(hochs, tiefs, preis)
    volumen, schnitt = _volumen(balken)
    relativ_wert, index_20 = _vergleich(balken, index_balken)
    hoch, tief = _jahresband(hochs, tiefs, hoch_52, tief_52)
    namen = muster(
        preis,
        sma(schluesse, 50),
        sma(schluesse, 200),
        rsi_wert,
        rendite_1,
        rendite_5,
        rendite_20,
        index_20,
        volumen,
        schnitt,
        bricht,
        trend_kreuzt(schluesse),
    )
    return Technik(
        vollstaendig=not fehlend,
        fehlend=fehlend,
        hinweise=hinweise,
        muster=namen,
        macd=None if macd_werte is None else macd_werte[0],
        macd_signal=None if macd_werte is None else macd_werte[1],
        atr=atr(hochs, tiefs, roh),
        trendstaerke=adx(hochs, tiefs, roh),
        volatilitaet=volatilitaet(schluesse),
        rendite_1=rendite_1,
        rendite_5=rendite_5,
        rendite_20=rendite_20,
        rendite_60=rendite_60,
        stuetze=stuetze,
        widerstand=widerstand,
        relativ=relativ_wert,
        index_titel=index_titel,
        hoch_52=hoch,
        tief_52=tief,
    )


def _true_ranges(hochs, tiefs, schluesse) -> Tuple[float, ...]:
    werte = []
    for index in range(1, len(schluesse)):
        werte.append(
            max(
                hochs[index] - tiefs[index],
                abs(hochs[index] - schluesse[index - 1]),
                abs(tiefs[index] - schluesse[index - 1]),
            )
        )
    return tuple(werte)


def _wilder_reihe(werte: Sequence[float], periode: int) -> Tuple[float, ...]:
    if periode <= 0 or len(werte) < periode:
        return ()
    mittel = sum(werte[:periode])
    reihe = (mittel,)
    for wert in werte[periode:]:
        mittel = mittel - (mittel / periode) + wert
        reihe = reihe + (mittel,)
    return reihe


def _wilder_letzter(werte: Sequence[float], periode: int) -> Optional[float]:
    reihe = _wilder_reihe(werte, periode)
    if not reihe:
        return None
    return reihe[-1] / periode


def _richtungsbewegungen(hochs, tiefs, schluesse):
    plus = []
    minus = []
    spannen = []
    for index in range(1, len(schluesse)):
        nach_oben = hochs[index] - hochs[index - 1]
        nach_unten = tiefs[index - 1] - tiefs[index]
        plus.append(nach_oben if nach_oben > nach_unten and nach_oben > 0 else 0.0)
        minus.append(nach_unten if nach_unten > nach_oben and nach_unten > 0 else 0.0)
        spannen.append(
            max(
                hochs[index] - tiefs[index],
                abs(hochs[index] - schluesse[index - 1]),
                abs(tiefs[index] - schluesse[index - 1]),
            )
        )
    return tuple(plus), tuple(minus), tuple(spannen)


def _dx_werte(atr_reihe, plus_reihe, minus_reihe) -> Tuple[float, ...]:
    werte = []
    for spanne, plus, minus in zip(atr_reihe, plus_reihe, minus_reihe):
        if spanne == 0:
            continue
        plus_di = 100 * plus / spanne
        minus_di = 100 * minus / spanne
        summe = plus_di + minus_di
        werte.append(0.0 if summe == 0 else 100 * abs(plus_di - minus_di) / summe)
    return tuple(werte)


def _spread(preise: Sequence[float]) -> Optional[float]:
    kurz = sma(preise, 50)
    lang = sma(preise, 200)
    if kurz is None or lang is None:
        return None
    return kurz - lang


def _ist_ruecksetzer(preis, sma50, sma200, rsi_wert) -> bool:
    if sma50 is None or sma200 is None or rsi_wert is None:
        return False
    return preis > sma200 and sma50 > sma200 and 35 <= rsi_wert <= 48


def _starker_verlust(rendite_1, rendite_5) -> bool:
    return (rendite_1 is not None and rendite_1 <= -5) or (rendite_5 is not None and rendite_5 <= -8)


def _volumen_hebt_ab(volumen, schnitt) -> bool:
    return volumen is not None and schnitt not in (None, 0) and volumen > 1.5 * schnitt


def _rendite(werte: Sequence[float], tage: int) -> Optional[float]:
    if len(werte) <= tage or werte[-(tage + 1)] == 0:
        return None
    return (werte[-1] / werte[-(tage + 1)] - 1) * 100


def _fehlende_pflicht(schluesse: Sequence[float]) -> Tuple[str, ...]:
    fehlend = []
    if len(schluesse) < 200:
        fehlend.append("200 Handelstage")
    if rsi(schluesse, 14) is None:
        fehlend.append("RSI")
    return tuple(fehlend)


def _fehlende_hinweise(hat_bereinigt: bool, index_balken) -> Tuple[str, ...]:
    hinweise = []
    if not hat_bereinigt:
        hinweise.append("Bereinigter Kurs fehlt")
    if not index_balken:
        hinweise.append("Vergleichsindex fehlt")
    return tuple(hinweise)


def _markt_reihen(balken):
    hochs = tuple(bar.hoch if bar.hoch is not None else bar.schluss for bar in balken)
    tiefs = tuple(bar.tief if bar.tief is not None else bar.schluss for bar in balken)
    roh = tuple(bar.schluss for bar in balken)
    return hochs, tiefs, roh


def _zonen_fuer_kurs(hochs, tiefs, preis):
    historie_hoch = hochs[:-1]
    historie_tief = tiefs[:-1]
    if len(historie_hoch) < 15:
        return None, None, False
    stuetze, widerstand = zonen(historie_hoch, historie_tief, preis)
    bricht = widerstand is not None and preis > widerstand
    return stuetze, widerstand, bricht


def _volumen(balken):
    if not balken:
        return None, None
    aktuell = balken[-1].volumen
    werte = tuple(bar.volumen for bar in balken[-20:] if bar.volumen is not None)
    schnitt = sum(werte) / len(werte) if werte else None
    return aktuell, schnitt


def _vergleich(balken, index_balken):
    if not index_balken:
        return None, None
    aktie, index = _gemeinsame_kurse(balken, index_balken)
    return relativ(aktie, index, 60), _rendite(index, 20)


def _gemeinsame_kurse(aktie, index):
    if any(bar.zeit is None for bar in aktie) or any(bar.zeit is None for bar in index):
        return tuple(bar.bereinigt for bar in aktie), tuple(bar.bereinigt for bar in index)
    index_nach_tag = {_tag(bar.zeit): bar.bereinigt for bar in index}
    tage = tuple(tag for tag in (_tag(bar.zeit) for bar in aktie) if tag in index_nach_tag)
    aktie_nach_tag = {_tag(bar.zeit): bar.bereinigt for bar in aktie}
    return tuple(aktie_nach_tag[tag] for tag in tage), tuple(index_nach_tag[tag] for tag in tage)


def _tag(zeit: int):
    return datetime.fromtimestamp(zeit, ZoneInfo("UTC")).date()


def _jahresband(hochs, tiefs, hoch_52, tief_52):
    fenster_hoch = hochs[-252:]
    fenster_tief = tiefs[-252:]
    hoch = hoch_52 if hoch_52 is not None else (max(fenster_hoch) if fenster_hoch else None)
    tief = tief_52 if tief_52 is not None else (min(fenster_tief) if fenster_tief else None)
    return hoch, tief
