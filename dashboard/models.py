from dataclasses import dataclass

import pandas as pd


@dataclass
class MarketBook:
    platform: str
    market_url: str
    asks: pd.DataFrame
