"""Guard market breadth denominators and same-session sector comparisons."""
import datetime as dt
import unittest
from unittest.mock import patch

import pandas as pd

import market_today as M


class MarketTodayTests(unittest.TestCase):
    def test_breadth_uses_all_three_groups_and_ignores_invalid_dates(self):
        year = dt.date.today().year - 1
        text = ('Date,Advances,Declines,Unchanged\n'
                f'12/29/{year} 0:00:00,40,50,10\n'
                f'12/30/{year} 0:00:00,100,-1,2\n'
                f'1/2/{year + 2} 0:00:00,900,1,1\n')
        breadth = M.parse_breadth(text, year)
        dates = pd.to_datetime([f'{year}-12-28', f'{year}-12-29'])
        workspaces = [{'id': 'sectors', 'columns': []}]
        with patch.object(M, 'fetch_breadth', return_value=breadth):
            result = M.build({'SPX': pd.Series([100., 104.], index=dates)}, workspaces)
        self.assertEqual(result['breadth']['date'], f'{year}-12-29')
        self.assertEqual(result['breadth']['share'], 40)
        self.assertEqual(result['breadth']['counts']['Unchanged'], 10)

    def test_sector_without_matching_session_is_unranked(self):
        dates = pd.to_datetime(['2025-11-25', '2025-11-26', '2025-11-28'])
        sector = {'id': 'sector-XLK', 'title': 'Technology', 'source_ids': ['XLK']}
        workspaces = [{'id': 'sectors', 'columns': [{'panels': [sector]}]}]
        raw = {'SPX': pd.Series([100., 101., 104.], index=dates),
               'XLK': pd.Series([100., 110.], index=dates[:2])}
        with patch.object(M, 'fetch_breadth', return_value=pd.DataFrame(columns=M.NASDAQ_COUNTS, dtype=float)):
            result = M.build(raw, workspaces)
        self.assertEqual(result['session'], '2025-11-28')
        self.assertIsNone(result['sectors'][0]['delta'])
        self.assertIsNone(result['breadth']['share'])
