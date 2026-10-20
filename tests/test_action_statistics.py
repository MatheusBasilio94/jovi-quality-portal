from datetime import date, timedelta
import unittest

from tools.action_statistics import action_timeline, count_chart, timeline_chart


def action(created='2026-10-01T10:00:00+00:00', status='Open', closed=None, area='SMT'):
    return dict(created_at=created,status=status,closed_at=closed,area=area)


class StatisticsTests(unittest.TestCase):
    def test_counts_follow_selected_actions_and_preserve_zero_statuses(self):
        rows=[action(),action(status='In progress',area='Assembly'),action(status='Closed',closed='2026-10-02T10:00:00+00:00')]
        status=count_chart(rows,'status')
        self.assertEqual(list(status.data[0].y),[1,1,0,1,0])
        self.assertEqual(list(status.data[0].customdata),['Open','In progress','Pending verification','Closed','Notification'])
        area=count_chart(rows,'area')
        self.assertEqual(list(area.data[0].y),[2,1])
        self.assertEqual(list(area.data[0].customdata),['SMT','Assembly'])
        self.assertGreaterEqual(status.layout.yaxis.dtick,1)
        self.assertEqual(status.layout.yaxis.dtick,int(status.layout.yaxis.dtick))

    def test_daily_dates_and_closures_use_manaus_time_and_current_status(self):
        rows=[action('2026-10-01T02:00:00+00:00',status='Closed',closed='2026-10-02T02:00:00+00:00'),
              action('2026-10-01T10:00:00+00:00'),
              action('2026-10-02T10:00:00+00:00',status='Open',closed='2026-10-03T10:00:00+00:00')]
        frame,grain=action_timeline(rows)
        self.assertEqual(grain,'Daily')
        self.assertEqual(frame['Period'].tolist(),['30/09/26','01/10/26','02/10/26'])
        self.assertEqual(frame['Created'].tolist(),[1,1,1])
        self.assertEqual(frame['Closed'].tolist(),[0,1,0])
        chart=timeline_chart(rows)
        self.assertEqual(sum(chart.data[0].y),3)
        self.assertEqual(sum(chart.data[1].y),1)

    def test_long_history_grouping_preserves_counts_and_order(self):
        for span,grain in [(30,'Daily'),(31,'Weekly'),(179,'Weekly'),(180,'Monthly')]:
            with self.subTest(span=span):
                start=date(2026,1,1)
                end=start+timedelta(days=span)
                rows=[action(f'{start}T12:00:00+00:00'),
                      action(f'{end}T12:00:00+00:00',status='Closed',closed=f'{end}T12:00:00+00:00')]
                frame,actual=action_timeline(rows)
                self.assertEqual(actual,grain)
                self.assertEqual(frame['Created'].sum(),2)
                self.assertEqual(frame['Closed'].sum(),1)
                self.assertEqual(len(set(frame['Period'])),len(frame))
                if grain=='Weekly': self.assertEqual(frame.iloc[0]['Period'],'01/01/26')

    def test_empty_history_is_safe(self):
        frame,grain=action_timeline([])
        self.assertTrue(frame.empty)
        self.assertEqual(grain,'Daily')
        self.assertEqual(list(timeline_chart([]).data[0].y),[])

    def test_notifications_have_separate_period_counts_and_status_color(self):
        rows = [action(), action(status='Notification'), action('2026-11-02T10:00:00+00:00', status='Notification')]
        frame, grain = action_timeline(rows)
        self.assertEqual((frame['Created'].sum(), frame['Notifications'].sum()), (1, 2))
        chart = timeline_chart(rows)
        self.assertEqual([(trace.name, sum(trace.y)) for trace in chart.data], [('Created', 1), ('Closed', 0), ('Notifications', 2)])
        status = count_chart(rows, 'status')
        self.assertEqual(status.data[0].y[-1], 2)
        self.assertEqual(len(status.data[0].marker.color), 5)


if __name__=='__main__': unittest.main()
