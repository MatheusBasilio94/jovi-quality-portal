"""Weekly review date selection must always use Monday through Sunday."""
import ast
from datetime import date, timedelta
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


def review_app():
    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    names = {"weekly_kpi_week_label", "weekly_kpi_review_page"}
    functions = "\n\n".join(
        ast.unparse(node) for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    )
    setup = '''
import streamlit as st
from datetime import date, datetime as RealDatetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

class datetime:
    @staticmethod
    def now(zone):
        st.session_state["today_zone"] = str(zone)
        return RealDatetime(2026, 11, 23, 8, tzinfo=zone)

def kpi_review_glue_controls(start, end, key):
    st.session_state["glue_bounds"] = (start, end)
    return "Compare scenarios", {"Operation": ["Glue"]}

def weekly_kpi_review_data(start, end, **kwargs):
    st.session_state["requested_periods"].append((start, end))
    return {}, {}, {}, {}, {}

def kpi_review_table(directory, summaries, daily, days, exceptions):
    st.session_state["table_days"] = days
    st.session_state["week_labels"] = [summary[0] for summary in summaries]

def kpi_review_glue_comparison(*args):
    st.session_state["comparison_days"] = args[5]

configured_kpi_directory = lambda: ()
kpi_review_glue_directory = lambda directory, excluded: directory
is_admin = lambda: False
smart_report_kpi_candidates = lambda *args, **kwargs: {}
st.session_state["requested_periods"] = []
'''
    return AppTest.from_string(setup + functions + "\nweekly_kpi_review_page()")


class WeeklyKPIWeekBoundsTests(unittest.TestCase):
    def assert_week(self, app, selected):
        self.assertFalse(app.exception)
        monday = selected - timedelta(days=selected.weekday())
        sunday = monday + timedelta(days=6)
        days = [monday + timedelta(days=offset) for offset in range(7)]
        self.assertEqual(app.session_state["weekly_kpi_week_end"], sunday)
        self.assertEqual(app.selectbox(key="weekly_kpi_year").value, sunday.isocalendar().year)
        self.assertEqual(app.selectbox(key=f"weekly_kpi_week_{sunday.isocalendar().year}").value, sunday)
        self.assertEqual(len(app.date_input), 0)
        self.assertEqual(app.session_state["table_days"], days)
        self.assertEqual(app.session_state["comparison_days"], days)
        self.assertEqual(app.session_state["requested_periods"], [
            (monday, sunday),
            (monday - timedelta(days=7), sunday - timedelta(days=7)),
            (monday, sunday),
            (monday - timedelta(days=7), sunday - timedelta(days=7)),
        ])
        self.assertEqual(app.session_state["glue_bounds"], (monday - timedelta(days=7), sunday))
        self.assertEqual(app.session_state["week_labels"], [
            f"WK{(sunday - timedelta(days=7)).isocalendar().week:02d}",
            f"WK{sunday.isocalendar().week:02d}",
        ])

    def test_default_is_last_completed_week_in_manaus(self):
        app = review_app().run()
        self.assert_week(app, date(2026, 11, 22))
        self.assertEqual(app.session_state["today_zone"], "America/Manaus")

    def test_every_saved_weekday_is_normalized_before_the_widget(self):
        for offset in range(7):
            selected = date(2026, 11, 16) + timedelta(days=offset)
            with self.subTest(selected=selected):
                app = review_app()
                app.session_state["weekly_kpi_week_end"] = selected
                self.assert_week(app.run(), selected)

    def test_week_selection_handles_month_year_and_leap_day_boundaries(self):
        app = review_app().run()
        for selected in [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 29),
                         date(2026, 12, 31), date(2027, 1, 1), date(2028, 2, 29)]:
            with self.subTest(selected=selected):
                year = selected.isocalendar().year
                if app.selectbox(key="weekly_kpi_year").value != year:
                    app.selectbox(key="weekly_kpi_year").set_value(year).run()
                sunday = selected + timedelta(days=6 - selected.weekday())
                app.selectbox(key=f"weekly_kpi_week_{year}").set_value(sunday).run()
                self.assert_week(app, selected)
                self.assert_week(app.run(), selected)

    def test_hiding_a_day_changes_only_visible_columns(self):
        app = review_app().run()
        monday, sunday = date(2026, 11, 16), date(2026, 11, 22)
        app.multiselect(key="weekly_kpi_hidden_days_2026-11-22").set_value([monday]).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["table_days"][0], monday + timedelta(days=1))
        self.assertEqual(len(app.session_state["table_days"]), 6)
        self.assertEqual(app.session_state["requested_periods"][0], (monday, sunday))
        self.assertEqual(app.session_state["comparison_days"], app.session_state["table_days"])

    def test_years_offer_only_valid_iso_weeks_with_their_full_ranges(self):
        app = review_app().run()
        self.assertEqual(len(app.selectbox(key="weekly_kpi_week_2026").options), 53)
        self.assertIn("WK47 (16-Nov ~ 22-Nov)", app.selectbox(key="weekly_kpi_week_2026").options)
        self.assertEqual(app.selectbox(key="weekly_kpi_week_2026").options[-1], "WK53 (28-Dec ~ 03-Jan)")
        app.selectbox(key="weekly_kpi_week_2026").set_value(date(2027, 1, 3)).run()
        self.assert_week(app, date(2026, 12, 31))
        app.selectbox(key="weekly_kpi_year").set_value(2027).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.selectbox(key="weekly_kpi_week_2027").options), 52)
        self.assert_week(app, date(2027, 12, 27))
        app.selectbox(key="weekly_kpi_year").set_value(2026).run()
        self.assert_week(app, date(2026, 12, 31))

    def test_cleared_legacy_date_defaults_to_last_completed_week(self):
        app = review_app()
        app.session_state["weekly_kpi_week_end"] = None
        self.assert_week(app.run(), date(2026, 11, 22))


if __name__ == "__main__":
    unittest.main()
