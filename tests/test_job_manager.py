import threading
import time
import unittest

from app.job_manager import JobManager, RoutingJobManager


class RoutingJobManagerTests(unittest.TestCase):
    def test_comfyui_workflows_share_one_execution_lane_across_owners(self):
        comfy = JobManager(worker_count=1)
        external = JobManager(worker_count=3)
        routing = RoutingJobManager(
            comfy,
            external,
            {
                "RMBG2": {"provider": "comfyui"},
                "Hosted": {"provider": "openrouter"},
            },
        )
        state_lock = threading.Lock()
        active_local = 0
        max_active_local = 0
        intervals: dict[str, list[float]] = {}

        def processor(job, progress):
            nonlocal active_local, max_active_local
            if job.payload["workflow_id"] != "RMBG2":
                return
            with state_lock:
                active_local += 1
                max_active_local = max(max_active_local, active_local)
                intervals[job.id] = [time.monotonic(), 0.0]
            progress(50)
            time.sleep(0.06)
            with state_lock:
                intervals[job.id][1] = time.monotonic()
                active_local -= 1

        routing.register_processor("generate", processor)
        jobs = [
            routing.enqueue(f"owner-{index % 2}", "generate", {"workflow_id": "RMBG2"})
            for index in range(4)
        ]
        routing.start()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if all(routing.get(job.id).status == "complete" for job in jobs):
                    break
                time.sleep(0.01)
            self.assertTrue(all(routing.get(job.id).status == "complete" for job in jobs))
            self.assertEqual(max_active_local, 1)
            ordered = sorted(intervals.values(), key=lambda item: item[0])
            self.assertEqual(len(ordered), 4)
            for previous, current in zip(ordered, ordered[1:]):
                self.assertGreaterEqual(current[0], previous[1])
        finally:
            routing.stop()

    def test_hosted_lane_can_run_while_local_lane_is_busy(self):
        comfy = JobManager(worker_count=1)
        external = JobManager(worker_count=2)
        routing = RoutingJobManager(
            comfy,
            external,
            {
                "RMBG2": {"provider": "comfyui"},
                "Hosted": {"provider": "openrouter"},
            },
        )
        local_started = threading.Event()
        hosted_started = threading.Event()
        release = threading.Event()

        def processor(job, progress):
            if job.payload["workflow_id"] == "RMBG2":
                local_started.set()
            else:
                hosted_started.set()
            release.wait(timeout=2)

        routing.register_processor("generate", processor)
        local = routing.enqueue("local-owner", "generate", {"workflow_id": "RMBG2"})
        hosted = routing.enqueue("hosted-owner", "generate", {"workflow_id": "Hosted"})
        routing.start()
        try:
            self.assertTrue(local_started.wait(timeout=1))
            self.assertTrue(hosted_started.wait(timeout=1))
            self.assertEqual(routing.get(local.id).status, "running")
            self.assertEqual(routing.get(hosted.id).status, "running")
        finally:
            release.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if all(routing.get(job.id).status == "complete" for job in (local, hosted)):
                    break
                time.sleep(0.01)
            routing.stop()


if __name__ == "__main__":
    unittest.main()
