"""
Regression: embedding input must be exactly the raw (normalized) user text.
No topic_label, canonical_claim, or stance_hint prefixing.
"""
import uuid
from unittest.mock import patch, MagicMock
import unittest

from app.services.utils import normalize_insight_text
from app.services.topic_layer import ingest_idea


class TestEmbeddingRawText(unittest.TestCase):
    def test_embedding_input_is_raw_text_only(self):
        raw = "Winters are cozy."
        normalized = normalize_insight_text(raw)
        with patch("app.services.topic_layer.embed_text") as mock_embed, patch(
            "app.services.topic_layer._classify_topic_hierarchy"
        ) as _mock_hierarchy, patch("app.services.topic_layer._upsert_topic_level") as _mock_upsert, patch(
            "app.services.topic_layer._assign_stance"
        ) as _mock_assign_stance, patch("app.services.topic_layer._update_stance_centroid"), patch(
            "app.services.topic_layer._nearest_ideas_with_filters", return_value=[]
        ), patch("app.services.topic_layer._upsert_similarity_edges"):
            mock_embed.return_value = [0.1] * 1536
            _mock_hierarchy.return_value = {"level1": "Weather & Environment", "level2": "Seasons", "level3": "Winter Experience"}
            parent = MagicMock()
            parent.id = uuid.uuid4()
            parent.name = "Weather & Environment"
            child2 = MagicMock()
            child2.id = uuid.uuid4()
            child2.name = "Seasons"
            child2.parent_topic_id = parent.id
            child3 = MagicMock()
            child3.id = uuid.uuid4()
            child3.name = "Winter Experience"
            child3.parent_topic_id = child2.id
            _mock_upsert.side_effect = [parent, child2, child3]
            _mock_assign_stance.return_value = ("neutral", 0.0)

            db = MagicMock()
            db.execute.return_value.scalar_one_or_none.return_value = None

            ingest_idea(db, raw)

            mock_embed.assert_called_once()
            call_arg = mock_embed.call_args[0][0]
            self.assertEqual(call_arg, normalized, "embedding must be computed on exact normalized raw text")
            self.assertNotIn("topic_label", call_arg)
            self.assertNotIn("canonical_claim", call_arg)
            _mock_hierarchy.assert_called_once()
            args, kwargs = _mock_hierarchy.call_args
            self.assertEqual(args[0], normalized)
            self.assertEqual(kwargs.get("topic_label", ""), "")
            self.assertEqual(kwargs.get("canonical_claim", ""), "")
