"""
Unit tests for backend.observability.greenops.
Covers: CarbonTracker estimation logic, CarbonAwareScheduler queue processing.
No network calls — API fetching is bypassed or mocked.
"""
import asyncio
import time

import pytest

from backend.observability.greenops import (
    CARBON_THRESHOLD_GCO2_KWH,
    CPU_ACTIVE_WATTS,
    GPU_INFERENCE_WATTS,
    CarbonAwareScheduler,
    CarbonTracker,
    ScheduledTask,
    TaskPriority,
    estimate_query_carbon,
)


# ── CarbonTracker ─────────────────────────────────────────────────────────────

class TestCarbonTrackerEstimate:
    def setup_method(self):
        self.tracker = CarbonTracker()
        self.tracker._grid_intensity = 400.0  # fixed intensity for determinism

    def test_zero_duration_emits_zero_carbon(self):
        assert self.tracker.estimate_carbon(0.0) == 0.0

    def test_carbon_proportional_to_duration(self):
        c1 = self.tracker.estimate_carbon(10.0)
        c2 = self.tracker.estimate_carbon(20.0)
        assert pytest.approx(c2, rel=1e-6) == c1 * 2

    def test_carbon_proportional_to_power(self):
        c_cpu = self.tracker.estimate_carbon(60.0, power_watts=CPU_ACTIVE_WATTS)
        c_gpu = self.tracker.estimate_carbon(60.0, power_watts=GPU_INFERENCE_WATTS)
        assert c_gpu > c_cpu

    def test_carbon_formula_correctness(self):
        # 65W * 3600s = 234000 J = 65 Wh = 0.065 kWh
        # 0.065 kWh * 400 gCO2/kWh = 26 gCO2
        result = self.tracker.estimate_carbon(3600.0, power_watts=65.0)
        assert pytest.approx(result, rel=1e-4) == 26.0

    def test_carbon_positive_for_nonzero_inputs(self):
        result = self.tracker.estimate_carbon(1.0, power_watts=10.0)
        assert result > 0.0


class TestCarbonTrackerIsLowCarbon:
    def test_below_threshold_is_low_carbon(self):
        tracker = CarbonTracker()
        tracker._grid_intensity = CARBON_THRESHOLD_GCO2_KWH - 1
        assert tracker.is_low_carbon is True

    def test_above_threshold_is_not_low_carbon(self):
        tracker = CarbonTracker()
        tracker._grid_intensity = CARBON_THRESHOLD_GCO2_KWH + 1
        assert tracker.is_low_carbon is False

    def test_exactly_at_threshold_is_not_low_carbon(self):
        tracker = CarbonTracker()
        tracker._grid_intensity = CARBON_THRESHOLD_GCO2_KWH
        assert tracker.is_low_carbon is False


class TestCarbonTrackerUpdateIntensity:
    @pytest.mark.asyncio
    async def test_caches_within_update_interval(self):
        tracker = CarbonTracker()
        tracker._grid_intensity = 123.0
        tracker._last_update = time.time()  # just updated
        result = await tracker.update_intensity()
        # Should return cached value without calling API
        assert result == 123.0

    @pytest.mark.asyncio
    async def test_uses_regional_estimate_without_api_key(self):
        """Without an API key, _fetch_from_api falls back to regional estimate."""
        tracker = CarbonTracker()
        tracker._last_update = 0  # force update
        import backend.observability.greenops as g
        original_key = g.ELECTRICITY_MAPS_API_KEY
        g.ELECTRICITY_MAPS_API_KEY = ""
        try:
            result = await tracker.update_intensity()
            assert 100 <= result <= 600  # within expected regional range
        finally:
            g.ELECTRICITY_MAPS_API_KEY = original_key

    @pytest.mark.asyncio
    async def test_falls_back_to_default_on_api_error(self, monkeypatch):
        tracker = CarbonTracker()
        tracker._last_update = 0

        async def fail_fetch():
            raise RuntimeError("API unavailable")

        monkeypatch.setattr(tracker, "_fetch_from_api", fail_fetch)
        result = await tracker.update_intensity()
        assert result > 0  # has a fallback value


class TestRegionalEstimate:
    def test_returns_positive_value(self):
        tracker = CarbonTracker()
        result = tracker._get_regional_estimate()
        assert result >= 100

    def test_result_within_expected_range(self):
        tracker = CarbonTracker()
        for _ in range(20):  # run multiple times due to random variation
            result = tracker._get_regional_estimate()
            assert 100 <= result <= 600


# ── CarbonAwareScheduler ──────────────────────────────────────────────────────

