import unittest

import pandas as pd

from tools.dashboard_charts import pareto_chart


class ParetoChartTests(unittest.TestCase):
    def test_long_labels_remain_distinct_and_cumulative_line_only_increases(self):
        frame = pd.DataFrame(
            {
                "Phenomenon": [
                    "BlockMicSelfTest_Different_Reason_A",
                    "BlockMicSelfTest_Different_Reason_B",
                    "Initial_UpperCapacity_Failure",
                ],
                "NGPCBs": [7, 6, 27],
            }
        )

        figure = pareto_chart(frame, "Phenomenon", "NGPCBs", "Pareto", "#0D7A45")
        bars, cumulative = figure.data

        self.assertEqual(len(set(bars.x)), 3)
        self.assertEqual(list(cumulative.y), sorted(cumulative.y))
        self.assertTrue(all(label.startswith("BlockMicSelfTest_") for label in list(bars.x)[1:3]))


if __name__ == "__main__":
    unittest.main()
