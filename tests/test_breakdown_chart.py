import unittest

import pandas as pd

from tools.breakdown_chart import build_breakdown_chart, category_counts


class BreakdownChartTests(unittest.TestCase):
    def test_counts_unique_boards_and_uses_other_card_filters(self):
        data = pd.DataFrame({
            "_DefectKey": ["A", "A", "B", "C", "A"],
            "FaultReason": ["Download", "Download", "Solder", "Download", "Solder"],
            "Model": ["M1", "M1", "M1", "M2", "M1"],
        })
        counts = category_counts(data, "FaultReason", {"Model": "M1", "FaultReason": "Download"})
        self.assertEqual(counts.to_dict(), {"Solder": 2, "Download": 1})
        figure = build_breakdown_chart(counts.drop(index="Download"), "My title", show_values=False)
        self.assertEqual(list(figure.data[0].y), [2])
        self.assertIsNone(figure.data[0].text)
        self.assertEqual(figure.layout.title.text, "My title")
        self.assertEqual(figure.layout.meta["jovi_report_export"], "breakdown")

    def test_preserves_full_category_in_hover_and_shortens_axis_label(self):
        category = "A very long repair remark " * 4
        figure = build_breakdown_chart(pd.Series([7], index=[category]), "Issues")
        self.assertEqual(figure.data[0].customdata[0], category)
        self.assertLess(len(figure.layout.xaxis.ticktext[0]), len(category))
        self.assertGreater(figure.layout.yaxis.range[1], 7)


if __name__ == "__main__":
    unittest.main()
