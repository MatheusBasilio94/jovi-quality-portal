import unittest

import pandas as pd

from tools.smart_report_rules import kpi_defect_scopes, top_issue_reasons


class SmartReportRuleTests(unittest.TestCase):
    def test_repair_remark_is_the_top_issue_reason_with_a_phenomenon_fallback(self):
        frame = pd.DataFrame(
            {
                "Phenomenon": ["Original phenomenon", "Fallback phenomenon", "Alternate fallback"],
                "RepaireRemark": ["Repaired root cause", "", None],
                "RepairRemark": ["Secondary remark", "", "Alternate repair cause"],
            }
        )

        self.assertEqual(
            top_issue_reasons(frame).tolist(),
            ["Repaired root cause", "Fallback phenomenon", "Alternate repair cause"],
        )

    def test_each_kpi_uses_only_its_own_detractor_scope(self):
        smt = pd.DataFrame(
            {
                "FailureType": ["Functional Failure", "Appearance Failure", "Unclassified"],
                "Phenomenon": ["Functional top", "Appearance top", "Ignored"],
            }
        )
        assembly = pd.DataFrame(
            {
                "FailureType": ["Funcional", "Aparência", "Funcional", "Fora do escopo"],
                "Phenomenon": ["Functional top", "Appearance top", "Mando top", "Ignored"],
                "IsFunctionMando": [False, False, True, False],
                "IsSMTDuty": [False, False, True, False],
            }
        )

        scopes = kpi_defect_scopes(smt, assembly)

        self.assertEqual(scopes["smt_function"]["Phenomenon"].tolist(), ["Functional top"])
        self.assertEqual(scopes["smt_process"]["Phenomenon"].tolist(), ["Functional top", "Appearance top"])
        self.assertEqual(scopes["assembly_function"]["Phenomenon"].tolist(), ["Functional top", "Mando top"])
        self.assertEqual(scopes["assembly_appearance"]["Phenomenon"].tolist(), ["Appearance top"])
        self.assertEqual(scopes["assembly_mando"]["Phenomenon"].tolist(), ["Mando top"])
        self.assertEqual(scopes["smt_assembly_duty"]["Phenomenon"].tolist(), ["Mando top"])


if __name__ == "__main__":
    unittest.main()
