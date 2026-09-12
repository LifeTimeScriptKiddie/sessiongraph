import unittest
from pathlib import Path

from sessiongraph.analyze import analyze
from sessiongraph.parsers import parse_agentctl_loop
from sessiongraph.scorecard import evaluate_scorecard
from sessiongraph.suggest import select_findings, map_topology, render_agentctl


def analysis(rows):
    return analyze(parse_agentctl_loop(rows, Path('fixture/trace.jsonl')))


def event(name, **fields):
    return {'event': name, 'iteration': 1, **fields}


class AgentctlEvidenceTests(unittest.TestCase):
    def test_suggestions_preserve_capture_findings(self):
        for rows, code in (([event('generate', ok=True)], 'loop_incomplete'),
                           ([event('evaluate', ok=False), event('finish', status='stopped')], 'loop_telemetry_gap')):
            result = analysis(rows)
            plan = map_topology(select_findings(result['findings']))
            self.assertIn(code, plan['findings_used'])
            task, config, _ = render_agentctl(plan, task='repair capture', analysis=result)
            self.assertIn(code, task)
            self.assertIn('## Capture coverage', config)
            self.assertIn('Newly exposed failures may lower health', task)

    def test_missing_failure_class_is_unknown_not_timeout(self):
        result = analysis([event('evaluate', ok=False, durationMs=300000), event('finish', status='stopped')])
        codes = {f['code'] for f in result['findings']}
        self.assertIn('loop_telemetry_gap', codes)
        self.assertNotIn('agent_timeout', codes)
        self.assertEqual(result['metrics']['loop_failure_classification_missing'], 1)

    def test_explicit_timeout_for_either_role(self):
        for role in ('generate', 'evaluate'):
            with self.subTest(role=role):
                result = analysis([event(role, ok=False, failureClass='timeout'), event('finish', status='stopped')])
                self.assertIn('agent_timeout', {f['code'] for f in result['findings']})
                self.assertEqual(result['metrics']['loop_failure_classification_missing'], 0)

    def test_rejection_and_success_are_not_transport_failures(self):
        for status in ('passed', 'stopped', 'paused'):
            result = analysis([event('evaluate', ok=True), event('finish', status=status)])
            self.assertTrue(result['metrics']['loop_terminal_recorded'])
            self.assertFalse({'loop_telemetry_gap', 'agent_timeout', 'loop_incomplete'} & {f['code'] for f in result['findings']})

    def test_truncated_and_resumed_traces(self):
        for rows in ([event('generate', ok=True)],
                     [event('finish', status='passed'), event('generate', ok=True)],
                     [event('finish', status='running')]):
            result = analysis(rows)
            self.assertFalse(result['metrics']['loop_terminal_recorded'])
            self.assertIn('loop_incomplete', {f['code'] for f in result['findings']})

    def test_unclassified_variants(self):
        for value in (None, '', 'none', 'unknown', ' ', 42, False):
            result = analysis([event('evaluate', ok=False, failureClass=value), event('finish', status='failed')])
            self.assertEqual(result['metrics']['loop_failure_classification_missing'], 1)

    def test_scorecard_rejects_apparent_improvement_from_truncation(self):
        before = analysis([event('generate', ok=False, failureClass='timeout'), event('finish', status='stopped')])
        after = analysis([event('generate', ok=True)])
        scorecard = evaluate_scorecard(before, after)
        self.assertGreater(scorecard['compare']['delta']['workflow_health'], 0)
        self.assertFalse(scorecard['ok'])
        self.assertFalse(next(g['ok'] for g in scorecard['gates'] if g['id'] == 'agentctl_evidence_available'))

    def test_scorecard_accepts_recorded_recovery_and_rejects_legacy_or_gap(self):
        before = analysis([event('generate', ok=False, failureClass='timeout'), event('finish', status='stopped')])
        after = analysis([event('generate', ok=True), event('finish', status='passed')])
        self.assertTrue(evaluate_scorecard(before, after)['ok'])
        before['metrics'].pop('loop_terminal_recorded')
        self.assertFalse(evaluate_scorecard(before, after)['ok'])
        gap = analysis([event('evaluate', ok=False), event('finish', status='stopped')])
        self.assertFalse(evaluate_scorecard(gap, after)['ok'])
