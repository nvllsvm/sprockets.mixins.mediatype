import base64
import datetime
import json
import os
import pickle
import struct
import sys
import unittest
import uuid

from tornado import testing
import umsgpack

from sprockets.mixins.mediatype import content, handlers, transcoders
import examples


class UTC(datetime.tzinfo):
    ZERO = datetime.timedelta(0)

    def utcoffset(self, dt):
        return self.ZERO

    def dst(self, dt):
        return self.ZERO

    def tzname(self, dt):
        return 'UTC'


class Context(object):
    """Super simple class to call setattr on"""
    pass


def pack_string(obj):
    """Optimally pack a string according to msgpack format"""
    payload = str(obj).encode('ASCII')
    l = len(payload)
    if l < (2 ** 5):
        prefix = struct.pack('B', 0b10100000 | l)
    elif l < (2 ** 8):
        prefix = struct.pack('BB', 0xD9, l)
    elif l < (2 ** 16):
        prefix = struct.pack('>BH', 0xDA, l)
    else:
        prefix = struct.pack('>BI', 0xDB, l)
    return prefix + payload


def pack_bytes(payload):
    """Optimally pack a byte string according to msgpack format"""
    l = len(payload)
    if l < (2 ** 8):
        prefix = struct.pack('BB', 0xC4, l)
    elif l < (2 ** 16):
        prefix = struct.pack('>BH', 0xC5, l)
    else:
        prefix = struct.pack('>BI', 0xC6, l)
    return prefix + payload


class SendResponseTests(testing.AsyncHTTPTestCase):

    def get_app(self):
        return examples.make_application(debug=True)

    def test_that_content_type_default_works(self):
        response = self.fetch('/', method='POST', body='{}',
                              headers={'Content-Type': 'application/json'})
        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers['Content-Type'],
                         'application/json; charset="utf-8"')

    def test_that_missing_content_type_uses_default(self):
        response = self.fetch('/', method='POST', body='{}',
                              headers={'Accept': 'application/xml',
                                       'Content-Type': 'application/json'})
        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers['Content-Type'],
                         'application/json; charset="utf-8"')

    def test_that_accept_header_is_obeyed(self):
        response = self.fetch('/', method='POST', body='{}',
                              headers={'Accept': 'application/msgpack',
                                       'Content-Type': 'application/json'})
        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers['Content-Type'],
                         'application/msgpack')

    def test_that_default_content_type_is_set_on_response(self):
        response = self.fetch('/', method='POST', body=umsgpack.packb({}),
                              headers={'Content-Type': 'application/msgpack'})
        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers['Content-Type'],
                         'application/json; charset="utf-8"')


class GetRequestBodyTests(testing.AsyncHTTPTestCase):

    def get_app(self):
        return examples.make_application(debug=True)

    def test_that_request_with_unhandled_type_results_in_415(self):
        response = self.fetch(
            '/', method='POST', headers={'Content-Type': 'application/xml'},
            body=(u'<request><name>value</name>'
                  u'<embedded><utf8>\u2731</utf8></embedded>'
                  u'</request>').encode('utf-8'))
        self.assertEqual(response.code, 415)

    def test_that_msgpack_request_returns_default_type(self):
        body = {
            'name': 'value',
            'embedded': {
                'utf8': u'\u2731'
            }
        }
        response = self.fetch('/', method='POST', body=umsgpack.packb(body),
                              headers={'Content-Type': 'application/msgpack'})
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body.decode('utf-8')), body)


