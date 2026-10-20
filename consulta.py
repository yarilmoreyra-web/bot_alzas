"""Consulta bajo demanda: compara el precio actual contra el de hace N minutos
(15 por defecto) para toda la watchlist y envía el top de alzas a Telegram.

Pensado para correr en GitHub Actions (se dispara desde el celular), pero
también funciona en cualquier computadora con las variables de entorno."""
import os
import time
import logging
from datetime import datetime, timedelta

import pytz
import requests
from longbridge.openapi import Config, QuoteContext, Period, AdjustType

try:
    from longbridge.openapi import TradeSessions
except ImportError:          # versiones que no lo exponen
    TradeSessions = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("consulta")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

MINUTOS = int(os.environ.get("MINUTOS") or 15)
MIN_VOL = int(os.environ.get("VOLUMEN_MINIMO") or 100000)   # volumen negociado en el intervalo
TOP_N = 25
RVOL_DIAS = int(os.environ.get("RVOL_DIAS") or 20)   # días para el promedio de volumen diario

TZ_NY = pytz.timezone("America/New_York")
TZ_LIMA = pytz.timezone("America/Lima")

_WATCHLIST_RAW = [
   
   "AAOI.US", "AAPL.US", "ACLS.US", "AGX.US", "AKAM.US", "ALAB.US", "ALC.US", "ALNY.US", 
   "ALVO.US", "SNOW.US", "AMAT.US", "AMD.US", "AMKR.US", "AMT.US", "AMZN.US", "ANET.US", 
   "APA.US", "APH.US", "APLD.US", "APP.US", "ARM.US", "ARQT.US", "ASML.US", "ASX.US", 
   "AUNA.US", "AVGO.US", "AXP.US", "AZO.US", "BABA.US", "BAP.US", "BBOT.US", "BE.US", 
   "BGC.US", "C.US", "CAI.US", "CAMT.US", "CAT.US", "CBRS.US", "CELC.US", "CF.US", 
   "CIEN.US", "CIFR.US", "CLOV.US", "CLSK.US", "CNOB.US", "COF.US", "COHR.US", "CORZ.US", 
   "COUR.US", "CRDO.US", "CRGY.US", "CRM.US", "CRWD.US", "CRWV.US", "CSCO.US", "CTVA.US", 
   "CVX.US", "DELL.US", "DFTX.US", "DIOD.US", "DIS.US", "DNLI.US", "DOCN.US", "DUOL.US", 
   "DXPE.US", "DY.US", "ENVA.US", "ESAB.US", "ETN.US", "ETOR.US", "FCX.US", "FDX.US", 
   "FICO.US", "FIX.US", "FLEX.US", "FPS.US", "FRVO.US", "GE.US", "GEV.US", "GLW.US", 
   "GNRC.US", "GOOGL.US", "GSK.US", "HAE.US", "HALO.US", "HDB.US", "HEI.US", "HIMS.US", 
   "HOOD.US", "HPQ.US", "HSBC.US", "HUM.US", "IBM.US", "IBRX.US", "IFS.US", "ILMN.US", 
   "IMMP.US", "IMOS.US", "INIO.US", "INTC.US", "INTU.US", "IONQ.US", "IREN.US", "JBL.US", 
   "JCI.US", "JNJ.US", "JPM.US", "KEEL.US", "KEYS.US", "KLAC.US", "KO.US", "LFCR.US", 
   "LIN.US", "LITE.US", "LLY.US", "LMT.US", "LRCX.US", "LW.US", "MA.US", "MANE.US", 
   "MCD.US", "MCK.US", "MELI.US", "META.US", "MNSO.US", "MPWR.US", "MRNA.US", "MRVL.US", 
   "MSFT.US", "MSTR.US", "MT.US", "MTRN.US", "MTSI.US", "MTZ.US", "MU.US", "MXL.US", 
   "NBIS.US", "NEOG.US", "NFLX.US", "NOK.US", "NOW.US", "NPO.US", "NRG.US", "NTLA.US", 
   "NTRA.US", "NVDA.US", "OKTA.US", "ORCL.US", "P.US", "PANW.US", "PCVX.US", "PENG.US", 
   "PEP.US", "PGNY.US", "PLTR.US", "PNC.US", "POWL.US", "PTGX.US", "PWR.US", "QCOM.US", 
   "QMCO.US", "RGTI.US", "ROK.US", "RTX.US", "RUSHB.US", "RVMD.US", "SEI.US", "SHAZ.US", 
   "SHOP.US", "SIMO.US", "SITM.US", "SKHY.US", "SLS.US", "SLXN.US", "SMCI.US", "SMMT.US", 
   "SNDK.US", "SPGI.US", "SOFI.US", "SPCX.US", "SQM.US", "SRRK.US", "STM.US", "STRL.US", 
   "STX.US", "SYK.US", "SYNA.US", "TE.US", "TEL.US", "TER.US", "TLN.US", "TMO.US", "TOYO.US", 
   "TSEM.US", "TSLA.US", "TSM.US", "TT.US", "TTMI.US", "TWLO.US", "TXG.US", "TXN.US", 
   "TXT.US", "UBER.US", "V.US", "VICR.US", "VIK.US", "VKTX.US", "VRT.US", "VSH.US", 
   "VST.US", "VSXY.US", "WAT.US", "WDC.US", "WELL.US", "WMT.US", "WULF.US", "XE.US", 
   "XOM.US", "YPF.US", "ZS.US"
]
WATCHLIST = list(dict.fromkeys(_WATCHLIST_RAW))


