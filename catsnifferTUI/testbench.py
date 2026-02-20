"""
CatSniffer TUI Testbench - Smoke Test Module

Automated test sequences for device validation.
"""
import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime

from .constants import (
    SMOKE_TEST_PASS_THRESHOLD,
    MAX_CONCURRENT_SMOKE_TESTS,
    SMOKE_TEST_STEP_TIMEOUT,
    CommandStatus,
)
from .device import CatSnifferDevice, CommandResult


@dataclass
class TestStep:
    """A single test step."""
    name: int
    endpoint: str  # "CDC1" or "CDC2"
    command: str
    expected_match: str  # Regex pattern
    timeout: float = SMOKE_TEST_STEP_TIMEOUT

    def __str__(self):
        return f"{self.endpoint}: {self.command}"


@dataclass
class TestStepResult:
    """Result of a single test step."""
    step: TestStep
    passed: bool
    command_result: CommandResult
    timestamp: float
    response_snippet: str = ""

    @property
    def status_text(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass
class SmokeTestResult:
    """Result of a complete smoke test."""
    device_id: int
    start_time: float
    end_time: float
    step_results: List[TestStepResult]
    interrupted: bool = False
    interrupt_reason: str = ""

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.step_results if r.passed)

    @property
    def total_count(self) -> int:
        return len(self.step_results)

    @property
    def passed(self) -> bool:
        return self.passed_count >= SMOKE_TEST_PASS_THRESHOLD

    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time


# Standard smoke test sequence
SMOKE_TEST_STEPS: List[TestStep] = [
    TestStep(1, "CDC2", "status", r"Mode:|Band:"),
    TestStep(2, "CDC2", "band3", r"LoRa|band3"),
    TestStep(3, "CDC2", "modulation lora", r"lora|LoRa"),
    TestStep(4, "CDC2", "lora_mode command", r"COMMAND"),
    TestStep(5, "CDC2", "lora_config", r"LoRa Configuration:|Frequency:"),
    TestStep(6, "CDC2", "lora_apply", r"applied|success|Applied"),
    TestStep(7, "CDC1", "TEST", r"TEST|ready|initialized"),
    TestStep(8, "CDC1", "TXTEST", r"TX Result|Success|Sending"),
    TestStep(9, "CDC2", "modulation fsk", r"fsk|FSK"),
    TestStep(10, "CDC2", "fsk_apply", r"applied|success|Applied"),
    TestStep(11, "CDC1", "FSKTEST", r"FSK|Success"),
]


