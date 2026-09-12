import unittest
from pathlib import Path
from sessiongraph.parsers import parse_generic
from sessiongraph.analyze import analyze
from sessiongraph.report import mermaid


class ProvenanceGraphTests(unittest.TestCase):
    def test_explicit_roots_and_merge_preserved(self):
        result = analyze(parse_generic([
            {'id': 'user', 'parent_id': None}, {'id': 'system', 'parent_ids': []},
            {'id': 'request', 'parent_id': 'user', 'parent_ids': ['user', 'system']},
        ], Path('fixture.jsonl')))
        self.assertEqual(result['graph']['edges'], [
            {'from': 'user', 'to': 'request', 'relation': 'precedes'},
            {'from': 'system', 'to': 'request', 'relation': 'precedes'},
        ])
        self.assertEqual(result['metrics']['merge_events'], 1)
        self.assertEqual(result['metrics']['edges'], 2)

    def test_omitted_parent_keeps_legacy_sequence(self):
        result = analyze(parse_generic([{'id': 'a'}, {'id': 'b'}], Path('fixture')))
        self.assertEqual(result['graph']['edges'], [{'from': 'a', 'to': 'b', 'relation': 'precedes'}])

    def test_missing_secondary_parent_is_visible(self):
        result = analyze(parse_generic([{'id': 'a', 'parent_ids': []},
            {'id': 'b', 'parent_ids': ['a', 'missing']}], Path('fixture')))
        self.assertIn('dangling_edges', {f['code'] for f in result['findings']})
        self.assertIn({'from': 'missing', 'to': 'b', 'relation': 'precedes'}, result['graph']['edges'])

    def test_malformed_lineage_fails_closed(self):
        for row in ({'parent_ids': 'a'}, {'parent_ids': ['a', 'a']}, {'parent_ids': [None]},
                    {'parent_ids': ['a'], 'parent_id': 'b'}, {'parent_ids': [], 'parent_id': 'a'}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                parse_generic([{'id': 'x', **row}], Path('fixture'))

    def test_parent_relations_are_validated_and_exported(self):
        result = analyze(parse_generic([
            {'id': 'request', 'kind': 'user_request', 'parent_ids': []},
            {'id': 'run', 'parent_ids': ['request'],
             'parent_relations': {'request': 'requested'}},
        ], Path('fixture')))
        self.assertEqual(result['graph']['edges'], [
            {'from': 'request', 'to': 'run', 'relation': 'requested'},
        ])
        self.assertIn('-->|"requested"|', mermaid(result))
        for relations in ('bad', {'missing': 'requested'}, {'request': ''}):
            with self.subTest(relations=relations), self.assertRaises(ValueError):
                parse_generic([
                    {'id': 'request', 'parent_ids': []},
                    {'id': 'run', 'parent_ids': ['request'], 'parent_relations': relations},
                ], Path('fixture'))
