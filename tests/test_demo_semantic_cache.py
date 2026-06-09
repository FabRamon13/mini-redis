import unittest

from benchmarks.demo_semantic_cache import build_workload
from benchmarks.demo_semantic_cache import percentile
from benchmarks.demo_semantic_cache import result_record


class SemanticCacheDemoTests(unittest.TestCase):
    def test_workload_has_expected_phases_and_size(self):
        sequential, burst = build_workload()

        phase_counts = {}
        for case in sequential + burst:
            phase_counts[case.phase] = phase_counts.get(case.phase, 0) + 1

        self.assertEqual(len(sequential), 40)
        self.assertEqual(len(burst), 6)
        self.assertEqual(
            phase_counts,
            {
                "cold_seed": 6,
                "semantic": 18,
                "exact_repeat": 12,
                "negative_control": 4,
                "queue_burst": 6,
            },
        )

    def test_cold_seeds_run_before_semantic_cases(self):
        sequential, _ = build_workload()

        self.assertTrue(all(case.phase == "cold_seed" for case in sequential[:6]))
        self.assertTrue(all(case.phase == "semantic" for case in sequential[6:24]))

    def test_result_record_marks_expected_outcome(self):
        sequential, _ = build_workload()
        case = sequential[6]
        job = {
            "status": "completed",
            "result": {
                "cache": "hit",
                "matched_prompt": "what is redis",
                "similarity_score": 0.92,
            },
        }

        record = result_record(case, job, 12.5)

        self.assertTrue(record["correct"])
        self.assertEqual(record["matched_prompt"], "what is redis")
        self.assertEqual(record["similarity_score"], 0.92)

    def test_percentile_interpolates_values(self):
        self.assertEqual(percentile([10, 20, 30], 0.5), 20)
        self.assertEqual(percentile([], 0.95), 0.0)


if __name__ == "__main__":
    unittest.main()