class SmokeTestRunner:
    """Runs smoke tests on CatSniffer devices."""

    def __init__(self):
        self._running_tests: Dict[int, asyncio.Task] = {}
        self._results: Dict[int, SmokeTestResult] = {}
        self._on_progress: Optional[Callable[[int, TestStepResult], None]] = None
        self._on_complete: Optional[Callable[[int, SmokeTestResult], None]] = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SMOKE_TESTS)

    def set_callbacks(
        self,
        on_progress: Optional[Callable[[int, TestStepResult], None]] = None,
        on_complete: Optional[Callable[[int, SmokeTestResult], None]] = None,
    ):
        """Set progress and completion callbacks."""
        self._on_progress = on_progress
        self._on_complete = on_complete

    def is_running(self, device_id: int) -> bool:
        """Check if a test is running for a device."""
        task = self._running_tests.get(device_id)
        return task is not None and not task.done()

    def get_result(self, device_id: int) -> Optional[SmokeTestResult]:
        """Get the last test result for a device."""
        return self._results.get(device_id)

    def cancel(self, device_id: int):
        """Cancel a running test."""
        task = self._running_tests.get(device_id)
        if task and not task.done():
            task.cancel()

    async def run_single(
        self,
        device: CatSnifferDevice,
        steps: Optional[List[TestStep]] = None
    ) -> SmokeTestResult:
        """Run smoke test on a single device."""
        steps = steps or SMOKE_TEST_STEPS
        device_id = device.device_id

        result = SmokeTestResult(
            device_id=device_id,
            start_time=time.time(),
            end_time=0,
            step_results=[]
        )

        async with self._semaphore:
            device.smoke_test_running = True
            device.smoke_test_results = {}

            try:
                for step in steps:
                    # Check if device is still connected
                    if not device.shell or device.shell.state.value != "connected":
                        result.interrupted = True
                        result.interrupt_reason = "Device disconnected"
                        break

                    # Execute step
                    step_result = await self._execute_step(device, step)
                    result.step_results.append(step_result)

                    # Store in device
                    device.smoke_test_results[step.name] = step_result.command_result

                    # Progress callback
                    if self._on_progress:
                        self._on_progress(device_id, step_result)

                    # Small delay between steps
                    await asyncio.sleep(0.2)

            except asyncio.CancelledError:
                result.interrupted = True
                result.interrupt_reason = "Test cancelled"

            except Exception as e:
                result.interrupted = True
                result.interrupt_reason = str(e)

            finally:
                device.smoke_test_running = False
                result.end_time = time.time()
                self._results[device_id] = result

                # Completion callback
                if self._on_complete:
                    self._on_complete(device_id, result)

        return result

    async def _execute_step(self, device: CatSnifferDevice, step: TestStep) -> TestStepResult:
        """Execute a single test step."""
        pattern = re.compile(step.expected_match, re.IGNORECASE)

        # Select endpoint
        if step.endpoint == "CDC2":
            result = await device.send_shell_command(
                step.command,
                timeout=step.timeout,
                expected_match=pattern
            )
        elif step.endpoint == "CDC1":
            result = await device.send_lora_command(
                step.command,
                timeout=step.timeout,
                expected_match=pattern
            )
        else:
            result = CommandResult(
                command=step.command,
                status=CommandStatus.ERROR,
                response=None,
                duration_ms=0,
                retries=0,
                error=f"Unknown endpoint: {step.endpoint}"
            )

        # Check if response matches expected pattern
        passed = False
        if result.passed and result.response:
            passed = bool(pattern.search(result.response))

        return TestStepResult(
            step=step,
            passed=passed,
            command_result=result,
            timestamp=time.time(),
            response_snippet=(result.response[:100] if result.response else "")[:50]
        )

    async def run_multiple(
        self,
        devices: List[CatSnifferDevice],
        steps: Optional[List[TestStep]] = None
    ) -> Dict[int, SmokeTestResult]:
        """Run smoke tests on multiple devices in parallel (rate-limited)."""
        tasks = {}

        for device in devices:
            task = asyncio.create_task(self.run_single(device, steps))
            self._running_tests[device.device_id] = task
            tasks[device.device_id] = task

        # Wait for all to complete
        results = {}
        for device_id, task in tasks.items():
            try:
                results[device_id] = await task
            except asyncio.CancelledError:
                pass

        return results


class FleetActions:
    """Fleet-wide actions for all devices."""

    def __init__(self):
        self._on_complete: Optional[Callable[[str, Dict[int, CommandResult]], None]] = None

    def set_callbacks(
        self,
        on_complete: Optional[Callable[[str, Dict[int, CommandResult]], None]] = None,
    ):
        """Set completion callback."""
        self._on_complete = on_complete

    async def set_all_band(
        self,
        devices: List[CatSnifferDevice],
        band: str
    ) -> Dict[int, CommandResult]:
        """Set band on all devices."""
        results = {}
        tasks = {}

        for device in devices:
            if device.shell:
                tasks[device.device_id] = asyncio.create_task(device.set_band(band))

        for device_id, task in tasks.items():
            try:
                results[device_id] = await task
            except Exception as e:
                results[device_id] = CommandResult(
                    command=band,
                    status=CommandStatus.ERROR,
                    response=None,
                    duration_ms=0,
                    retries=0,
                    error=str(e)
                )

        if self._on_complete:
            self._on_complete(f"set_all_{band}", results)

        return results

    async def set_all_lora_freq(
        self,
        devices: List[CatSnifferDevice],
        freq_hz: int
    ) -> Dict[int, CommandResult]:
        """Set LoRa frequency on all devices."""
        results = {}
        tasks = {}

        for device in devices:
            if device.shell:
                tasks[device.device_id] = asyncio.create_task(
                    device.send_shell_command(f"lora_freq {freq_hz}")
                )

        for device_id, task in tasks.items():
            try:
                results[device_id] = await task
            except Exception as e:
                results[device_id] = CommandResult(
                    command=f"lora_freq {freq_hz}",
                    status=CommandStatus.ERROR,
                    response=None,
                    duration_ms=0,
                    retries=0,
                    error=str(e)
                )

        if self._on_complete:
            self._on_complete("set_all_lora_freq", results)

        return results

    async def refresh_all_status(
        self,
        devices: List[CatSnifferDevice]
    ) -> Dict[int, bool]:
        """Refresh status on all devices."""
        results = {}
        tasks = {}

        for device in devices:
            if device.shell:
                tasks[device.device_id] = asyncio.create_task(device.refresh_status())

        for device_id, task in tasks.items():
            try:
                results[device_id] = await task
            except Exception:
                results[device_id] = False

        return results
