from krkn_ai.algorithm.recommender import ScenarioRecommender

def test_basic():
    rec = ScenarioRecommender('fake')
    rec._q = lambda x: 0.8
    results = rec.recommend('15m', 2)
    assert len(results) <= 2
