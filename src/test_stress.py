"""Regressions for delayed VIX releases and mixed-frequency stress inputs."""
import unittest
import numpy as np
import pandas as pd
import derive as D


class StressTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=1400)
        self.series = pd.Series(20 + np.sin(np.arange(1400) / 13), index=self.dates)

    def test_newer_market_vix_is_used_without_replacing_official_history(self):
        official = self.series.iloc[:-1]
        market = pd.Series([999., 35.], index=self.dates[-2:])
        result = D.vix_series({'VIXCLS': official, 'VIX': market})
        self.assertEqual(result.iloc[-1], 35.)
        self.assertEqual(result.iloc[-2], official.iloc[-1])
        self.assertTrue(result.index.is_unique)
        pd.testing.assert_series_equal(D.vix_series({'VIX': market}), market)

    def test_older_market_quote_does_not_replace_official_close(self):
        pd.testing.assert_series_equal(
            D.vix_series({'VIXCLS': self.series, 'VIX': self.series.iloc[:-1] * 2}),
            self.series,
        )

    def test_no_observations_means_no_new_z_scores(self):
        source = self.series.iloc[:-3]
        result, used, _ = D.stress_composite({'VIXCLS': source})
        self.assertEqual(result.index[-1], source.index[-1])
        self.assertEqual(used, ['VIX'])
        window = source.iloc[-1250:]
        self.assertAlmostEqual(result.iloc[-1], (window.iloc[-1] - window.mean()) / window.std())

    def test_weekly_z_score_is_held_until_next_observation(self):
        weekly = self.series.iloc[::5].iloc[:-1]
        latest = self.series.copy()
        latest.iloc[-1] = 35.
        result, used, _ = D.stress_composite({'VIXCLS': latest, 'NFCI': weekly})
        daily_window = latest.iloc[-1250:]
        weekly_grid = D.daily(weekly).loc[:weekly.index[-1]].iloc[-1250:]
        expected = ((latest.iloc[-1] - daily_window.mean()) / daily_window.std()
                    + (weekly.iloc[-1] - weekly_grid.mean()) / weekly_grid.std()) / 2
        self.assertAlmostEqual(result.iloc[-1], expected)
        self.assertEqual(used, ['VIX', 'NFCI'])

    def test_frozen_daily_component_is_excluded(self):
        result, used, dropped = D.stress_composite({
            'VIXCLS': self.series, 'MOVE': self.series.iloc[:-30],
        })
        self.assertEqual(used, ['VIX'])
        self.assertTrue(any('MOVE' in item for item in dropped))
        self.assertFalse(result.empty)


if __name__ == '__main__':
    unittest.main()
