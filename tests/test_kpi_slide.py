import unittest

import pandas as pd

from tools.kpi_slide import (
    build_kpi_panel_chart,
    build_kpi_slide,
    build_presentation_timeline,
    build_presentation_trend,
)


class KpiSlideTests(unittest.TestCase):
    def test_builds_a_copy_ready_four_panel_slide_with_target_lines_and_gaps(self):
        trend = pd.DataFrame(
            {
                "Period": ["WK38", "WK39", "22-Sep"],
                "Rate": [0.9966, None, 1.0],
                "PPM": [2100, 0, 2500],
            }
        )
        panels = [
            {
                "title": "Functional Pass Rate",
                "frame": trend,
                "x_column": "Period",
                "y_column": "Rate",
                "value_type": "percent",
                "target": 0.9966,
                "exceptions": trend.iloc[[1]],
            },
            {
                "title": "SMT Process NG Rate (PPM)",
                "frame": trend,
                "x_column": "Period",
                "y_column": "PPM",
                "value_type": "ppm",
                "target": 5000,
            },
            {
                "title": "Assembly SMT Process Duty NG Rate (PPM)",
                "frame": trend,
                "x_column": "Period",
                "y_column": "PPM",
                "value_type": "ppm",
                "target": 700,
            },
            {
                "title": "SMT OQC Pass Rate",
                "frame": trend,
                "x_column": "Period",
                "y_column": "Rate",
                "value_type": "percent",
                "target": 0.985,
            },
        ]

        figure = build_kpi_slide("WK38 & WK39 · 14 Sep – 25 Sep 2026", panels)

        self.assertEqual(figure.layout.width, 1600)
        self.assertEqual(figure.layout.height, 900)
        self.assertEqual(len(figure.layout.shapes), 4)
        self.assertEqual(sum(trace.mode == "lines+markers+text" for trace in figure.data), 4)
        self.assertEqual(sum(trace.marker.symbol == "x" for trace in figure.data if trace.mode == "markers"), 1)
        self.assertIn(None, list(figure.data[0].y))
        annotation_texts = [str(annotation.text) for annotation in figure.layout.annotations]
        self.assertFalse(any("Quality – SMT" in text for text in annotation_texts))
        self.assertNotIn("<b>JOVI</b>", annotation_texts)

    def test_presentation_timeline_has_weekly_totals_then_only_input_days_of_latest_week(self):
        dates = pd.to_datetime(
            ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]
        )
        source = pd.DataFrame(
            {
                "PeriodDate": dates,
                "Input": [100] * len(dates),
                "FunctionalDefectPCBs": [1, 0, 1, 0, 0, 2, 0, 0, 1, 0],
            }
        )

        timeline = build_presentation_timeline(
            source,
            date_column="PeriodDate",
            input_column="Input",
        )
        trend = build_presentation_trend(
            source,
            timeline,
            date_column="PeriodDate",
            denominator_column="Input",
            numerator_column="FunctionalDefectPCBs",
            calculation="pass_minus",
        )

        self.assertEqual(
            list(timeline["Period"]),
            ["WK38", "WK39", "21-Sep", "22-Sep", "23-Sep", "24-Sep", "25-Sep"],
        )
        self.assertAlmostEqual(trend.loc[0, "Value"], 0.996)
        self.assertAlmostEqual(trend.loc[1, "Value"], 0.994)
        self.assertFalse(trend["IsException"].any())

    def test_individual_chart_keeps_a_full_pass_rate_inside_the_plot(self):
        frame = pd.DataFrame(
            {
                "Period": ["WK38", "WK39", "21-Sep", "22-Sep", "23-Sep", "24-Sep", "25-Sep"],
                "Value": [0.9973, 0.9758, 0.9824, 0.9130, 1.0, 1.0, 1.0],
            }
        )

        figure = build_kpi_panel_chart(
            {
                "title": "Functional Pass Rate",
                "frame": frame,
                "x_column": "Period",
                "y_column": "Value",
                "value_type": "percent",
                "target": 0.9966,
            }
        )

        self.assertEqual(figure.layout.width, 1920)
        self.assertEqual(figure.layout.height, 1080)
        self.assertEqual(len(figure.layout.shapes), 1)
        self.assertGreaterEqual(figure.layout.yaxis.range[1], 1.008)
        self.assertTrue(figure.data[0].cliponaxis)
        self.assertEqual(
            list(figure.data[0].textposition),
            ["top center", "bottom center", "top center", "bottom center", "top center", "bottom center", "top center"],
        )


if __name__ == "__main__":
    unittest.main()
