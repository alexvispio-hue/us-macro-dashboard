"""Offline regression tests for new calculations and missing source handling."""
import json
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import market
import sources

class MarketTests(unittest.TestCase):
    def test_rsi_boundaries(self):
        self.assertEqual(market.rsi(pd.Series(np.arange(40))).iloc[-1],100)
        self.assertEqual(market.rsi(pd.Series(-np.arange(40))).iloc[-1],0)
        self.assertEqual(market.rsi(pd.Series([12.]*40)).iloc[-1],50)

    def test_cot_sort_numeric_deduplicate(self):
        def row(t,n): return dict(report_date_as_yyyy_mm_dd=t,m_money_positions_long_all=str(n),m_money_positions_short_all='5',open_interest_all='50')
        result=market.parse_cot(json.dumps([row('2026-09-22',20),row('2026-09-15',10),row('2026-09-22',30)]))
        self.assertEqual(list(result.long),[10,30])
        self.assertTrue(result.index.is_monotonic_increasing)

    def test_index_uses_only_past_and_handles_constant(self):
        s=pd.Series(np.arange(180,dtype=float))
        self.assertAlmostEqual(market.normalized(s).iloc[-1],100)
        self.assertAlmostEqual(market.normalized(-s).iloc[-1],-100)
        self.assertTrue(market.normalized(pd.Series([5.]*180)).isna().all())
        before=market.normalized(s.iloc[:100])
        pd.testing.assert_series_equal(before,market.normalized(s).iloc[:100])

    def test_missing_data_builds_empty_panels(self):
        empty_bars=pd.DataFrame(columns=['open','high','low','close','volume'],dtype=float)
        empty_cot=pd.DataFrame(columns=['long','short','oi'],dtype=float)
        with patch.object(market,'bars',return_value=empty_bars),patch.object(market,'cot',return_value=empty_cot),patch.object(sources,'fetch_fred',return_value=pd.Series(dtype=float)):
            result=market.build({})
        self.assertEqual(len(result['columns']),2)
        self.assertEqual(len(result['curves']),3)
        self.assertTrue(all(v['value'] is None for c in result['curves'] for v in c['values']))
        json.dumps(result,allow_nan=False)

    def test_offline_never_calls_network(self):
        with patch.object(sources,'OFFLINE',True),patch.object(sources.SESSION,'get') as get:
            with self.assertRaises(sources.HostBlocked): sources._get('https://example.com')
            get.assert_not_called()

if __name__=='__main__': unittest.main()
