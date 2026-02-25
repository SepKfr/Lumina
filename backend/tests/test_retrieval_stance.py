"""
Unit test: "Winters are cozy.", "I love winters.", "Winter makes me sad."
All share same level1/level2/level3 topic; supportive retrieval returns same-stance,
opposing retrieval returns opposite-stance.
"""
import uuid
from unittest.mock import patch, MagicMock
import unittest

from app.services.topic_layer import (
    _classify_topic_hierarchy,
    _cosine,
    retrieve_supportive,
    retrieve_opposing,
)
from app.services.utils import normalize_insight_text


class TestRetrievalStance(unittest.TestCase):
    def test_topic_hierarchy_same_topic_for_winter_sentences(self):
        """All three winter sentences should map to same level1/2/3 (no sentiment in topic names)."""
        with patch("app.services.topic_layer.chat_json") as mock_chat:
            mock_chat.return_value = {
                "level1": "Weather & Environment",
                "level2": "Seasons",
                "level3": "Winter Experience",
            }
            for text in ["Winters are cozy.", "I love winters.", "Winter makes me sad."]:
                out = _classify_topic_hierarchy(normalize_insight_text(text), "", "")
                self.assertEqual(out["level1"], "Weather & Environment")
                self.assertEqual(out["level2"], "Seasons")
                self.assertEqual(out["level3"], "Winter Experience")

    def test_supportive_filters_same_stance_opposing_filters_opposite_stance(self):
        """retrieve_supportive returns same stance_label; retrieve_opposing returns opposite."""
        db = MagicMock()
        seed = MagicMock()
        seed.id = uuid.uuid4()
        seed.subtopic_id = uuid.uuid4()
        seed.topic_id = uuid.uuid4()
        seed.stance_label = "pro"
        seed.embedding = [0.1] * 10

        # Supportive: same subtopic, same stance
        with patch("app.services.topic_layer._get_idea_or_none", return_value=seed), patch(
            "app.services.topic_layer._nearest_ideas_same_subtree"
        ) as mock_same:
            mock_same.return_value = [
                {"id": uuid.uuid4(), "text": "I love winters.", "stance_label": "pro", "similarity": 0.9},
            ]
            retrieve_supportive(db, seed.id, top_k=5)
            self.assertEqual(mock_same.call_count, 1)
            kwargs = mock_same.call_args[1]
            self.assertEqual(kwargs["stance_label"], "pro")
            self.assertEqual(kwargs["subtopic_id"], seed.subtopic_id)

        # Opposing: same subtopic, opposite stance
        with patch("app.services.topic_layer._get_idea_or_none", return_value=seed), patch(
            "app.services.topic_layer._nearest_ideas_same_subtree"
        ) as mock_opp:
            mock_opp.return_value = [
                {"id": uuid.uuid4(), "text": "Winter makes me sad.", "stance_label": "con", "similarity": 0.3, "embedding": [0.2] * 10},
            ]
            with patch("app.services.topic_layer._get_stance_centroid", return_value=[0.15] * 10):
                retrieve_opposing(db, seed.id, top_k=5)
            self.assertEqual(mock_opp.call_count, 1)
            kwargs = mock_opp.call_args[1]
            self.assertEqual(kwargs["stance_label"], "con")
            self.assertEqual(kwargs["subtopic_id"], seed.subtopic_id)

    def test_cosine_helper(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(_cosine(a, b), 1.0, places=5)
        c = [0.0, 1.0, 0.0]
        self.assertAlmostEqual(_cosine(a, c), 0.0, places=5)