# ---------------------------------------------------------------- Telegram
def enviar_telegram(texto, parse_mode="Markdown"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Faltan tokens de Telegram.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texto}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(url, json=payload, timeout=15)
        if not r.ok:
            log.error("Telegram respondió %s: %s", r.status_code, r.text)
    except requests.RequestException as e:
        log.error("Error al enviar a Telegram: %s", e)


def enviar_en_bloques(encabezado, items, limite=3800):
    """Telegram acepta máx. 4096 caracteres por mensaje: se parte en varios."""
    mensajes, actual = [], encabezado
    for it in items:
        if len(actual) + len(it) > limite:
            mensajes.append(actual)
            actual = ""
        actual += it
    if actual.strip():
        mensajes.append(actual)
    for m in mensajes:
        enviar_telegram(m)
        time.sleep(0.5)


# ---------------------------------------------------------------- Longbridge
_variante = 0   # qué forma de llamar a candlesticks funciona con la versión instalada


def pedir_velas(ctx, simbolo, n=30):
    """Últimas n velas de 1 minuto, incluyendo pre, regular, post y overnight
    cuando la versión de la librería lo permite."""
    global _variante
    variantes = []
    if TradeSessions is not None:
        variantes.append(lambda: ctx.candlesticks(
            simbolo, Period.Min_1, n, AdjustType.NoAdjust, trade_sessions=TradeSessions.All))
        variantes.append(lambda: ctx.candlesticks(
            simbolo, Period.Min_1, n, AdjustType.NoAdjust, trade_session=TradeSessions.All))
    variantes.append(lambda: ctx.candlesticks(simbolo, Period.Min_1, n, AdjustType.NoAdjust))

    for intento in range(3):
        try:
            return variantes[_variante]()
        except TypeError:
            if _variante + 1 < len(variantes):
                _variante += 1          # esa forma no existe: probar la siguiente
                continue
            raise
        except Exception as e:
            log.warning("%s: %s (reintento %d)", simbolo, e, intento + 1)
            time.sleep(1.5)
    return None


def sesion_actual(t):
    """Qué campo del quote corresponde a la sesión en curso (hora de Nueva York)."""
    m = t.hour * 60 + t.minute
    if 4 * 60 <= m < 9 * 60 + 30:
        return "pre_market_quote"
    if 9 * 60 + 30 <= m < 16 * 60:
        return None                      # sesión regular: campos del quote principal
    if 16 * 60 <= m < 20 * 60:
        return "post_market_quote"
    return "overnight_quote"


def datos_sesion(ctx, simbolos, atributo):
    """VWAP (valor negociado / volumen) y máximo (HOD) de la sesión en curso."""
    res = {}
    try:
        for q in ctx.quote(simbolos):
            fuente = getattr(q, atributo, None) if atributo else q
            if not fuente:
                continue
            vol = int(getattr(fuente, "volume", 0) or 0)
            turnover = float(getattr(fuente, "turnover", 0) or 0)
            hod = float(getattr(fuente, "high", 0) or 0)
            prev = float(q.prev_close or 0)      # cierre anterior, del quote principal
            res[q.symbol] = (turnover / vol if vol > 0 and turnover > 0 else 0.0, hod, prev, vol)
    except Exception as e:
        log.warning("No pude obtener VWAP/HOD: %s", e)
    return res


def promedio_volumen(ctx, simbolo, descartar_hoy=False):
    """Volumen diario promedio de los últimos RVOL_DIAS días (velas diarias)."""
    velas = None
    for intento in range(3):
        try:
            velas = ctx.candlesticks(simbolo, Period.Day, RVOL_DIAS + 1, AdjustType.NoAdjust)
            break
        except Exception as e:
            log.warning("%s (promedio de volumen): %s (reintento %d)", simbolo, e, intento + 1)
            time.sleep(1.5)
    if not velas:
        return 0.0
    velas = sorted(velas, key=lambda c: c.timestamp)
    if descartar_hoy:
        velas = velas[:-1]            # quita la vela de hoy, que está incompleta
    vols = [int(c.volume or 0) for c in velas[-RVOL_DIAS:] if int(c.volume or 0) > 0]
    return sum(vols) / len(vols) if vols else 0.0