class JSONTranscoderTests(unittest.TestCase):

    def setUp(self):
        super(JSONTranscoderTests, self).setUp()
        self.transcoder = transcoders.JSONTranscoder()

    def test_that_uuids_are_dumped_as_strings(self):
        obj = {'id': uuid.uuid4()}
        dumped = self.transcoder.dumps(obj)
        self.assertEqual(dumped.replace(' ', ''), '{"id":"%s"}' % obj['id'])

    def test_that_datetimes_are_dumped_in_isoformat(self):
        obj = {'now': datetime.datetime.now()}
        dumped = self.transcoder.dumps(obj)
        self.assertEqual(dumped.replace(' ', ''),
                         '{"now":"%s"}' % obj['now'].isoformat())

    def test_that_tzaware_datetimes_include_tzoffset(self):
        obj = {'now': datetime.datetime.now().replace(tzinfo=UTC())}
        self.assertTrue(obj['now'].isoformat().endswith('+00:00'))
        dumped = self.transcoder.dumps(obj)
        self.assertEqual(dumped.replace(' ', ''),
                         '{"now":"%s"}' % obj['now'].isoformat())

    @unittest.skipIf(sys.version_info[0] == 2, 'bytes unsupported on python 2')
    def test_that_bytes_are_base64_encoded(self):
        bin = bytes(os.urandom(127))
        dumped = self.transcoder.dumps({'bin': bin})
        self.assertEqual(
            dumped, '{"bin":"%s"}' % base64.b64encode(bin).decode('ASCII'))

    def test_that_bytearrays_are_base64_encoded(self):
        bin = bytearray(os.urandom(127))
        dumped = self.transcoder.dumps({'bin': bin})
        self.assertEqual(
            dumped, '{"bin":"%s"}' % base64.b64encode(bin).decode('ASCII'))

    def test_that_memoryviews_are_base64_encoded(self):
        bin = memoryview(os.urandom(127))
        dumped = self.transcoder.dumps({'bin': bin})
        self.assertEqual(
            dumped, '{"bin":"%s"}' % base64.b64encode(bin).decode('ASCII'))

    def test_that_unhandled_objects_raise_type_error(self):
        with self.assertRaises(TypeError):
            self.transcoder.dumps(object())


class ContentSettingsTests(unittest.TestCase):

    def test_that_from_application_creates_instance(self):

        context = Context()
        settings = content.ContentSettings.from_application(context)
        self.assertIs(content.ContentSettings.from_application(context),
                      settings)

    def test_that_handler_listed_in_available_content_types(self):
        settings = content.ContentSettings()
        settings['application/json'] = object()
        self.assertEqual(len(settings.available_content_types), 1)
        self.assertEqual(settings.available_content_types[0].content_type,
                         'application')
        self.assertEqual(settings.available_content_types[0].content_subtype,
                         'json')

    def test_that_handler_is_not_overwritten(self):
        settings = content.ContentSettings()
        settings['application/json'] = handler = object()
        settings['application/json'] = object()
        self.assertIs(settings.get('application/json'), handler)


class ContentFunctionTests(unittest.TestCase):

    def setUp(self):
        super(ContentFunctionTests, self).setUp()
        self.context = Context()

    def test_that_add_binary_content_type_creates_binary_handler(self):
        content.add_binary_content_type(self.context,
                                        'application/vnd.python.pickle',
                                        pickle.dumps, pickle.loads)
        settings = content.ContentSettings.from_application(self.context)
        transcoder = settings['application/vnd.python.pickle']
        self.assertIsInstance(transcoder, handlers.BinaryContentHandler)
        self.assertIs(transcoder._pack, pickle.dumps)
        self.assertIs(transcoder._unpack, pickle.loads)

    def test_that_add_text_content_type_creates_text_handler(self):
        content.add_text_content_type(self.context, 'application/json', 'utf8',
                                      json.dumps, json.loads)
        settings = content.ContentSettings.from_application(self.context)
        transcoder = settings['application/json']
        self.assertIsInstance(transcoder, handlers.TextContentHandler)
        self.assertIs(transcoder._dumps, json.dumps)
        self.assertIs(transcoder._loads, json.loads)


