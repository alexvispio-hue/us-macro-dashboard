"""Check that regular and shaded meetings use their final date."""
import unittest

from event_calendar import fed_dates


class EventCalendarTests(unittest.TestCase):
    def test_fed_meetings_with_and_without_projection_styling(self):
        html = '''
        <h4><a id="42828">2026 FOMC Meetings</a></h4>
        <div class="fomc-meeting__month col-xs-5"><strong>October</strong></div>
        <div class="fomc-meeting__date col-xs-4">27-28</div>
        <div class="fomc-meeting--shaded fomc-meeting__month col-xs-5"><strong>December</strong></div>
        <div class="fomc-meeting__date col-xs-4">8-9*</div>
        '''
        self.assertEqual([row['date'] for row in fed_dates(html)], ['2026-10-28', '2026-12-09'])
