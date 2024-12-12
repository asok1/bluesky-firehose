import multiprocessing
import signal
import time
from collections import defaultdict
from types import FrameType
from typing import Any

from atproto import CAR, AtUri, FirehoseSubscribeReposClient, firehose_models, models, parse_subscribe_repos_message

import clickhouse_connect
import uuid

from atproto_firehose.exceptions import FirehoseError

from opentelemetry import metrics, trace

import os
from dotenv import load_dotenv

load_dotenv("config.env")
HOST = os.getenv('host')
USER = os.getenv('user')
PWD = os.getenv('password')
IS_SECURE = os.getenv('secure')

# Acquire a tracer
tracer = trace.get_tracer("firehose.tracer")
# Acquire a meter.
meter = metrics.get_meter("firehose.meter")
# Now create a counter instrument to make measurements with

event_rate = meter.create_gauge(
    "event.rate",
    description="Number of inbound events per second",
)

_INTERESTED_RECORDS = {
    models.ids.AppBskyFeedLike: models.AppBskyFeedLike,
    models.ids.AppBskyFeedPost: models.AppBskyFeedPost,
    models.ids.AppBskyGraphFollow: models.AppBskyGraphFollow,
}

def appendContentTable_Clickhouse(timestamp, authorId, postContent, uri, cid):
    client = clickhouse_connect.get_client(
        host=HOST,
        user=USER,
        password=PWD,
        secure=IS_SECURE
    )
    # Sample data to insert
    data = [
        (str(uuid.uuid4()),timestamp, authorId, postContent, uri, cid),
    ]


    # Send data to ClickHouse
    client.insert(
        table='activity',    # Name of the table
        data=data,            # Data to insert as a list of tuples
        settings={'async_insert': 1, 'wait_for_async_insert': 1}
    )

    client.close()


def _get_ops_by_type(commit: models.ComAtprotoSyncSubscribeRepos.Commit) -> defaultdict:
    operation_by_type = defaultdict(lambda: {'created': [], 'deleted': []})

    car = CAR.from_bytes(commit.blocks)
    for op in commit.ops:
        if op.action == 'update':
            # not supported yet
            continue

        uri = AtUri.from_str(f'at://{commit.repo}/{op.path}')

        if op.action == 'create':
            if not op.cid:
                continue

            create_info = {'uri': str(uri), 'cid': str(op.cid), 'author': commit.repo}

            record_raw_data = car.blocks.get(op.cid)
            if not record_raw_data:
                continue

            try:
                record = models.get_or_create(record_raw_data, strict=False)
                record_type = _INTERESTED_RECORDS.get(uri.collection)
                if record_type and models.is_record_type(record, record_type):
                    operation_by_type[uri.collection]['created'].append({'record': record, **create_info})
            except:
                print(f'ERROR PROCESSING RECORD %s', record_raw_data)

        if op.action == 'delete':
            operation_by_type[uri.collection]['deleted'].append({'uri': str(uri)})

    return operation_by_type


def worker_main(cursor_value: multiprocessing.Value, pool_queue: multiprocessing.Queue) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # we handle it in the main process

    while True:
        message = pool_queue.get()

        commit = parse_subscribe_repos_message(message)
        if not isinstance(commit, models.ComAtprotoSyncSubscribeRepos.Commit):
            continue

        if commit.seq % 20 == 0:
            cursor_value.value = commit.seq

        if not commit.blocks:
            continue

        ops = _get_ops_by_type(commit)
        for created_post in ops[models.ids.AppBskyFeedPost]['created']:
            author = created_post['author']
            record = created_post['record']
            uri = created_post['uri']
            cid = created_post['cid']

            inlined_text = record.text.replace('\n', ' ')
            print(f'full post data: {created_post}')
            appendContentTable_Clickhouse(record.created_at, author, inlined_text, uri, cid)



def get_firehose_params(cursor_value: multiprocessing.Value) -> models.ComAtprotoSyncSubscribeRepos.Params:
    return models.ComAtprotoSyncSubscribeRepos.Params(cursor=cursor_value.value)


def measure_events_per_second(func: callable) -> callable:
    def wrapper(*args) -> Any:
        wrapper.calls += 1
        cur_time = time.time()

        if cur_time - wrapper.start_time >= 1:
            print(f'NETWORK LOAD: {wrapper.calls} events/second')
            event_rate.set(wrapper.calls)
            wrapper.start_time = cur_time
            wrapper.calls = 0

        return func(*args)

    wrapper.calls = 0
    wrapper.start_time = time.time()

    return wrapper


def signal_handler(_: int, __: FrameType) -> None:
    print('Keyboard interrupt received. Waiting for the queue to empty before terminating processes...')

    # Stop receiving new messages
    client.stop()

    # Drain the messages queue
    while not queue.empty():
        print('Waiting for the queue to empty...')
        time.sleep(0.2)

    print('Queue is empty. Gracefully terminating processes...')

    pool.terminate()
    pool.join()

    exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)

    start_cursor = None

    params = None
    cursor = multiprocessing.Value('i', 0)
    if start_cursor is not None:
        cursor = multiprocessing.Value('i', start_cursor)
        params = get_firehose_params(cursor)

    client = FirehoseSubscribeReposClient(params)

    workers_count = multiprocessing.cpu_count() * 2 - 1
    max_queue_size = 10

    queue = multiprocessing.Queue(maxsize=max_queue_size)
    pool = multiprocessing.Pool(workers_count, worker_main, (cursor, queue))

    @measure_events_per_second
    def on_message_handler(message: firehose_models.MessageFrame) -> None:
        if cursor.value:
            # we are using updating the cursor state here because of multiprocessing
            # typically you can call client.update_params() directly on commit processing
            client.update_params(get_firehose_params(cursor))

        queue.put(message)

    while True:
        try:
            client.start(on_message_handler)
        except FirehoseError:
            a = 1+1
            print(f'RUNTIME ERROR %s', "what is happening oof")
