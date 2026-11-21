import unittest
import datetime as dt
import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
import sources
import update_publish as U

class UpdatePublishTests(unittest.TestCase):
    def test_scheduled_fred_rows_do_not_enter_dashboard_before_their_date(self):
        today = dt.date.today()
        yesterday = (today - dt.timedelta(days=1)).isoformat()
        tomorrow = (today + dt.timedelta(days=1)).isoformat()
        observations = [
            {'date': yesterday, 'value': '3.9'},
            {'date': today.isoformat(), 'value': '3.8'},
            {'date': tomorrow, 'value': '3.7'},
        ]
        api = json.dumps({'observations': observations})
        csv = 'observation_date,IORB\n' + '\n'.join(
            row['date'] + ',' + row['value'] for row in observations
        )
        for response in (api, csv):
            with self.subTest(response=response):
                series = sources._parse_fred('IORB', response)
                self.assertEqual(series.index[-1].date(), today)
                self.assertEqual(series.tolist(), [3.9, 3.8])

    def test_failed_command_displays_stderr_and_reports_step(self):
        console = StringIO()
        with redirect_stdout(console), self.assertRaisesRegex(U.UpdateError, 'Аудит данных.*код 7'):
            U.command([sys.executable, '-c', "import sys; print('row IORB', file=sys.stderr); sys.exit(7)"],
                      step='Аудит данных')
        self.assertIn('row IORB', console.getvalue())

    def test_cache_fallback_stops_publication(self):
        for status,detail in [('cache','сеть упала, старый кэш n=10'),('skip','offline')]:
            with self.assertRaises(U.UpdateError):U.validate_fallbacks({'diagnostics':[{'name':'GDP','status':status,'detail':detail}]})
    def test_regular_cache_is_allowed(self):
        U.validate_fallbacks({'diagnostics':[{'name':'GDP','status':'cache','detail':'n=20'}]})
    def test_unrelated_staged_files_are_not_committed(self):
        def fake(*args,**kwargs):
            output='main\n' if args==('branch','--show-current') else 'src/config.py\n' if args==('diff','--cached','--name-only') else ''
            return SimpleNamespace(stdout=output,returncode=0)
        with patch.object(U,'git',side_effect=fake):
            with self.assertRaises(U.UpdateError):U.preflight()
    def test_wrong_branch_is_not_published(self):
        with patch.object(U,'git',return_value=SimpleNamespace(stdout='checkpoint/test',returncode=0)):
            with self.assertRaises(U.UpdateError):U.preflight()
    def test_build_failure_prevents_git_push(self):
        with patch.object(U,'preflight'),patch.object(U,'prepare',side_effect=U.UpdateError('build failed')),patch.object(U,'publish') as publish:
            self.assertEqual(U.main(['--no-open']),1)
            publish.assert_not_called()
    def test_prepare_only_never_touches_git(self):
        with patch.object(U,'preflight') as preflight,patch.object(U,'prepare') as prepare,patch.object(U,'publish') as publish:
            self.assertEqual(U.main(['--prepare-only','--offline']),0)
            prepare.assert_called_once_with(offline=True)
            preflight.assert_not_called();publish.assert_not_called()
    def test_publish_only_uses_allowlisted_paths(self):
        calls=[]
        def fake(*args,**kwargs):
            calls.append(args)
            return SimpleNamespace(stdout='',returncode=1 if args[:3]==('diff','--cached','--quiet') else 0)
        with patch.object(U,'preflight'),patch.object(U,'git',side_effect=fake):U.publish()
        self.assertIn(('add','--',*U.PUBLIC_FILES),calls)
        commit=next(args for args in calls if args[0]=='commit')
        self.assertIn('--only',commit)
        self.assertEqual(commit[-3:],U.PUBLIC_FILES)
        self.assertEqual(calls[-1],('push','origin','main'))
    def test_no_changes_do_not_make_an_empty_commit(self):
        with patch.object(U,'preflight'),patch.object(U,'git',return_value=SimpleNamespace(stdout='',returncode=0)) as git:
            U.publish()
        self.assertFalse(any(call.args[0]=='commit' for call in git.call_args_list))

if __name__=='__main__':unittest.main()
