from concurrent.futures import ThreadPoolExecutor
import threading

from services.api.store import Store


def test_shared_store_serializes_transactions_and_cursor_consumption(tmp_path):
    store = Store(tmp_path)
    gate = threading.Barrier(6)

    def writer(number):
        gate.wait()
        for index in range(100):
            item = {'id': f'{number}-{index}', 'writer': number, 'index': index}
            store.save('entries', item)
            assert store.get('entries', item['id']) == item

    def reader():
        gate.wait()
        previous_count = 0
        for _ in range(200):
            rows = store.all('entries')
            assert len(rows) >= previous_count
            assert len({row['id'] for row in rows}) == len(rows)
            previous_count = len(rows)

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(writer, number) for number in range(3)]
            futures += [pool.submit(reader) for _ in range(3)]
            for future in futures:
                future.result(timeout=15)
        assert len(store.all('entries')) == 300
        backup = store.backup()
        assert backup.is_file()
    finally:
        store.close()
