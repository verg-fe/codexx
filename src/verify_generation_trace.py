"""Check output tracing using temporary files and mock HTTP only.

This suite never sends a request to the real model or reads an API credential.
"""
from contextlib import ExitStack
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import tracemalloc
import unittest
from unittest.mock import patch

import gateway
from generation_trace import GenerationTrace


MODEL = next(iter(gateway.MODELS))
ROUTING = {'model': MODEL, 'context_limit': 256000, 'runtime_context': 109568,
           'kv_cache_location': 'gpu', 'prompt_tokens': 13,
           'reasoning_budget': -1, 'media_converted_to_png': 0}


def records(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def reconstruct(rows):
    result = {}
    for row in rows:
        if row['event'] not in ('generated_delta', 'stream_snapshot'):
            continue
        key = row['channel'], row['item_id'], row['content_index']
        if row['event'] == 'stream_snapshot':
            result[key] = row['text']
        else:
            result[key] = result.get(key, '') + row['delta']
    return result


def delta(kind, item_id, text, **extra):
    return {'type': 'response.' + kind + '.delta', 'item_id': item_id,
            'delta': text, **extra}


def completed(output):
    return {'type': 'response.completed', 'response': {'id': 'mock-response',
            'status': 'completed', 'output': output, 'usage': {
                'input_tokens': 13, 'output_tokens': 8,
                'output_tokens_details': {'reasoning_tokens': 4}}}}


class GenerationTraceChecks(unittest.TestCase):
    def test_all_generated_channels_are_streamed_without_final_duplication(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = GenerationTrace(directory, ROUTING)
            # Advancing the clock forces the normal one-second flush policy.
            with patch('generation_trace.time.monotonic', return_value=trace.started + 2):
                trace.event(delta('reasoning_text', 'r', '先想一想'))
            self.assertEqual(reconstruct(records(trace.path))[('reasoning', 'r', 0)], '先想一想')
            trace.event(delta('reasoning_summary_text', 'r', 'summary', summary_index=1))
            trace.event(delta('output_text', 'm', '完成', content_index=0))
            trace.event(delta('output_text', 'm', '第二段', content_index=1))
            trace.event(delta('function_call_arguments', 'f', '{"path":'))
            trace.event(delta('function_call_arguments', 'f', '"a.txt"}'))
            trace.event(delta('custom_tool_call_input', 'c', '*** Begin Patch'))
            final_items = [
                {'type': 'reasoning', 'id': 'r', 'content': [
                    {'type': 'reasoning_text', 'text': '先想一想'}], 'summary': [
                    {'type': 'summary_text', 'text': ''},
                    {'type': 'summary_text', 'text': 'summary'}]},
                {'type': 'message', 'id': 'm', 'content': [
                    {'type': 'output_text', 'text': '完成'},
                    {'type': 'output_text', 'text': '第二段'}]},
                {'type': 'function_call', 'id': 'f', 'name': 'write_file',
                 'call_id': 'call-f', 'arguments': '{"path":"a.txt"}'},
                {'type': 'custom_tool_call', 'id': 'c', 'name': 'apply_patch',
                 'call_id': 'call-c', 'input': '*** Begin Patch'},
            ]
            for item in final_items:
                trace.event({'type': 'response.output_item.done', 'item': item})
            trace.event(completed(final_items))
            trace.finish('upstream_eof', 200)
            rows = records(trace.path)
            expected = {('reasoning', 'r', 0): '先想一想',
                        ('reasoning_summary', 'r', 1): 'summary',
                        ('text', 'm', 0): '完成', ('text', 'm', 1): '第二段',
                        ('tool_arguments', 'f', 0): '{"path":"a.txt"}',
                        ('tool_input', 'c', 0): '*** Begin Patch'}
            self.assertEqual(reconstruct(rows), expected)
            self.assertEqual(sum(row['event'] == 'generated_delta' for row in rows), 7)
            self.assertFalse(any(row['event'] == 'stream_snapshot' for row in rows))
            self.assertEqual(rows[-1]['generated_characters']['reasoning'], len('先想一想'))
            self.assertEqual(rows[-2]['usage']['output_tokens_details']['reasoning_tokens'], 4)

    def test_done_tail_is_saved_once_across_done_item_and_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = GenerationTrace(directory, ROUTING)
            trace.event(delta('output_text', 'm', 'hello'))
            trace.event({'type': 'response.output_text.done', 'item_id': 'm', 'text': 'hello world'})
            item = {'type': 'message', 'id': 'm', 'content': [
                {'type': 'output_text', 'text': 'hello world'}]}
            trace.event({'type': 'response.output_item.done', 'item': item})
            trace.event(completed([item]))
            trace.finish('upstream_eof', 200)
            rows = records(trace.path)
            tails = [row for row in rows if row.get('source') == 'done_tail']
            self.assertEqual([row['delta'] for row in tails], [' world'])
            self.assertEqual(reconstruct(rows)[('text', 'm', 0)], 'hello world')

    def test_final_revision_replaces_previous_content_including_shortening(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = GenerationTrace(directory, ROUTING)
            trace.event(delta('output_text', 'm', 'provisional longer answer'))
            trace.event({'type': 'response.output_text.done', 'item_id': 'm', 'text': 'final'})
            trace.event(completed([{'type': 'message', 'id': 'm', 'content': [
                {'type': 'output_text', 'text': 'final'}]}]))
            trace.finish('upstream_eof', 200)
            rows = records(trace.path)
            snapshots = [row for row in rows if row['event'] == 'stream_snapshot']
            self.assertEqual(len(snapshots), 1)
            self.assertTrue(snapshots[0]['replaces_previous'])
            self.assertEqual(reconstruct(rows)[('text', 'm', 0)], 'final')
            self.assertEqual(rows[-1]['generated_characters'], {'text': 5})

    def test_large_stream_keeps_only_counts_hashes_then_releases_on_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = GenerationTrace(directory, ROUTING)
            piece = 'generated content ' * 1024
            for unused in range(64):
                trace.event(delta('reasoning_text', 'r', piece))
            self.assertEqual(len(trace.streams), 1)
            count, digest = trace.streams[('reasoning', 'r', 0)]
            self.assertEqual(count, len(piece) * 64)
            self.assertEqual(len(digest.digest()), 32)
            self.assertFalse(any(isinstance(value, str) for value in (count, digest)))
            file_handle = trace.file
            trace.finish('client_disconnected', 200)
            self.assertTrue(trace.closed)
            self.assertTrue(file_handle.closed)
            self.assertIsNone(trace.file)
            self.assertEqual(trace.streams, {})
            rows = records(trace.path)
            self.assertEqual(reconstruct(rows)[('reasoning', 'r', 0)], piece * 64)
            self.assertEqual(rows[-1]['transport'], 'client_disconnected')
            self.assertIsNone(rows[-1]['upstream_terminal'])
            before = trace.path.read_bytes()
            trace.finish('second_finish', 500)
            trace.event(delta('output_text', 'm', 'ignored after close'))
            self.assertEqual(trace.path.read_bytes(), before)

    def test_ten_megabyte_output_does_not_accumulate_in_python_ram(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = GenerationTrace(directory, ROUTING)
            piece = 'x' * 1024
            event = delta('reasoning_text', 'r', piece)
            # Warm the serializer and trace item before measuring. Do not parse
            # the generated file or build the final output during measurement.
            trace.event(event)
            tracemalloc.start()
            try:
                for unused in range(10240):
                    trace.event(event)
                current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertLess(peak, 1024 * 1024)
            self.assertEqual(trace.streams[('reasoning', 'r', 0)][0], 1024 * 10241)
            trace.finish('client_disconnected', 200)
            self.assertGreater(trace.path.stat().st_size, 10 * 1024 * 1024)
            self.assertEqual(trace.streams, {})
            print('Trace RAM measurement: generated=10 MiB, current=' + str(current)
                  + ' bytes, peak=' + str(peak) + ' bytes', flush=True)

    def test_disk_creation_failure_disables_tracing_without_raising(self):
        with patch('generation_trace.Path.mkdir', side_effect=OSError('mock disk failure')):
            with patch('builtins.print'):
                trace = GenerationTrace('not-created', ROUTING)
                trace.event(delta('reasoning_text', 'r', 'should still infer'))
                trace.finish('upstream_eof', 200)
        self.assertIsNone(trace.file)
        self.assertEqual(trace.streams, {})
        self.assertTrue(trace.closed)

    def test_disk_write_or_flush_failure_closes_writer_without_raising(self):
        class FaultyDisk:
            def __init__(self, fail_flush):
                self.fail_flush = fail_flush
                self.closed = False

            def write(self, text):
                if not self.fail_flush:
                    raise OSError('mock disk full')

            def flush(self):
                raise OSError('mock disk full on flush')

            def close(self):
                self.closed = True

        for fail_flush in (False, True):
            with self.subTest(fail_flush=fail_flush), tempfile.TemporaryDirectory() as directory:
                trace = GenerationTrace(directory, ROUTING)
                trace.file.close()
                disk = FaultyDisk(fail_flush)
                trace.file = disk
                with patch('builtins.print'), patch('generation_trace.time.monotonic', return_value=trace.started + 2):
                    trace.event(delta('reasoning_text', 'r', 'not retained'))
                    trace.event(delta('output_text', 'm', 'keep inference working'))
                    trace.finish('upstream_eof', 200)
                self.assertTrue(disk.closed)
                self.assertIsNone(trace.file)
                self.assertEqual(trace.streams, {})

    def test_metadata_and_terminal_do_not_dump_inputs_images_or_authorization(self):
        private = 'PRIVATE_REQUEST_SENTINEL'
        with tempfile.TemporaryDirectory() as directory:
            trace = GenerationTrace(directory, {**ROUTING, 'input': private,
                'instructions': private, 'Authorization': private,
                'api_key': private, 'image_url': 'data:image/png;base64,' + private})
            terminal = completed([])
            terminal['response'].update(input=private, instructions=private,
                error={'code': 'test_error', 'message': private})
            terminal['response']['usage']['secret'] = private
            terminal['response']['usage']['input_tokens_details'] = {'cached_tokens': 3, 'secret': private}
            terminal['timings'] = {'predicted_per_second': 28.3, 'secret': private}
            trace.event(terminal)
            trace.finish('upstream_eof', 200)
            raw = trace.path.read_text(encoding='utf-8')
            self.assertNotIn(private, raw)
            self.assertNotIn('Authorization', raw)
            self.assertNotIn('data:image', raw)
            rows = records(trace.path)
            self.assertEqual(rows[0]['reasoning_budget'], -1)
            self.assertEqual(rows[-2]['usage']['input_tokens_details'], {'cached_tokens': 3})
            self.assertEqual(rows[-2]['timings'], {'predicted_per_second': 28.3})


class MockResponse(io.BytesIO):
    def __init__(self, events):
        payload = ''.join(('event: ' + item['type'] + '\n' if item.get('type') else '')
                          + 'data: ' + json.dumps(item) + '\n\n'
                          for item in events).encode('utf-8')
        super().__init__(payload)
        self.status = 200
        self.headers = {'Content-Type': 'text/event-stream'}


class GatewayTraceChecks(unittest.TestCase):
    def fixture(self, directory, events):
        instances = []

        class TrackingTrace(GenerationTrace):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.finished = threading.Event()
                instances.append(self)

            def finish(self, *args, **kwargs):
                try:
                    return super().finish(*args, **kwargs)
                finally:
                    self.finished.set()

        stack = ExitStack()
        stack.enter_context(patch.object(gateway, 'ROOT', Path(directory)))
        stack.enter_context(patch.object(gateway, 'load_settings', return_value={'api_key': 'mock-authorization'}))
        stack.enter_context(patch.object(gateway, 'route_inference', return_value=dict(ROUTING)))
        stack.enter_context(patch.object(gateway, 'GenerationTrace', TrackingTrace))
        stack.enter_context(patch.object(gateway.urllib.request, 'urlopen', return_value=MockResponse(events)))
        return stack, instances

    def test_short_mock_http_sse_is_unchanged_and_finish_runs(self):
        output = {'type': 'message', 'id': 'm', 'content': [{'type': 'output_text', 'text': 'mock visible answer'}]}
        events = [delta('reasoning_text', 'r', 'mock thought'),
                  delta('output_text', 'm', 'mock visible answer'), completed([output])]
        with tempfile.TemporaryDirectory() as directory:
            stack, instances = self.fixture(directory, events)
            with stack:
                class QuietHandler(gateway.Handler):
                    def log_message(self, *args):
                        pass

                server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    private = 'PRIVATE_HTTP_INPUT_SENTINEL'
                    connection.request('POST', '/v1/responses', json.dumps({
                        'model': MODEL, 'input': private, 'stream': True}), headers={
                        'Authorization': 'Bearer mock-authorization', 'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    result = response.read().decode('utf-8')
                    self.assertEqual(response.status, 200)
                    self.assertIn('mock visible answer', result)
                    self.assertIn('response.completed', result)
                    self.assertEqual(len(instances), 1)
                    self.assertTrue(instances[0].finished.wait(2))
                    trace = instances[0]
                    rows = records(trace.path)
                    self.assertEqual(rows[-1]['transport'], 'upstream_eof')
                    self.assertEqual(rows[-1]['upstream_terminal'], 'response.completed')
                    self.assertEqual(reconstruct(rows)[('reasoning', 'r', 0)], 'mock thought')
                    raw = trace.path.read_text(encoding='utf-8')
                    self.assertNotIn(private, raw)
                    self.assertNotIn('mock-authorization', raw)
                    self.assertTrue(trace.closed)
                    self.assertEqual(trace.streams, {})
                finally:
                    connection.close()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def fake_handler(self):
        handler = gateway.Handler.__new__(gateway.Handler)
        handler.command = 'POST'
        handler.path = '/v1/responses'
        body = json.dumps({'model': MODEL, 'input': 'mock input', 'stream': True}).encode()
        handler.headers = {'Authorization': 'Bearer mock-authorization', 'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = lambda *args: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        return handler

    def test_client_disconnect_still_finishes_and_preserves_last_received_delta(self):
        class DisconnectedWriter:
            def write(self, data):
                raise BrokenPipeError('mock client disconnected')

            def flush(self):
                pass

        events = [delta('reasoning_text', 'r', 'last thought received'),
                  delta('output_text', 'm', 'never reached')]
        with tempfile.TemporaryDirectory() as directory:
            stack, instances = self.fixture(directory, events)
            with stack:
                handler = self.fake_handler()
                handler.wfile = DisconnectedWriter()
                handler.forward_request()
                self.assertIsNone(handler.trace)
                self.assertEqual(len(instances), 1)
                trace = instances[0]
                self.assertTrue(trace.closed)
                self.assertIsNone(trace.file)
                self.assertEqual(trace.streams, {})
                rows = records(trace.path)
                self.assertEqual(rows[-1]['transport'], 'client_disconnected')
                self.assertEqual(reconstruct(rows), {('reasoning', 'r', 0): 'last thought received'})

    def test_gateway_finally_closes_trace_when_upstream_parse_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, instances = self.fixture(directory, [])
            with stack:
                invalid = MockResponse([])
                invalid.write(b'data: invalid-json\n\n')
                invalid.seek(0)
                with patch.object(gateway.urllib.request, 'urlopen', return_value=invalid):
                    handler = self.fake_handler()
                    with self.assertRaises(json.JSONDecodeError):
                        handler.forward_request()
                self.assertIsNone(handler.trace)
                self.assertTrue(instances[0].closed)
                self.assertEqual(instances[0].streams, {})
                self.assertEqual(records(instances[0].path)[-1]['transport'], 'proxy_error')

    def test_disabled_trace_does_not_change_gateway_output(self):
        item = {'type': 'message', 'id': 'm', 'content': [{'type': 'output_text', 'text': 'inference survives'}]}
        events = [delta('output_text', 'm', 'inference survives'), completed([item])]
        with tempfile.TemporaryDirectory() as directory:
            stack, instances = self.fixture(directory, events)
            with stack, patch('generation_trace.Path.mkdir', side_effect=OSError('mock disk full')), patch('builtins.print'):
                handler = self.fake_handler()
                handler.forward_request()
                result = handler.wfile.getvalue().decode('utf-8')
                self.assertIn('inference survives', result)
                self.assertIn('response.completed', result)
                self.assertTrue(instances[0].closed)
                self.assertIsNone(instances[0].file)

    def test_bare_upstream_error_is_forwarded_and_logs_only_code_and_type(self):
        private = 'PRIVATE_UPSTREAM_ERROR_MESSAGE'
        events = [{'error': {'code': 400, 'type': 'invalid_request_error', 'message': private}}]
        with tempfile.TemporaryDirectory() as directory:
            stack, instances = self.fixture(directory, events)
            with stack:
                handler = self.fake_handler()
                handler.forward_request()
                result = handler.wfile.getvalue().decode('utf-8')
                self.assertIn(private, result)
                self.assertIn('invalid_request_error', result)
                trace = instances[0]
                rows = records(trace.path)
                errors = [row for row in rows if row['event'] == 'upstream_error']
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0]['code'], 400)
                self.assertEqual(errors[0]['error_type'], 'invalid_request_error')
                self.assertNotIn(private, trace.path.read_text(encoding='utf-8'))
                self.assertTrue(trace.closed)

    def test_reasoning_only_failure_keeps_original_trace_and_adapter_outcome(self):
        item = {'type': 'reasoning', 'id': 'r', 'content': [
            {'type': 'reasoning_text', 'text': 'thinking without answer'}]}
        events = [delta('reasoning_text', 'r', 'thinking without answer'), completed([item])]
        with tempfile.TemporaryDirectory() as directory:
            stack, instances = self.fixture(directory, events)
            with stack:
                handler = self.fake_handler()
                handler.forward_request()
                self.assertIn('response.failed', handler.wfile.getvalue().decode('utf-8'))
                rows = records(instances[0].path)
                terminal = next(row for row in rows if row['event'] == 'upstream_terminal')
                adapter = next(row for row in rows if row['event'] == 'adapter_terminal')
                self.assertEqual(terminal['type'], 'response.completed')
                self.assertEqual(adapter['type'], 'response.failed')
                self.assertEqual(reconstruct(rows)[('reasoning', 'r', 0)], 'thinking without answer')


if __name__ == '__main__':
    unittest.main(verbosity=2)
