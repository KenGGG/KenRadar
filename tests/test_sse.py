"""Focused SSE broadcaster and frame contract tests."""
import asyncio


def test_sse_frame_and_heartbeat_contract() -> None:
    from kenradar.web.sse import format_sse_event, heartbeat_frame

    frame = format_sse_event({"type": "research_job.updated", "payload": {"progress": 3}}, event_id=7)
    assert frame.startswith("id: 7\nevent: message\ndata: ")
    assert frame.endswith("\n\n")
    assert '"progress": 3' in frame
    assert "event: heartbeat" in heartbeat_frame()


def test_sse_subscribe_publish_unsubscribe_and_cleanup() -> None:
    from kenradar.web.sse import SSEBroadcaster

    async def scenario() -> None:
        broadcaster = SSEBroadcaster()
        client = await broadcaster.subscribe()
        assert await broadcaster.count() == 1
        await broadcaster.publish({"type": "research_job.updated"})
        assert client.queue[-1]["type"] == "research_job.updated"
        await broadcaster.unsubscribe(client)
        assert await broadcaster.count() == 0
        assert not client.queue

    asyncio.run(scenario())
