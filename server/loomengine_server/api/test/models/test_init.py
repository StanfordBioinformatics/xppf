from collections import OrderedDict
from django.test import TestCase
import hashlib
import json

from api.models import render_from_template, render_string_or_list, \
    calculate_contents_fingerprint


class TestRenderFromTemplate(TestCase):

    def testRenderFromTemplate(self):
        raw_text = 'My name is {{name}}'
        context = {'name': 'Inigo'}
        rendered_text = render_from_template(raw_text, context)
        self.assertEqual(rendered_text, 'My name is Inigo')


class TestRenderFromStringOrList(TestCase):

    def testString(self):
        raw_text = 'Name: {{ name }}'
        context = {'name': 'Inigo'}
        rendered_text = render_string_or_list(raw_text, context)
        self.assertEqual(rendered_text, 'Name: Inigo')

    def testList(self):
        raw_text = ['Name: {{ name }}', 'Nome: {{ name }}', 'Nombre: {{ name }}',]
        context = {'name': 'Inigo'}
        rendered_text = render_string_or_list(raw_text, context)
        self.assertEqual(rendered_text, ['Name: Inigo', 'Nome: Inigo', 'Nombre: Inigo'])


class TestCalculateContentsFingerprint(TestCase):

    def testString(self):
        value = 'help'
        self.assertEqual(calculate_contents_fingerprint(value),
                        hashlib.md5(value).hexdigest())

    def testNonstring(self):
        value = 1
        self.assertEqual(calculate_contents_fingerprint(value),
                        hashlib.md5(str(value)).hexdigest())
        
    def testList(self):
        list_value = [1, 2, 3]
        list_with_items_hashed = [hashlib.md5(str(item)).hexdigest()
                                  for item in list_value]
        list_string = json.dumps(list_with_items_hashed, separators=(',',':'))
        self.assertEqual(
            calculate_contents_fingerprint(list_value),
            hashlib.md5(list_string).hexdigest())

    def testListOrderNotPreserved(self):
        list1_value = [1,2,3]
        list2_value = [2,1,3]
        self.assertEqual(calculate_contents_fingerprint(list1_value),
                         calculate_contents_fingerprint(list2_value))

    def testDict(self):
        dict_value = {'a': True, 'b': False, 'c': True}
        dict_with_items_hashed = OrderedDict(sorted(
            [(key, calculate_contents_fingerprint(value))
             for key, value in dict_value.items()]
        ))
        sorted_dict_string = json.dumps(dict_with_items_hashed,
                                        sort_keys=True, separators=(',',':'))
        self.assertEqual(calculate_contents_fingerprint(dict_value),
                         hashlib.md5(sorted_dict_string).hexdigest())

    def testDictOrderNotPreserved(self):
        dict1_value = {'a': True, 'b': False, 'c': True}
        dict2_value = {'b': False, 'a': True, 'c': True}
        self.assertEqual(calculate_contents_fingerprint(dict1_value),
                         calculate_contents_fingerprint(dict2_value))

    def testRecursiveWithDict(self):
        filename = 'zebras.jpg'
        md5 = 'adc123'
        file_resource = {'filename': filename, 'md5': md5}
        file_resource_string = json.dumps(
            OrderedDict(
                [('filename', calculate_contents_fingerprint('zebras.jpg')),
                 ('md5', calculate_contents_fingerprint(md5))]),
            separators=(',',':'))
        dict1_value = {'type': 'file', 'value': file_resource}
        dict2_value = {'type': 'file',
                       'value': file_resource_string}
        self.assertEqual(calculate_contents_fingerprint(dict1_value),
                         calculate_contents_fingerprint(dict2_value))
