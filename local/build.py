"""Build local/doorman.db, the SQLite stand-in for hackathon_gold.sierra.

Same six data products, same tags as sql/setup.sql + catalogue_products.sql +
catalogue_balance.sql left them on 21 Oct, from the same CSVs. db.py calls build()
when LOCAL_DB is set and the file is missing; run this file directly to rebuild.
"""
import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
SCHEMA = "sierra"
YOUNIS, JOSE = "younis@sierra.example", "jose@sierra.example"

# table -> (owner, sensitivity, licence_cost_gbp, domain, description)
TAGS = {
    "eod_prices": (YOUNIS, "licensed", "120", "Market data",
                   "Licensed end-of-day OHLCV from Yahoo and Nasdaq, 60 EM and GCC names, Jan 2024 to date"),
    "daily_summary": (YOUNIS, "internal", "0", "Market data",
                      "Delayed daily closes, free for internal use. Need OHLCV or the Nasdaq leg? Request eod_prices"),
    "positions": (YOUNIS, "confidential", "0", "Trading book",
                  "Live desk positions by ticker and book. Confidential: desk head approval only"),
    "corporate_actions": (JOSE, "licensed", "40", "Market data",
                          "Dividends and splits for the 60-name universe, Jan 2024 to date. Licensed per user"),
    "vendor_faults": (JOSE, "internal", "0", "Operations",
                      "Daily price faults where Yahoo and Nasdaq disagree, priced in GBP exposure"),
    "desk_mtm": (JOSE, "confidential", "0", "Trading book",
                 "Mark-to-market by book from live positions and the latest close. "
                 "Confidential: desk head approval only"),
}


def build(path: Path = HERE / "doorman.db") -> Path:
    bars = pd.read_csv(HERE / "bronze_vendor_bars.csv")
    positions = pd.read_csv(HERE / "positions.csv")[["ticker", "quantity", "book"]]
    faults = pd.read_csv(HERE / "gold_faults_preview.csv")[
        ["ticker", "venue", "date", "fault", "detail", "severity", "gbp_exposure", "book", "status"]]

    eod = bars[["vendor", "ticker", "venue", "date", "open", "high", "low", "close", "volume", "adj_close"]]
    yahoo = bars[bars.vendor == "yahoo"]
    corp = yahoo[(yahoo.dividends > 0) | (yahoo.splits > 0)][["ticker", "venue", "date", "dividends", "splits"]]
    corp = corp.rename(columns={"dividends": "dividend", "splits": "split_ratio"})
    latest = yahoo.sort_values("date").groupby("ticker").tail(1)[["ticker", "close"]]
    mtm = positions.merge(latest, on="ticker", how="left")
    mtm["mtm_local"] = (mtm.quantity * mtm.close).round(0)

    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    with sqlite3.connect(tmp) as con:
        for name, df in {"eod_prices": eod, "positions": positions, "vendor_faults": faults,
                         "corporate_actions": corp,
                         "daily_summary": yahoo[["ticker", "venue", "date", "close"]],
                         "desk_mtm": mtm[["book", "ticker", "quantity", "close", "mtm_local"]]}.items():
            df.to_sql(name, con, index=False)
        con.execute("CREATE TABLE table_tags (schema_name TEXT, table_name TEXT, tag_name TEXT, tag_value TEXT)")
        con.executemany("INSERT INTO table_tags VALUES (?, ?, ?, ?)", [
            (SCHEMA, t, k, v) for t, vals in TAGS.items()
            for k, v in zip(("data_owner", "sensitivity", "licence_cost_gbp", "domain", "description"), vals)])
    con.close()
    tmp.replace(path)
    return path


if __name__ == "__main__":
    print(build())