def crear_config():
    """Crea la conexión con Longbridge activando los datos overnight
    (según su documentación hay que activarlos de forma explícita)."""
    os.environ.setdefault("LONGBRIDGE_ENABLE_OVERNIGHT", "true")
    args = (
        os.environ.get("LONGBRIDGE_APP_KEY"),
        os.environ.get("LONGBRIDGE_APP_SECRET"),
        os.environ.get("LONGBRIDGE_ACCESS_TOKEN"),
    )
    try:
        return Config.from_apikey(*args, enable_overnight=True)
    except TypeError:            # esta versión no acepta el parámetro
        return Config.from_apikey(*args)


# ---------------------------------------------------------------- Principal
def main():
    inicio = datetime.now(TZ_NY)
    hora_txt = f"{inicio.strftime('%H:%M')} ET / {inicio.astimezone(TZ_LIMA).strftime('%H:%M')} Lima"
    log.info("Consulta: ahora vs hace %d min (%d tickers)", MINUTOS, len(WATCHLIST))

    try:
        config = crear_config()
        ctx = QuoteContext(config)
    except Exception as e:
        log.exception("No se pudo conectar con Longbridge")
        enviar_telegram(f"⚠️ No pude conectar con Longbridge: {e}", parse_mode=None)
        raise

    datos = {}
    for s in WATCHLIST:
        velas = pedir_velas(ctx, s)
        if velas:
            datos[s] = sorted(velas, key=lambda c: c.timestamp)
        time.sleep(0.12)          # respeta el límite de peticiones por segundo

    if not datos:
        enviar_telegram("⚠️ Longbridge no devolvió datos. Revisa el token o los permisos.", parse_mode=None)
        return

    # "Ahora" = la vela más reciente de todo el conjunto
    ahora_ts = max(v[-1].timestamp for v in datos.values())
    objetivo = ahora_ts - timedelta(minutes=MINUTOS)

    filas = []
    for simbolo, velas in datos.items():
        previas = [c for c in velas if c.timestamp <= objetivo]
        if not previas:
            continue
        p_base = float(previas[-1].close)
        p_ahora = float(velas[-1].close)
        vol = sum(int(c.volume or 0) for c in velas if c.timestamp > objetivo)
        if p_base > 0 and p_ahora > 0 and vol >= MIN_VOL:
            filas.append({
                "simbolo": simbolo,
                "base": p_base,
                "ahora": p_ahora,
                "vol": vol,
                "pct": (p_ahora - p_base) / p_base * 100,
            })

    filas = [f for f in filas if f["pct"] > 0]
    filas.sort(key=lambda x: x["pct"], reverse=True)
    top = filas[:TOP_N]

    if not top:
        enviar_telegram(
            f"⚠️ Consulta de las {hora_txt}: ninguna acción subió con volumen > {MIN_VOL:,} "
            f"en los últimos {MINUTOS} min ({len(datos)} tickers con datos).",
            parse_mode=None,
        )
        return

    encabezado = (
        f"⏱ *TOP {len(top)} ALZAS ÚLTIMOS {MINUTOS} MIN* ⏱\n"
        f"_Consulta: {hora_txt}_\n"
        f"_Filtro: Vol en el intervalo > {MIN_VOL:,} · {len(datos)} tickers analizados_\n\n"
    )
    sesion = sesion_actual(inicio)
    extra = datos_sesion(ctx, [f["simbolo"] for f in top], sesion)

    # RVOL: solo para el top (≈25 llamadas extra, no para las 158 acciones)
    descartar_hoy = sesion in (None, "post_market_quote")
    promedios = {}
    for f in top:
        promedios[f["simbolo"]] = promedio_volumen(ctx, f["simbolo"], descartar_hoy)
        time.sleep(0.12)

    items = []
    for i, f in enumerate(top, 1):
        vwap, hod, prev, vol_ses = extra.get(f["simbolo"], (0.0, 0.0, 0.0, 0))
        prom = promedios.get(f["simbolo"], 0.0)
        txt = (
            f"*{i}. {f['simbolo']}*\n"
            f"   📈 Subida: `{f['pct']:+.2f}%`\n"
            f"   💰 Ahora: `${f['ahora']:.2f}` (Hace {MINUTOS} min: `${f['base']:.2f}`)\n"
        )
        if prev > 0:
            txt += f"   📆 Cierre ayer: `${prev:.2f}` (precio {(f['ahora'] / prev - 1) * 100:+.1f}%)\n"
        if vwap > 0:
            txt += f"   📐 VWAP: `${vwap:.2f}` (precio {(f['ahora'] / vwap - 1) * 100:+.1f}%)\n"
        if hod > 0:
            txt += f"   🔝 HOD: `${hod:.2f}` (precio {(f['ahora'] / hod - 1) * 100:+.1f}%)\n"
        if prom > 0 and vol_ses > 0:
            txt += f"   🔥 RVOL: `{vol_ses / prom:.2f}x` (vol sesión vs prom. {RVOL_DIAS}d: `{prom:,.0f}`)\n"
        txt += f"   📊 Vol en {MINUTOS} min: `{f['vol']:,}`\n\n"
        items.append(txt)
    enviar_en_bloques(encabezado, items)
    log.info("Consulta enviada (%d acciones).", len(top))


if __name__ == "__main__":
    main()
