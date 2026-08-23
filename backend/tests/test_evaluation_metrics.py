import math

import pytest

from evaluation.grading import knapsack_metrics


def test_metrics_match_an_independent_hand_calculation():
    # Grade 3 at rank 2, grade 2 at rank 3, then irrelevant results.
    metrics = knapsack_metrics([0, 3, 2, 0], k=10)

    expected_dcg = 7 / math.log2(3) + 3 / math.log2(4)
    expected_idcg = 7 + 3 / math.log2(3)
    assert metrics["p5"] == pytest.approx(0.4)
    assert metrics["p10"] == pytest.approx(0.2)
    assert metrics["mrr"] == pytest.approx(0.5)
    assert metrics["ndcg"] == pytest.approx(expected_dcg / expected_idcg)


def test_rank_one_relevant_result_has_mrr_one_not_one_half():
    assert knapsack_metrics([3, 0, 0])["mrr"] == 1.0


def test_unjudged_results_are_excluded_and_zero_relevance_is_safe():
    assert knapsack_metrics([None, 0, 0])["mrr"] == 0.0
    assert knapsack_metrics([None, None])["p5"] is None