class TestSchedulerQueue:
    def setup_method(self):
        self.tracker = CarbonTracker()
        self.tracker._grid_intensity = 450.0  # high carbon (not low-carbon)
        self.scheduler = CarbonAwareScheduler(self.tracker)

    def test_schedule_adds_to_queue(self):
        task = ScheduledTask(
            name="test-task",
            priority=TaskPriority.NORMAL,
            task_fn=lambda: None,
        )
        self.scheduler.schedule(task)
        assert len(self.scheduler._queue) == 1

    def test_schedule_task_convenience_method(self):
        self.scheduler.schedule_task("quick-task", lambda: None)
        assert len(self.scheduler._queue) == 1

    def test_get_queue_status_structure(self):
        self.scheduler.schedule_task("t1", lambda: None)
        status = self.scheduler.get_queue_status()
        assert "queued_tasks" in status
        assert "grid_intensity_gco2_kwh" in status
        assert "is_low_carbon" in status
        assert "tasks" in status
        assert status["queued_tasks"] == 1


class TestSchedulerProcessQueue:
    def setup_method(self):
        self.tracker = CarbonTracker()
        self.scheduler = CarbonAwareScheduler(self.tracker)

    @pytest.mark.asyncio
    async def test_critical_task_runs_regardless_of_carbon(self):
        self.tracker._grid_intensity = 999.0  # very high carbon
        ran = []
        task = ScheduledTask(
            name="critical",
            priority=TaskPriority.CRITICAL,
            task_fn=lambda: ran.append(True),
        )
        self.scheduler.schedule(task)
        await self.scheduler._process_queue()
        assert ran == [True]
        assert len(self.scheduler._queue) == 0

    @pytest.mark.asyncio
    async def test_normal_task_deferred_when_high_carbon(self):
        self.tracker._grid_intensity = 999.0
        ran = []
        task = ScheduledTask(
            name="normal",
            priority=TaskPriority.NORMAL,
            task_fn=lambda: ran.append(True),
        )
        self.scheduler.schedule(task)
        await self.scheduler._process_queue()
        assert ran == []
        assert len(self.scheduler._queue) == 1

    @pytest.mark.asyncio
    async def test_normal_task_runs_in_low_carbon_window(self):
        self.tracker._grid_intensity = 50.0  # well below threshold
        ran = []
        task = ScheduledTask(
            name="normal",
            priority=TaskPriority.NORMAL,
            task_fn=lambda: ran.append(True),
        )
        self.scheduler.schedule(task)
        await self.scheduler._process_queue()
        assert ran == [True]

    @pytest.mark.asyncio
    async def test_expired_task_runs_regardless_of_carbon(self):
        self.tracker._grid_intensity = 999.0
        ran = []
        task = ScheduledTask(
            name="overdue",
            priority=TaskPriority.LOW,
            task_fn=lambda: ran.append(True),
            max_defer_hours=0.0001,  # expires almost immediately
        )
        task.created_at = time.time() - 3600  # 1 hour old
        self.scheduler.schedule(task)
        await self.scheduler._process_queue()
        assert ran == [True]

    @pytest.mark.asyncio
    async def test_async_task_is_awaited(self):
        self.tracker._grid_intensity = 50.0
        ran = []

        async def async_fn():
            ran.append(True)

        task = ScheduledTask(
            name="async-task",
            priority=TaskPriority.NORMAL,
            task_fn=async_fn,
        )
        self.scheduler.schedule(task)
        await self.scheduler._process_queue()
        assert ran == [True]

    @pytest.mark.asyncio
    async def test_failed_task_does_not_crash_scheduler(self):
        self.tracker._grid_intensity = 50.0

        def boom():
            raise RuntimeError("task failed")

        task = ScheduledTask(
            name="failing-task",
            priority=TaskPriority.CRITICAL,
            task_fn=boom,
        )
        self.scheduler.schedule(task)
        # Should not raise
        await self.scheduler._process_queue()


# ── estimate_query_carbon ─────────────────────────────────────────────────────

class TestEstimateQueryCarbon:
    def test_returns_positive_value(self):
        result = estimate_query_carbon(5.0, used_gpu=False)
        assert result > 0

    def test_gpu_higher_than_cpu(self):
        cpu = estimate_query_carbon(5.0, used_gpu=False)
        gpu = estimate_query_carbon(5.0, used_gpu=True)
        assert gpu > cpu

    def test_longer_duration_more_carbon(self):
        short = estimate_query_carbon(1.0, used_gpu=False)
        long_ = estimate_query_carbon(10.0, used_gpu=False)
        assert long_ > short
