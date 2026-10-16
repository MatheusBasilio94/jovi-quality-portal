from datetime import date, datetime
import unittest

import pandas as pd

from tools.br_datetime import br_date, br_datetime, br_frame


class BrazilianDateTests(unittest.TestCase):
    def test_iso_utc_example_and_midnight_conversion(self):
        self.assertEqual(br_datetime('2026-10-15T19:53:03.965896+00:00'), '15/10/26 15:53')
        self.assertEqual(br_datetime('2026-10-16T01:15:59Z'), '15/10/26 21:15')
        self.assertEqual(br_date('2026-10-15'), '15/10/26')

    def test_naive_mes_times_are_preserved_and_br_is_day_first(self):
        self.assertEqual(br_datetime(datetime(2026, 7, 6, 9, 5, 59)), '06/07/26 09:05')
        self.assertEqual(br_date('06/07/26'), '06/07/26')
        self.assertEqual(br_date('07/06/2026', dayfirst=False), '06/07/26')
        self.assertEqual(br_date(None), '—')
        self.assertEqual(br_datetime(pd.NaT), '—')

    def test_display_and_csv_do_not_modify_keys_order_or_calculation_types(self):
        source = pd.DataFrame({'PCB': ['20261015', '01/02/26'], 'Model':['A','B'],
            'Created':['2026-10-15T19:53:03+00:00', None],
            'Due date':['2026-10-16','2026-10-20'],
            'RepairDate':[pd.Timestamp('2026-10-15 12:35:45'), pd.NaT],
            'Date':[date(2026,10,15), date(2026,10,16)], 'Elapsed (h)':[1.5, 0.0], 'Closed':[1,0]})
        original = source.copy(deep=True)
        display = br_frame(source)
        self.assertEqual(display.loc[0, 'Created'], '15/10/26 15:53')
        self.assertEqual(display.loc[0, 'Due date'], '16/10/26')
        self.assertEqual(display.loc[0, 'RepairDate'], '15/10/26 12:35')
        self.assertEqual(display['PCB'].tolist(), original['PCB'].tolist())
        self.assertEqual(display['Elapsed (h)'].tolist(), [1.5, 0.0])
        self.assertEqual(display['Closed'].tolist(), [1,0])
        self.assertIn('15/10/26 15:53', display.to_csv(index=False))
        pd.testing.assert_frame_equal(source, original)

    def test_list_records_and_styled_tables_keep_other_values(self):
        records = [{'Date':'2026-10-15', 'Score':3}]
        self.assertEqual(br_frame(records).iloc[0]['Date'], '15/10/26')
        frame = pd.DataFrame({'Date': [pd.Timestamp('2026-10-15')], 'Gap':[2]})
        styled = frame.style.map(lambda value:'background-color:green', subset=['Gap'])
        rendered = br_frame(styled).to_html()
        self.assertIn('15/10/26', rendered)
        self.assertIn('background-color: green', rendered)
        self.assertEqual(frame.loc[0, 'Date'], pd.Timestamp('2026-10-15'))


if __name__=='__main__': unittest.main()
