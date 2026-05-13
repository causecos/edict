import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from edict.backend.app.workers.orchestrator_worker import OrchestratorWorker


class FakeBus:
    def __init__(self):
        self.published = []

    async def publish(self, **kwargs):
        self.published.append(kwargs)


def test_task_created_defaults_to_taizi_on_missing_or_legacy_state():
    worker = OrchestratorWorker()
    worker.bus = FakeBus()

    async def run_case(payload):
        await worker._on_task_created(payload, trace_id='trace-1')

    asyncio.run(run_case({'task_id': 'JJC-1', 'title': '測試任務'}))
    asyncio.run(run_case({'task_id': 'JJC-2', 'title': '測試任務', 'state': 'taizi'}))

    assert len(worker.bus.published) == 2
    for item in worker.bus.published:
        assert item['topic'] == 'task.dispatch'
        assert item['payload']['agent'] == 'taizi'
        assert item['payload']['state'] == 'Taizi'
        assert item['payload']['task_id'] in {'JJC-1', 'JJC-2'}
