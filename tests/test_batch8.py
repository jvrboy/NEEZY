"""Batch 8: reasoning, neuro v2, scheduler, queue, metrics, orchestrator, fusion."""

from __future__ import annotations

import unittest

from neezy_backend.config import AppSettings
from neezy_backend.job_queue import JobQueue
from neezy_backend.metrics_tracing import MetricsStore
from neezy_backend.neural_v2 import ARCH_V2, V2_INFO, train_v2
from neezy_backend.neuro_search import neuro_evolution_search
from neezy_backend.orchestrator import Orchestrator, Task
from neezy_backend.reasoning import ReasoningEngine
from neezy_backend.scheduler import Scheduler
from neezy_backend.signal_fusion import detect_anomalies, explain_score, fuse_signals


def _candles(n: int = 300) -> list[list[float]]:
    rows: list[list[float]] = []
    price = 100.0
    for i in range(n):
        price += 0.05
        open_ = price
        close = price + (0.3 if i % 2 == 0 else -0.3)
        high = max(open_, close) + 1
        low = min(open_, close) - 1
        rows.append([float(i), float(open_), float(high), float(low), float(close)])
    return rows


class ReasoningTests(unittest.TestCase):
    def test_cot_tot_react_reflection_debate(self):
        for strat in ("cot", "tot", "react", "reflection", "debate", "ensemble"):
            trace = ReasoningEngine(AppSettings(reasoning_strategy=strat)).think(
                "plan trade for EURUSD"
            )
            self.assertGreater(len(trace.steps), 0)
            self.assertTrue(trace.final_answer)
            self.assertGreater(trace.overall_confidence, 0)

    def test_reasoning_config_validation(self):
        s = AppSettings(
            reasoning_strategy="tot", thinking_mode="reflective", reasoning_depth=5
        )
        s.__post_init__()
        with self.assertRaises(ValueError):
            AppSettings(reasoning_strategy="nope").__post_init__()

    def test_quick_think_modes(self):
        eng = ReasoningEngine(AppSettings(thinking_mode="adversarial"))
        trace = eng.chain_of_thought("test", mode="adversarial")
        self.assertIn("adversarial", trace.mode)


class NeuralV2Tests(unittest.TestCase):
    def test_arch_v2_list(self):
        self.assertGreaterEqual(len(ARCH_V2), 5)
        for k in ARCH_V2:
            self.assertIn(k, V2_INFO)

    def test_train_v2_each(self):
        candles = _candles(400)
        for arch in ARCH_V2:
            out = train_v2(candles, architecture=arch)
            self.assertIn("model", out)
            self.assertEqual(out["model"]["model_type"], arch)

    def test_hyper_search(self):
        from neezy_backend.neural_v2 import hyper_search

        out = hyper_search(_candles(600), trials=3, seed=1)
        self.assertIn("model", out)
        self.assertIn("report", out)

    def test_neuro_evolution(self):
        res = neuro_evolution_search([], trials=5, seed=42)
        self.assertGreater(res.best_score, 0)
        self.assertEqual(res.trials, 5)
        self.assertTrue(res.best_arch)


class SchedulerQueueTests(unittest.TestCase):
    def test_scheduler_add_tick(self):
        s = Scheduler()
        s.register("demo", lambda: {"ok": True})
        job = s.add_job("demo", interval_seconds=10)
        self.assertTrue(job.id.startswith("job-"))
        fired = s.tick(now=job.next_run_at + 1)
        self.assertEqual(len(fired), 1)
        self.assertEqual(s.list_jobs()[0]["name"], "demo")

    def test_scheduler_policy_validation(self):
        s = Scheduler()
        with self.assertRaises(ValueError):
            s.add_job("x", policy="bad")

    def test_queue_enqueue_dequeue(self):
        q = JobQueue()
        j = q.enqueue("task-a", priority=1)
        self.assertEqual(q.size(), 1)
        out = q.dequeue()
        self.assertEqual(out.id, j.id)  # type: ignore[union-attr]
        q.enqueue("b", priority=5)
        q.enqueue("c", priority=2)
        self.assertEqual(q.drain(limit=2)[0].name, "c")  # priority 2 before 5

    def test_queue_retry_dead_letter(self):
        q = JobQueue(AppSettings(queue_retry_limit=1))
        j = q.enqueue("fail")
        q.dequeue()
        ok = q.requeue_failed(j)
        self.assertFalse(ok)
        self.assertEqual(len(q.dead_letter), 1)


class MetricsTracingTests(unittest.TestCase):
    def test_record_and_health(self):
        m = MetricsStore()
        m.record("latency", 10.0)
        m.record("latency", 20.0)
        summ = m.summary()
        self.assertIn("latency", summ)
        m.health_check("db", True)
        self.assertEqual(m.health()["status"], "ok")
        m.health_check("api", False)
        self.assertEqual(m.health()["status"], "degraded")

    def test_span(self):
        m = MetricsStore(AppSettings(tracing_enabled=True))
        sp = m.start_span("test-span")
        sp.finish()
        self.assertIsNotNone(sp.duration_ms)
        self.assertEqual(len(m.spans()), 1)


class OrchestratorTests(unittest.TestCase):
    def test_dag_execution(self):
        orch = Orchestrator(max_parallel=2)
        orch.add_task(Task(id="a", name="fetch"))
        orch.add_task(
            Task(id="b", name="analyse", depends_on=["a"], fn=lambda ctx: {"ok": 1})
        )
        orch.add_task(Task(id="c", name="report", depends_on=["b"]))
        res = orch.run({})
        self.assertEqual(len(res), 3)
        self.assertTrue(res["a"].ok)
        self.assertTrue(res["c"].ok)
        summ = orch.summary(res)
        self.assertEqual(summ["total"], 3)

    def test_cycle_detection(self):
        orch = Orchestrator()
        orch.add_task(Task(id="a", name="a", depends_on=["b"]))
        orch.add_task(Task(id="b", name="b", depends_on=["a"]))
        with self.assertRaises(ValueError):
            orch.topological_order()


class FusionTests(unittest.TestCase):
    def test_fuse_and_anomaly(self):
        demo = [
            {"source": "trend", "score": 1.0, "confidence": 0.8},
            {"source": "mom", "score": -0.5, "confidence": 0.6},
        ]
        fused = fuse_signals(demo)
        self.assertGreater(fused["confidence"], 0)
        expl = explain_score({"trend": 1.0, "mom": -0.5})
        self.assertEqual(expl["top_driver"], "trend")
        anoms = detect_anomalies([1, 1, 1, 10, 1], z_threshold=1.5)
        self.assertIn(3, anoms)
