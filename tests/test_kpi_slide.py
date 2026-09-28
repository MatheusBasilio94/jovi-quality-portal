import unittest

import pandas as pd

from tools.kpi_slide import build_kpi_slide


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
        self.assertTrue(any("Quality – SMT" in text for text in annotation_texts))
        self.assertIn("<b>JOVI</b>", annotation_texts)


if __name__ == "__main__":
    unittest.main()