class MsgPackTranscoderTests(unittest.TestCase):

    def setUp(self):
        super(MsgPackTranscoderTests, self).setUp()
        self.transcoder = transcoders.MsgPackTranscoder()

    def test_that_strings_are_dumped_as_strings(self):
        dumped = self.transcoder.packb(u'foo')
        self.assertEqual(self.transcoder.unpackb(dumped), 'foo')
        self.assertEqual(dumped, pack_string('foo'))

    def test_that_none_is_packed_as_nil_byte(self):
        self.assertEqual(self.transcoder.packb(None), b'\xC0')

    def test_that_bools_are_dumped_appropriately(self):
        self.assertEqual(self.transcoder.packb(False), b'\xC2')
        self.assertEqual(self.transcoder.packb(True), b'\xC3')

    def test_that_ints_are_packed_appropriately(self):
        self.assertEqual(self.transcoder.packb((2 ** 7) - 1), b'\x7F')
        self.assertEqual(self.transcoder.packb(2 ** 7), b'\xCC\x80')
        self.assertEqual(self.transcoder.packb(2 ** 8), b'\xCD\x01\x00')
        self.assertEqual(self.transcoder.packb(2 ** 16),
                         b'\xCE\x00\x01\x00\x00')
        self.assertEqual(self.transcoder.packb(2 ** 32),
                         b'\xCF\x00\x00\x00\x01\x00\x00\x00\x00')

    def test_that_negative_ints_are_packed_accordingly(self):
        self.assertEqual(self.transcoder.packb(-(2 ** 0)), b'\xFF')
        self.assertEqual(self.transcoder.packb(-(2 ** 5)), b'\xE0')
        self.assertEqual(self.transcoder.packb(-(2 ** 7)), b'\xD0\x80')
        self.assertEqual(self.transcoder.packb(-(2 ** 15)), b'\xD1\x80\x00')
        self.assertEqual(self.transcoder.packb(-(2 ** 31)),
                         b'\xD2\x80\x00\x00\x00')
        self.assertEqual(self.transcoder.packb(-(2 ** 63)),
                         b'\xD3\x80\x00\x00\x00\x00\x00\x00\x00')

    def test_that_lists_are_treated_as_arrays(self):
        dumped = self.transcoder.packb(list())
        self.assertEqual(self.transcoder.unpackb(dumped), [])
        self.assertEqual(dumped, b'\x90')

    def test_that_tuples_are_treated_as_arrays(self):
        dumped = self.transcoder.packb(tuple())
        self.assertEqual(self.transcoder.unpackb(dumped), [])
        self.assertEqual(dumped, b'\x90')

    def test_that_sets_are_treated_as_arrays(self):
        dumped = self.transcoder.packb(set())
        self.assertEqual(self.transcoder.unpackb(dumped), [])
        self.assertEqual(dumped, b'\x90')

    def test_that_unhandled_objects_raise_type_error(self):
        with self.assertRaises(TypeError):
            self.transcoder.packb(object())

    def test_that_uuids_are_dumped_as_strings(self):
        uid = uuid.uuid4()
        dumped = self.transcoder.packb(uid)
        self.assertEqual(self.transcoder.unpackb(dumped), str(uid))
        self.assertEqual(dumped, pack_string(uid))

    def test_that_datetimes_are_dumped_in_isoformat(self):
        now = datetime.datetime.now()
        dumped = self.transcoder.packb(now)
        self.assertEqual(self.transcoder.unpackb(dumped), now.isoformat())
        self.assertEqual(dumped, pack_string(now.isoformat()))

    def test_that_tzaware_datetimes_include_tzoffset(self):
        now = datetime.datetime.now().replace(tzinfo=UTC())
        self.assertTrue(now.isoformat().endswith('+00:00'))
        dumped = self.transcoder.packb(now)
        self.assertEqual(self.transcoder.unpackb(dumped), now.isoformat())
        self.assertEqual(dumped, pack_string(now.isoformat()))

    def test_that_bytes_are_sent_as_bytes(self):
        data = bytes(os.urandom(127))
        dumped = self.transcoder.packb(data)
        self.assertEqual(self.transcoder.unpackb(dumped), data)
        self.assertEqual(dumped, pack_bytes(data))

    def test_that_bytearrays_are_sent_as_bytes(self):
        data = bytearray(os.urandom(127))
        dumped = self.transcoder.packb(data)
        self.assertEqual(self.transcoder.unpackb(dumped), data)
        self.assertEqual(dumped, pack_bytes(data))

    def test_that_memoryviews_are_sent_as_bytes(self):
        data = memoryview(os.urandom(127))
        dumped = self.transcoder.packb(data)
        self.assertEqual(self.transcoder.unpackb(dumped), data)
        self.assertEqual(dumped, pack_bytes(data.tobytes()))
