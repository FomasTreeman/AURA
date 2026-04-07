"""
GreenOps – Carbon-aware scheduling for AURA.

Features:
- Grid carbon intensity tracking (via electricityMaps API or fallback estimates)
- Carbon estimation for compute operations
- Task scheduler that defers heavy operations to low-carbon windows
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional, Any
import os
import json

from backend.observability.metrics import OBSERVABILITY_METRICS
from backend.utils.logging import get_logger

log = get_logger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

# Carbon intensity threshold in gCO2/kWh (below this is considered "low carbon")
CARBON_THRESHOLD_GCO2_KWH = float(os.getenv("CARBON_THRESHOLD_GCO2_KWH", "200"))

# Default grid intensity when API unavailable (US average ~400 gCO2/kWh)
DEFAULT_GRID_INTENSITY = float(os.getenv("DEFAULT_GRID_INTENSITY", "400"))

# Electricity Maps API (free tier available)
ELECTRICITY_MAPS_API_KEY = os.getenv("ELECTRICITY_MAPS_API_KEY", "")
ELECTRICITY_MAPS_ZONE = os.getenv(
    "ELECTRICITY_MAPS_ZONE", "US-CAL-CISO"
)  # California ISO

# Power consumption estimates (Watts)
CPU_IDLE_WATTS = 10.0
CPU_ACTIVE_WATTS = 65.0  # Typical laptop/desktop CPU under load
GPU_INFERENCE_WATTS = 150.0  # If using GPU for LLM


class TaskPriority(Enum):
    """Task priority levels for carbon-aware scheduling."""

    CRITICAL = "critical"  # Run immediately regardless of carbon
    HIGH = "high"  # Run soon, mild deferral ok
    NORMAL = "normal"  # Standard deferral allowed
    LOW = "low"  # Heavy deferral, wait for low-carbon window


@dataclass
class ScheduledTask:
    """A task scheduled for carbon-aware execution."""

    name: str
    priority: TaskPriority
    task_fn: Callable
    args: tuple = ()
    kwargs: dict | None = None
    max_defer_hours: float = 24.0
    created_at: float | None = None
    estimated_watts: float = CPU_ACTIVE_WATTS
    estimated_duration_seconds: float = 60.0

    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}
        if self.created_at is None:
            self.created_at = time.time()


class CarbonTracker:
    """
    Tracks carbon intensity and estimates emissions.

    Uses electricityMaps API when available, falls back to regional averages.
    """

    def __init__(self):
        self._grid_intensity: float = DEFAULT_GRID_INTENSITY
        self._last_update: float = 0
        self._update_interval: float = 300  # 5 minutes
        self._zone: str = ELECTRICITY_MAPS_ZONE

    @property
    def grid_intensity(self) -> float:
        """Current grid carbon intensity in gCO2/kWh."""
        return self._grid_intensity

    @property
    def is_low_carbon(self) -> bool:
        """Check if current grid intensity is below threshold."""
        return self._grid_intensity < CARBON_THRESHOLD_GCO2_KWH

    async def update_intensity(self) -> float:
        """
        Fetch current grid carbon intensity.
        Returns the intensity and updates the internal state.
        """
        now = time.time()
        if now - self._last_update < self._update_interval:
            return self._grid_intensity

        try:
            intensity = await self._fetch_from_api()
            self._grid_intensity = intensity
            self._last_update = now
            OBSERVABILITY_METRICS.grid_intensity_gco2_kwh.set(intensity)
            log.info(
                "Grid intensity updated: %.1f gCO2/kWh (zone: %s)",
                intensity,
                self._zone,
            )
        except Exception as e:
            log.warning("Failed to fetch grid intensity: %s (using default)", e)
            # Keep existing value or use default
            if self._last_update == 0:
                self._grid_intensity = DEFAULT_GRID_INTENSITY
                OBSERVABILITY_METRICS.grid_intensity_gco2_kwh.set(
                    DEFAULT_GRID_INTENSITY
                )

        return self._grid_intensity

    async def _fetch_from_api(self) -> float:
        """Fetch carbon intensity from electricityMaps API."""
        if not ELECTRICITY_MAPS_API_KEY:
            # Use fallback regional estimates
            return self._get_regional_estimate()

        import httpx

        url = f"https://api.electricitymap.org/v3/carbon-intensity/latest?zone={self._zone}"
        headers = {"auth-token": ELECTRICITY_MAPS_API_KEY}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("carbonIntensity", DEFAULT_GRID_INTENSITY))

    def _get_regional_estimate(self) -> float:
        """
        Get estimated carbon intensity based on time of day and region.
        This is a simplified model when API is unavailable.
        """
        hour = datetime.now().hour

        # Simple model: lower intensity during midday (solar peak) and night (low demand)
        # Higher during morning/evening peaks
        if 10 <= hour <= 15:
            # Midday: solar production peak
            base = 250
        elif 6 <= hour <= 9 or 17 <= hour <= 21:
            # Morning/evening peaks
            base = 450
        else:
            # Night: baseload (varies by region)
            base = 350

        # Add some randomness to simulate real-world variability
        import random

        variation = random.uniform(-50, 50)
        return max(100, base + variation)

    def estimate_carbon(
        self,
        duration_seconds: float,
        power_watts: float = CPU_ACTIVE_WATTS,
    ) -> float:
        """
        Estimate carbon emissions for a compute operation.

        Args:
            duration_seconds: How long the operation takes
            power_watts: Power consumption in Watts

        Returns:
            Estimated emissions in grams CO2eq
        """
        # Convert: Watts * seconds = Joules
        # Joules / 3600 = Wh
        # Wh / 1000 = kWh
        # kWh * gCO2/kWh = gCO2
        energy_kwh = (power_watts * duration_seconds) / 3_600_000
        carbon_grams = energy_kwh * self._grid_intensity
        return carbon_grams


class CarbonAwareScheduler:
    """
    Scheduler that defers non-critical tasks to low-carbon windows.

    Tasks are queued and executed when:
    - Grid intensity is below threshold, OR
    - Task has waited longer than max_defer_hours, OR
    - Task priority is CRITICAL
    """

    def __init__(self, tracker: CarbonTracker | None = None):
        self.tracker = tracker or CarbonTracker()
        self._queue: list[ScheduledTask] = []
        self._running: bool = False
        self._check_interval: float = 60.0  # Check every minute
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the scheduler background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        log.info("Carbon-aware scheduler started")

    async def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Carbon-aware scheduler stopped")

    def schedule(self, task: ScheduledTask) -> None:
        """Add a task to the queue."""
        self._queue.append(task)
        log.info("Task '%s' scheduled (priority: %s)", task.name, task.priority.value)

    def schedule_task(
        self,
        name: str,
        task_fn: Callable,
        priority: TaskPriority = TaskPriority.NORMAL,
        max_defer_hours: float = 24.0,
        estimated_duration_seconds: float = 60.0,
        **kwargs,
    ) -> None:
        """Convenience method to schedule a task."""
        task = ScheduledTask(
            name=name,
            task_fn=task_fn,
            priority=priority,
            max_defer_hours=max_defer_hours,
            estimated_duration_seconds=estimated_duration_seconds,
            kwargs=kwargs,
        )
        self.schedule(task)

    async def _scheduler_loop(self):
        """Main scheduler loop."""
        while self._running:
            try:
                await self.tracker.update_intensity()
                await self._process_queue()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Scheduler error: %s", e)
                await asyncio.sleep(self._check_interval)

    async def _process_queue(self):
        """Process pending tasks based on carbon intensity."""
        if not self._queue:
            return

        now = time.time()
        is_low_carbon = self.tracker.is_low_carbon
        intensity = self.tracker.grid_intensity

        tasks_to_run = []
        remaining = []

        for task in self._queue:
            created = task.created_at or now
            age_hours = (now - created) / 3600
            should_run = False

            if task.priority == TaskPriority.CRITICAL:
                should_run = True
                log.debug("Running critical task '%s'", task.name)
            elif age_hours >= task.max_defer_hours:
                should_run = True
                log.info(
                    "Task '%s' exceeded max defer time (%.1fh), running now",
                    task.name,
                    age_hours,
                )
            elif is_low_carbon:
                should_run = True
                log.info(
                    "Low carbon window (%.1f gCO2/kWh), running task '%s'",
                    intensity,
                    task.name,
                )
            elif (
                task.priority == TaskPriority.HIGH
                and intensity < CARBON_THRESHOLD_GCO2_KWH * 1.5
            ):
                should_run = True
                log.info(
                    "Acceptable carbon (%.1f gCO2/kWh), running high-priority task '%s'",
                    intensity,
                    task.name,
                )

            if should_run:
                tasks_to_run.append(task)
            else:
                remaining.append(task)
                OBSERVABILITY_METRICS.queries_deferred_for_carbon.inc()

        self._queue = remaining

        for task in tasks_to_run:
            await self._execute_task(task)

    async def _execute_task(self, task: ScheduledTask):
        """Execute a scheduled task and record carbon emissions."""
        start_time = time.time()
        try:
            kwargs = task.kwargs or {}
            if asyncio.iscoroutinefunction(task.task_fn):
                await task.task_fn(*task.args, **kwargs)
            else:
                task.task_fn(*task.args, **kwargs)

            duration = time.time() - start_time
            carbon = self.tracker.estimate_carbon(duration, task.estimated_watts)
            OBSERVABILITY_METRICS.record_carbon(carbon)
            log.info(
                "Task '%s' completed in %.2fs, estimated carbon: %.4f gCO2",
                task.name,
                duration,
                carbon,
            )
        except Exception as e:
            log.error("Task '%s' failed: %s", task.name, e)

    def get_queue_status(self) -> dict:
        """Return current queue status."""
        return {
            "queued_tasks": len(self._queue),
            "grid_intensity_gco2_kwh": self.tracker.grid_intensity,
            "is_low_carbon": self.tracker.is_low_carbon,
            "threshold_gco2_kwh": CARBON_THRESHOLD_GCO2_KWH,
            "tasks": [
                {
                    "name": t.name,
                    "priority": t.priority.value,
                    "age_hours": (time.time() - (t.created_at or time.time())) / 3600,
                    "max_defer_hours": t.max_defer_hours,
                }
                for t in self._queue
            ],
        }


# Module-level singletons
CARBON_TRACKER = CarbonTracker()
CARBON_SCHEDULER = CarbonAwareScheduler(CARBON_TRACKER)


def estimate_query_carbon(duration_seconds: float, used_gpu: bool = False) -> float:
    """
    Estimate carbon emissions for a RAG query.

    Args:
        duration_seconds: Query duration
        used_gpu: Whether GPU was used for inference

    Returns:
        Estimated grams CO2eq
    """
    power = GPU_INFERENCE_WATTS if used_gpu else CPU_ACTIVE_WATTS
    return CARBON_TRACKER.estimate_carbon(duration_seconds, power)
