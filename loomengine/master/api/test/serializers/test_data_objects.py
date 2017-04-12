import copy
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from rest_framework import serializers

from . import fixtures, get_mock_context
from api.serializers.data_objects import *


class TestStringDataObjectSerializer(TestCase):

    def testCreate(self):
        s = StringDataObjectSerializer(
            data=fixtures.data_objects.string_data_object)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.value,
            fixtures.data_objects.string_data_object['value'])

    def testUpdate(self):
        s = StringDataObjectSerializer(
            data=fixtures.data_objects.string_data_object)
        s.is_valid(raise_exception=True)
        m = s.save()

        new_value = 'new value'
        s2 = StringDataObjectSerializer(
            m, data={'value': new_value}, partial=True)
        s2.is_valid(raise_exception=True)
        m2 = s2.save()
        self.assertEqual(m2.value, new_value)

    def testNegCreateWithDuplicateID(self):
        data = copy.deepcopy(fixtures.data_objects.string_data_object)

        s1 = StringDataObjectSerializer(data=data)
        s1.is_valid(raise_exception=True)
        m1 = s1.save()

        data.update({'uuid': m1.uuid})
        s2 = StringDataObjectSerializer(data=data)
        s2.is_valid(raise_exception=True)
        with self.assertRaises(ValidationError):
            m2 = s2.save()

    def testNegCreateWithBadData(self):
        for baddata in [
            {'value': 'x'}, # missing type
            {'type': 'string'} # missing value
            ]:
            s = StringDataObjectSerializer(data=baddata)
            self.assertFalse(s.is_valid())


class TestBooleanDataObjectSerializer(TestCase):

    def testCreate(self):
        s = BooleanDataObjectSerializer(
            data=fixtures.data_objects.boolean_data_object)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.value,
            fixtures.data_objects.boolean_data_object['value'])


class TestIntegerDataObjectSerializer(TestCase):

    def testCreate(self):
        s = IntegerDataObjectSerializer(
            data=fixtures.data_objects.integer_data_object)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.value,
            fixtures.data_objects.integer_data_object['value'])


class TestFloatDataObjectSerializer(TestCase):

    def testCreate(self):
        s = FloatDataObjectSerializer(
            data=fixtures.data_objects.float_data_object)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.value,
            fixtures.data_objects.float_data_object['value'])

class TestArrayDataObjectSerializer(TestCase):

    def testCreateArray(self):
        s = ArrayDataObjectSerializer(
            data=fixtures.data_objects.string_data_object_array)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.prefetch_members.count(),
            len(fixtures.data_objects.string_data_object_array['members'])
            )

    def testUpdate(self):
        pass

    def testValidate(self):
        pass


class TestDataObjectSerializer(TestCase):

    def testCreateStringDataObject(self):
        s = StringDataObjectSerializer(
            data=fixtures.data_objects.string_data_object)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.value,
            fixtures.data_objects.string_data_object['value'])

    def testNegCreateWithBadData(self):
        for baddata in [
            {'value': 'x'}, # missing type
            {'type': 'string'} # missing value
            ]:
            s = DataObjectSerializer(data=baddata)
            self.assertFalse(s.is_valid())

    def testCreateArray(self):
        s = DataObjectSerializer(
            data=fixtures.data_objects.string_data_object_array)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.prefetch_members.count(),
            len(fixtures.data_objects.string_data_object_array['members'])
        )

    def testGetDataFromModel(self):
        s1 = FileDataObjectSerializer(
            data=fixtures.data_objects.file_data_object)
        s1.is_valid(raise_exception=True)
        m = s1.save()

        s2 = DataObjectSerializer(m, context=get_mock_context())
        d = s2.data
        self.assertEqual(
            d['md5'],
            fixtures.data_objects.file_data_object['md5'])

    def testGetDataFromData(self):
        s = FileDataObjectSerializer(data=fixtures.data_objects.file_data_object,
                                     context=get_mock_context())
        s.is_valid(raise_exception=True)
        s.save()
        d = s.data
        self.assertEqual(
            d['md5'],
            fixtures.data_objects.file_data_object['md5'])

        
    
class TestFileResourceSerializer(TestCase):

    def testCreate(self):
        s = FileResourceSerializer(data=fixtures.data_objects.file_resource)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(m.file_url,
                         fixtures.data_objects.file_resource['file_url'])


class TestFileDataObjectSerializer(TestCase):
    
    def testCreate(self):
        s = FileDataObjectSerializer(
            data=fixtures.data_objects.file_data_object)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.filename,
            fixtures.data_objects.file_data_object['filename'])

    def testRender(self):
        s = FileDataObjectSerializer(
            data=fixtures.data_objects.file_data_object)
        s.is_valid(raise_exception=True)
        m = s.save()

        do = DataObject.objects.get(id=m.id)
        s2 = DataObjectSerializer(do, context=get_mock_context())
        self.assertEqual(s2.data['filename'],
                         fixtures.data_objects.file_data_object['filename'])
