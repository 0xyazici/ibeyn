import csv
import html
import io
import json
import math
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json,text/csv,*/*",
}

BTC_KAYNAKLARI = [
    ("Coinbase", "https://api.coinbase.com/v2/prices/BTC-USD/spot",
     ["data", "amount"]),
    ("Kraken", "https://api.kraken.com/0/public/Ticker?pair=XBTUSD",
     ["result", "XXBTZUSD", "c", 0]),
    ("Blockchain.com", "https://blockchain.info/ticker",
     ["USD", "last"]),
]

ALTIN_URL = "https://api.gold-api.com/price/XAU"
MOEX_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/index/"
    "securities/IMOEX.json?iss.meta=off&iss.only=marketdata"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS5,DGS10"
YAHOO_HOSTLAR = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]


def http_get(url, timeout=25):
    istek = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(istek, timeout=timeout) as yanit:
        return yanit.read().decode("utf-8")


def http_json(url):
    return json.loads(http_get(url))


def sayi(deger):
    v = float(deger)
    if not math.isfinite(v):
        raise ValueError("Geçersiz sayı")
    return v


def pozitif(deger):
    v = sayi(deger)
    if v <= 0:
        raise ValueError("Geçersiz fiyat")
    return v


def kayit(ad, deger, tur, degisim=None, degisim_tur="yuzde", not_=""):
    return {
        "ad": ad,
        "deger": deger,
        "tur": tur,
        "degisim": degisim,
        "degisim_tur": degisim_tur,
        "not": not_,
    }


def bos(ad, tur):
    return kayit(ad, None, tur)


def btc_ortalama():
    fiyatlar = []

    for kaynak, url, yol in BTC_KAYNAKLARI:
        try:
            veri = http_json(url)
            for anahtar in yol:
                veri = veri[anahtar]
            fiyatlar.append(pozitif(veri))
        except Exception as hata:
            print(f"  BTC {kaynak} hatası: {type(hata).__name__}: {hata}")

    if not fiyatlar:
        raise RuntimeError("BTC kaynaklarının hiçbirinden veri alınamadı")

    ortalama = sum(fiyatlar) / len(fiyatlar)
    return kayit(
        "BTC/USD", ortalama, "usd",
        not_=f"{len(fiyatlar)}/{len(BTC_KAYNAKLARI)} kaynak ortalaması",
    )


def ons_altin():
    veri = http_json(ALTIN_URL)

    if veri.get("symbol") != "XAU":
        raise ValueError("Beklenmeyen altın sembolü")

    return kayit("ONS/USD", pozitif(veri["price"]), "usd",
                 not_="Gold API, USD / troy ons")


def yahoo(ad, sembol):
    son_hata = None

    for host in YAHOO_HOSTLAR:
        url = (
            f"https://{host}/v8/finance/chart/{quote(sembol, safe='')}"
            "?range=1d&interval=1d"
        )
        try:
            veri = http_json(url)
            meta = veri["chart"]["result"][0]["meta"]
            fiyat = pozitif(meta["regularMarketPrice"])

            onceki = meta.get("previousClose") or meta.get("chartPreviousClose")
            degisim = None
            if onceki:
                onceki = pozitif(onceki)
                degisim = (fiyat - onceki) / onceki * 100

            return kayit(ad, fiyat, "puan", degisim, not_=sembol)

        except Exception as hata:
            son_hata = hata

    raise RuntimeError(f"{type(son_hata).__name__}: {son_hata}")


def moex_imoex():
    veri = http_json(MOEX_URL)["marketdata"]
    sutunlar = veri["columns"]
    satir = veri["data"][0]
    kayitlar = dict(zip(sutunlar, satir))

    fiyat = kayitlar.get("CURRENTVALUE") or kayitlar.get("LASTVALUE")
    degisim = kayitlar.get("LASTCHANGEPRC")

    return kayit(
        "MOEX Rusya (IMOEX)",
        pozitif(fiyat),
        "puan",
        sayi(degisim) if degisim is not None else None,
        not_="Moskova Borsası ISS",
    )


def fred_tahviller():
    metin = http_get(FRED_URL)
    satirlar = list(csv.reader(io.StringIO(metin)))
    baslik = satirlar[0]
    govde = satirlar[1:]

    sonuc = {}

    for seri, ad in (("DGS5", "ABD 5 Yıllık Tahvil"),
                     ("DGS10", "ABD 10 Yıllık Tahvil")):
        try:
            idx = baslik.index(seri)
            gecerli = [
                (s[0], float(s[idx]))
                for s in govde
                if len(s) > idx and s[idx] not in ("", ".")
            ]

            tarih, son = gecerli[-1]
            onceki = gecerli[-2][1] if len(gecerli) > 1 else None
            degisim_bp = (son - onceki) * 100 if onceki is not None else None

            sonuc[seri] = kayit(
                ad, son, "yuzde", degisim_bp, "bp",
                not_=f"FRED {seri}, son veri günü: {tarih}",
            )
        except Exception as hata:
            print(f"  {seri} hatası: {type(hata).__name__}: {hata}")
            sonuc[seri] = bos(ad, "yuzde")

    return sonuc


def guvenli(ad, tur, fonksiyon):
    try:
        k = fonksiyon()
        print(f"OK   {ad}: {k['deger']}")
        return k
    except Exception as hata:
        print(f"HATA {ad}: {type(hata).__name__}: {hata}")
        return bos(ad, tur)


def veri_topla():
    tahvil = {}
    try:
        tahvil = fred_tahviller()
        for k in tahvil.values():
            print(f"OK   {k['ad']}: {k['deger']}")
    except Exception as hata:
        print(f"HATA FRED: {type(hata).__name__}: {hata}")

    t5 = tahvil.get("DGS5", bos("ABD 5 Yıllık Tahvil", "yuzde"))
    t10 = tahvil.get("DGS10", bos("ABD 10 Yıllık Tahvil", "yuzde"))

    return [
        ("Kripto ve Altın", [
            guvenli("BTC/USD", "usd", btc_ortalama),
            guvenli("ONS/USD", "usd", ons_altin),
        ]),
        ("Borsa İstanbul", [
            guvenli("BIST 100", "puan", lambda: yahoo("BIST 100", "XU100.IS")),
            guvenli("BIST 30", "puan", lambda: yahoo("BIST 30", "XU030.IS")),
        ]),
        ("ABD Endeksleri", [
            guvenli("S&P 500", "puan", lambda: yahoo("S&P 500", "^GSPC")),
            guvenli("Dow Jones", "puan", lambda: yahoo("Dow Jones", "^DJI")),
            guvenli("Nasdaq", "puan", lambda: yahoo("Nasdaq", "^IXIC")),
        ]),
        ("İngiltere ve Rusya", [
            guvenli("FTSE 100", "puan", lambda: yahoo("FTSE 100", "^FTSE")),
            guvenli("MOEX Rusya", "puan", moex_imoex),
        ]),
        ("ABD Tahvil Faizi", [t5, t10]),
    ]


def deger_yazisi(k):
    v = k["deger"]
    if v is None:
        return "—"
    if k["tur"] == "usd":
        return f"${v:,.2f}"
    if k["tur"] == "yuzde":
        return f"%{v:.2f}"
    return f"{v:,.2f}"


def degisim_yazisi(k):
    d = k["degisim"]
    if d is None or k["deger"] is None:
        return "", "notr"

    sinif = "yukari" if d > 0 else "asagi" if d < 0 else "notr"

    if k["degisim_tur"] == "bp":
        return f"{d:+.0f} bp", sinif

    return f"{d:+.2f}%", sinif


def satir_html(k):
    degisim, sinif = degisim_yazisi(k)
    ipucu = html.escape(k["not"], quote=True)

    return (
        f'<div class="satir" title="{ipucu}">'
        f'<span class="ad">{html.escape(k["ad"])}</span>'
        f'<span class="deger">{html.escape(deger_yazisi(k))}</span>'
        f'<span class="degisim {sinif}">{html.escape(degisim)}</span>'
        "</div>"
    )


SABLON = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#f5f3ee">
    <meta http-equiv="refresh" content="900">
    <title>Piyasa Paneli</title>

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link
        href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700&display=swap"
        rel="stylesheet"
    >

    <style>
        * { box-sizing: border-box; }

        html { min-height: 100%; background: #f5f3ee; }

        body {
            margin: 0;
            min-height: 100vh;
            padding: 32px 14px 40px;
            font-family: Arial, Helvetica, sans-serif;
            color: #faf9f6;
            background:
                radial-gradient(ellipse at 24% 18%,
                    rgba(255, 255, 255, 0.98), transparent 55%),
                radial-gradient(ellipse at 78% 80%,
                    rgba(190, 198, 209, 0.27), transparent 56%),
                #f5f3ee;
        }

        .panel {
            width: min(760px, 100%);
            margin: 0 auto;
            display: grid;
            gap: 18px;
        }

        .kart {
            position: relative;
            isolation: isolate;
            overflow: hidden;
            padding: 20px clamp(16px, 4vw, 34px) 12px;
            border: 1px solid rgba(255, 255, 255, 0.62);
            border-radius: 22px;
            background: linear-gradient(
                135deg, rgba(83, 89, 98, 0.88), rgba(40, 45, 53, 0.95));
            -webkit-backdrop-filter: blur(20px);
            backdrop-filter: blur(20px);
            box-shadow:
                0 18px 44px rgba(35, 40, 48, 0.13),
                0 5px 14px rgba(35, 40, 48, 0.06),
                inset 0 1px 0 rgba(255, 255, 255, 0.25);
        }

        .kart::before {
            content: "";
            position: absolute;
            z-index: -1;
            inset: 0;
            pointer-events: none;
            background: linear-gradient(
                115deg, rgba(255, 255, 255, 0.14), transparent 42%,
                rgba(255, 255, 255, 0.02) 70%, transparent);
        }

        h2 {
            margin: 0 0 6px;
            font-family: "Orbitron", "Courier New", monospace;
            font-size: clamp(10px, 1.9vw, 13px);
            font-weight: 500;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #bdc3cc;
        }

        .satir {
            display: grid;
            grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) 84px;
            align-items: baseline;
            gap: 10px;
            padding: 12px 0;
            border-top: 1px solid rgba(255, 255, 255, 0.10);
        }

        h2 + .satir { border-top: none; }

        .ad {
            font-family: "Orbitron", "Courier New", monospace;
            font-size: clamp(11px, 2.4vw, 16px);
            font-weight: 500;
            color: #d7dbe1;
        }

        .deger {
            text-align: right;
            font-family: "Orbitron", "Courier New", monospace;
            font-size: clamp(16px, 4.2vw, 30px);
            font-weight: 600;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.02em;
            color: #faf9f6;
            white-space: nowrap;
        }

        .degisim {
            text-align: right;
            font-family: "Orbitron", "Courier New", monospace;
            font-size: clamp(10px, 2vw, 13px);
            font-weight: 500;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }

        .yukari { color: #8fe3b0; }
        .asagi { color: #ff9f9f; }
        .notr { color: #a9b0ba; }

        .tarih {
            margin: 4px 0 0;
            text-align: center;
            font-family: "Orbitron", "Courier New", monospace;
            font-size: clamp(10px, 1.6vw, 12px);
            font-weight: 500;
            letter-spacing: 0.10em;
            color: rgba(54, 57, 63, 0.56);
        }

        @media (max-width: 400px) {
            .satir { grid-template-columns: 1fr auto; row-gap: 2px; }
            .degisim { grid-column: 2; }
        }
    </style>
</head>

<body>
    <main class="panel">
        {{KARTLAR}}
        <p class="tarih">
            <time datetime="{{ISO}}">{{TARIH}} · {{SAAT}}</time>
        </p>
    </main>
</body>
</html>
"""


def main():
    bolumler = veri_topla()

    toplam = sum(len(k) for _, k in bolumler)
    basarili = sum(
        1 for _, kayitlar in bolumler for k in kayitlar
        if k["deger"] is not None
    )

    print(f"Başarılı veri: {basarili}/{toplam}")

    if basarili == 0:
        raise SystemExit("Hiçbir veri alınamadı. index.html değiştirilmedi.")

    kartlar = []
    for baslik, kayitlar in bolumler:
        satirlar = "\n".join(satir_html(k) for k in kayitlar)
        kartlar.append(
            f'<section class="kart"><h2>{html.escape(baslik)}</h2>'
            f"{satirlar}</section>"
        )

    zaman = datetime.now(timezone(timedelta(hours=3)))

    cikti = (
        SABLON
        .replace("{{KARTLAR}}", "\n".join(kartlar))
        .replace("{{ISO}}", zaman.isoformat(timespec="seconds"))
        .replace("{{TARIH}}", zaman.strftime("%d.%m.%Y"))
        .replace("{{SAAT}}", zaman.strftime("%H:%M"))
    )

    Path("index.html").write_text(cikti, encoding="utf-8")
    print("index.html oluşturuldu.")


if __name__ == "__main__":
    main()
