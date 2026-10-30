import copy
import unittest
import history

def snapshot(value,date='2026-01-01',generated='before'):
    panel={'id':'p','title':'Panel','series':[{'name':'s','asof':date,'lastRaw':value,'data':[{'time':date,'value':value}]}]}
    return {'generated':generated,'columns':[{'panels':[panel]}],'markets':{'columns':[]}}

class HistoryTests(unittest.TestCase):
    def test_new_observation(self):
        result=history.snapshot_change(snapshot(1),snapshot(2,'2026-02-01','after'))
        self.assertEqual(result['rows'][0]['kind'],'Новое наблюдение')
        self.assertEqual(result['rows'][0]['delta'],1)
    def test_same_date_revision(self):
        result=history.snapshot_change(snapshot(1),snapshot(2))
        self.assertEqual(result['rows'][0]['kind'],'Пересчёт / уточнение')
        self.assertEqual(result['rows'][0]['revisions'],1)
    def test_offline_rebuild_keeps_last_meaningful_changes(self):
        previous=snapshot(2)
        previous['changes']={'previous':'a','current':'b','rows':[{'kind':'Новое наблюдение'}]}
        result=history.snapshot_change(previous,snapshot(2))
        self.assertEqual(result,previous['changes'])
    def test_missing_data_is_reported(self):
        current=snapshot(None)
        current['columns'][0]['panels'][0]['series'][0]['data']=[]
        result=history.snapshot_change(snapshot(1),current)
        self.assertEqual(result['rows'][0]['kind'],'Данные недоступны')
    def test_new_row_and_no_mutation(self):
        current=snapshot(1);original=copy.deepcopy(current)
        result=history.snapshot_change(None,current)
        self.assertEqual(result['rows'][0]['kind'],'Добавлен ряд')
        self.assertEqual(current,original)

if __name__=='__main__':unittest.main()
