"""Regression tests for units, calendar alignment and missing-source behavior."""
import unittest
import numpy as np
import pandas as pd
import catalogue

class CatalogueTests(unittest.TestCase):
    def workspaces(self,raw):
        return {w['id']:w for w in catalogue.build(raw,[],{'columns':[]})}
    def panel(self,workspaces,pid):
        return next(p for w in workspaces.values() for c in w['columns'] for p in c['panels'] if p['id']==pid)
    def test_empty_sources_keep_navigation(self):
        workspaces=self.workspaces({})
        self.assertGreaterEqual(len(workspaces),27)
        for w in workspaces.values():
            for c in w['columns']:
                for p in c['panels']:
                    self.assertFalse(any(s['data'] for s in p['series']))
    def test_inflation_changes_use_observations(self):
        dates=pd.date_range('2023-01-01',periods=24,freq='MS')
        raw={'CPIAUCSL':pd.Series(100*1.01**np.arange(24),index=dates)}
        ws=self.workspaces(raw)
        yoy=self.panel(ws,'cpi-yoy')['series'][0]['lastRaw']
        momentum=self.panel(ws,'momentum-CPIAUCSL')['series'][0]['lastRaw']
        self.assertAlmostEqual(yoy,(1.01**12-1)*100)
        self.assertAlmostEqual(momentum,yoy)
        self.assertEqual(self.panel(ws,'cpi-yoy')['series'][0]['asof'],'2024-12-01')
    def test_dollar_units(self):
        date=pd.to_datetime(['2026-01-01'])
        ws=self.workspaces({k:pd.Series([v],index=date) for k,v in {'GFDEBTN':39_000_000,'GDP':33_000,'TOTALSL':5_000_000}.items()})
        for pid,expected in [('debt-level',39),('gdp-level',33),('consumercredit',5000)]:
            self.assertEqual(self.panel(ws,pid)['series'][0]['lastRaw'],expected)
    def test_broker_ratio_uses_quarter_end_money(self):
        raw={'BOGZ1FL663067003Q':pd.Series([1_000_000.],index=pd.to_datetime(['2026-04-01'])),
             'M2SL':pd.Series([10_000.,20_000.,25_000.],index=pd.to_datetime(['2026-04-01','2026-05-01','2026-06-01']))}
        row=self.panel(self.workspaces(raw),'broker-m2')['series'][0]
        self.assertEqual(row['lastRaw'],4)
        self.assertEqual(row['asof'],'2026-06-30')
    def test_ids_are_unique_in_catalogue(self):
        ids=[p['id'] for w in self.workspaces({}).values() for c in w['columns'] for p in c['panels']]
        self.assertEqual(len(ids),len(set(ids)))

class CalendarAndFreshnessTests(unittest.TestCase):
    def test_missing_month_does_not_turn_yoy_into_thirteen_months(self):
        dates=pd.date_range('2023-01-01',periods=25,freq='MS').delete(6)
        data=pd.Series(np.arange(len(dates))+100.,index=dates)
        result=catalogue.calendar_change(data)
        self.assertAlmostEqual(result.loc['2024-01-01'],(data.loc['2024-01-01']/data.loc['2023-01-01']-1)*100)
        self.assertTrue(pd.isna(result.loc['2024-07-01']))
    def test_missing_month_does_not_change_three_month_horizon(self):
        dates=pd.to_datetime(['2023-01-01','2023-02-01','2023-04-01','2023-05-01'])
        result=catalogue.calendar_change(pd.Series([100.,102.,105.,106.],index=dates),months=3,annualize=True)
        self.assertAlmostEqual(result.loc['2023-04-01'],(1.05**4-1)*100)
    def test_broker_ratio_rejects_missing_quarter_end_denominator(self):
        raw={'BOGZ1FL663067003Q':pd.Series([1_000_000.],index=pd.to_datetime(['2026-04-01'])),
             'M2SL':pd.Series([25_000.],index=pd.to_datetime(['2026-04-01']))}
        workspaces=catalogue.build(raw,[],{'columns':[]})
        panel=next(p for w in workspaces for c in w['columns'] for p in c['panels'] if p['id']=='broker-m2')
        self.assertEqual(panel['series'][0]['data'],[])
        self.assertIsNone(panel['series'][0]['asof'])
    def test_monthly_source_cadence_survives_daily_display_grid(self):
        import derive
        from unittest.mock import patch
        monthly=pd.Series(np.arange(12.)+100,index=pd.date_range('2025-01-01',periods=12,freq='MS'))
        daily=monthly.reindex(pd.date_range('2025-01-01','2026-01-31'),method='ffill')
        with patch.object(derive.pd.Timestamp,'today',return_value=pd.Timestamp('2026-01-31')):
            row=derive._s('monthly',daily,'#fff',stamp=monthly.index[-1],freshness_source=monthly)
        self.assertFalse(row['stale'])
        self.assertEqual(row['asof'],'2025-12-01')
    def test_core_rows_are_not_downloaded_twice(self):
        from unittest.mock import patch
        row=pd.Series([1.],index=pd.to_datetime(['2026-01-01']))
        with patch.dict(catalogue.FRED,{'GDP':'GDP'},clear=True),patch.dict(catalogue.YAHOO,{},clear=True),patch.object(catalogue.sources,'fetch_fred') as fetch,patch.object(catalogue.sources,'manual_series',return_value={}):
            self.assertIs(catalogue.load({'GDP':row})['GDP'],row)
        fetch.assert_not_called()

if __name__=='__main__':unittest.main()
