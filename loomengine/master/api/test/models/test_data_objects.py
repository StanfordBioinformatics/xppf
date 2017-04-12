import os
from django.test import TestCase

from api.models.data_objects import *


class TestFileDataObject(TestCase):

    def setUp(self):
        self.filename = 'myfile.dat'
        self.filename_copy = 'myfile.dat_copy'
        self.filename2 = 'myfile2.dat'

        self.file = FileDataObject.objects.create(
            type='file',
            filename=self.filename,
            source_type='imported',
            file_import={'source_url': 'file:///data/'+self.filename,
                         'note': 'Test data'},
            md5='abcde'
        )
        # Same content, different name
        self.file_copy = FileDataObject.objects.create(
            type='file',
            filename=self.filename_copy,
            source_type='imported',
            file_import={
                'note': 'Test data',
                'source_url': 'file:///data/'+self.filename,
            },
            md5='abcde'
        )
        self.file2 = FileDataObject.objects.create(
            type='file',
            filename=self.filename2,
            source_type='imported',
            file_import={
                'note': 'Test data',
                'source_url': 'file:///data/'+self.filename2,
            },
            md5='fghij'
        )
        # Same content, same name
        self.file2_duplicate = FileDataObject.objects.create(
            type='file',
            filename=self.filename2,
            source_type='imported',
            file_import={
                'note': 'Test data',
                'source_url': 'file:///data/'+self.filename2,
            },
            md5='fghij'
        )

    def testGetByValue(self):
        file = DataObject.get_by_value(self.filename, 'file')
        self.assertEqual(file.filename, self.filename)

    def testGetByValueNoMatchError(self):
        with self.assertRaises(NoFileMatchError):
            file = DataObject.get_by_value('nonexistent_filename', 'file')

    def testGetByValueMultipleMatchesError(self):
        with self.assertRaises(MultipleFileMatchesError):
            file = DataObject.get_by_value(self.filename2, 'file')

    def testGetByValue_Name(self):
        matches = FileDataObject.filter_by_name_or_id_or_hash(self.filename)
        self.assertEqual(len(matches),1) 
        self.assertTrue(matches[0].filename, self.filename)

    def testGetByValue_ID(self):
        matches = FileDataObject.filter_by_name_or_id_or_hash(
            "@%s" % self.file.uuid)
        self.assertEqual(len(matches),1) 
        self.assertTrue(matches[0].filename, self.filename)

    def testGetByValue_Hash(self):
        matches = FileDataObject.filter_by_name_or_id_or_hash(
            "$%s" % self.file.md5)
        self.assertEqual(len(matches),2) 
        self.assertTrue(matches[0].filename, self.filename)

    def testGetByValue_NameHash(self):
        matches = FileDataObject.filter_by_name_or_id_or_hash(
            "%s$%s" % (self.filename, self.file.md5))
        self.assertEqual(len(matches),1) 
        self.assertTrue(matches[0].filename, self.filename)

    def testGetByValue_NameId(self):
        matches = FileDataObject.filter_by_name_or_id_or_hash(
            "%s@%s" % (self.filename, self.file.uuid))
        self.assertEqual(len(matches),1) 
        self.assertTrue(matches[0].filename, self.filename)

    def testGetByValue_HashId(self):
        matches = FileDataObject.filter_by_name_or_id_or_hash(
            "@%s$%s" % (self.file.uuid, self.file.md5))
        self.assertEqual(len(matches),1) 
        self.assertTrue(matches[0].filename, self.filename)

    def testGetByValue_NameHashId(self):
        query = "%s$%s@%s" % (self.filename, self.file.md5, self.file.uuid)
        
        matches = FileDataObject.filter_by_name_or_id_or_hash(
            "%s$%s@%s" % (self.filename, self.file.md5, self.file.uuid))
        self.assertEqual(len(matches),1) 
        self.assertTrue(matches[0].filename, self.filename)

    def testSubstitutionValue(self):
        self.assertEqual(self.file.substitution_value,
                         self.filename)

    def testIsReady(self):
        with self.settings(
                KEEP_DUPLICATE_FILES=True):
            self.file.initialize_file_resource()

        self.assertFalse(self.file.is_ready())
        self.file.file_resource.upload_status = 'complete'
        self.file.file_resource.save()
        file = DataObject.objects.get(uuid=self.file.uuid)
        self.assertTrue(file.is_ready())

    def testCreateIncompleteResourceForImportKeepDuplicateTrue(self):
        with self.settings(
                KEEP_DUPLICATE_FILES=True):
            self.file.initialize_file_resource()
            self.file_copy.initialize_file_resource()

        # Files should have separate resources, even if contents match
        self.assertNotEqual(self.file.file_resource.uuid,
                            self.file_copy.file_resource.uuid)

    def testCreateIncompleteResourceForImportKeepDuplicateFalseUploadIncomplete(self):
        with self.settings(
                KEEP_DUPLICATE_FILES=False):
            self.file.initialize_file_resource()
            self.file_copy.initialize_file_resource()

        # Files with matching content should not share a resource
        # unless upload is complete
        self.assertNotEqual(self.file.file_resource.id,
                            self.file_copy.file_resource.id)

    def testCreateIncompleteResourceForImportKeepDuplicateFalseUploadComplete(self):
        with self.settings(
                KEEP_DUPLICATE_FILES=False):
            self.file.initialize_file_resource()
            self.file.file_resource.upload_status = 'complete'
            self.file.file_resource.save()
            self.file_copy.initialize_file_resource()

        # Files with matching content should share a resource
        # provided upload on first resource was complete
        self.assertEqual(self.file.file_resource.uuid,
                         self.file_copy.file_resource.uuid)

    def testAddUrlPrefixLocal(self):
        path = '/my/path'
        with self.settings(
                LOOM_STORAGE_TYPE='LOCAL'):
            url = FileResource._add_url_prefix(path)
        self.assertEqual(url, 'file://'+path)

    def testAddUrlPrefixGoogleStorage(self):
        path = '/my/path'
        bucket_id = 'mybucket'
        with self.settings(
                LOOM_STORAGE_TYPE='GOOGLE_STORAGE',
                GOOGLE_STORAGE_BUCKET=bucket_id):
            url = FileResource._add_url_prefix(path)
        self.assertEqual(url, 'gs://'+bucket_id+path)

    def testAddUrlPrefixRelativePathError(self):
        path = 'relative/path'
        with self.settings(
                LOOM_STORAGE_TYPE='LOCAL'):
            with self.assertRaises(RelativePathError):
                FileResource._add_url_prefix(path)

    def testAddUrlPrefixInvalidServerTypeError(self):
        path = '/my/path'
        with self.settings(
                LOOM_STORAGE_TYPE='WRONG_VALUE'):
            with self.assertRaises(InvalidFileServerTypeError):
                FileResource._add_url_prefix(path)

    def testGetBrowseablePathForImportedFile(self):
        self.assertEqual(
            FileResource._get_browsable_path(self.file),
            'imported')

    def testGetFileRoot(self):
        file_root = '/mydata'
        with self.settings(
                LOOM_STORAGE_ROOT=file_root):
            self.assertEqual(FileResource._get_file_root(),
                             file_root)

    def testGetFileRootExpandUser(self):
        file_root = '~/mydata'
        with self.settings(
                LOOM_STORAGE_ROOT=file_root,
                LOOM_STORAGE_TYPE='LOCAL'):
            self.assertEqual(FileResource._get_file_root(),
                             os.path.expanduser(file_root))

    def testGetFileRootRelativeFileRootError(self):
        file_root = 'mydata'
        with self.settings(
                LOOM_STORAGE_ROOT=file_root):
            with self.assertRaises(RelativeFileRootError):
                FileResource._get_file_root()

    def testGetPathForImportDuplicatesAndReruns(self):
        file_root = '/mydata'
        with self.settings(
                KEEP_DUPLICATE_FILES=True,
                FORCE_RERUN=True,
                LOOM_STORAGE_ROOT = file_root
        ):
            
            path = FileResource._get_path_for_import(self.file)
            self.assertTrue(
                path.startswith(os.path.join(file_root, 'imported')))
            self.assertTrue(
                path.endswith('_%s_%s' % (str(self.file.uuid)[0:8],
                                          self.file.filename)))

    def testGetPathForImportDuplicatesNoReruns(self):
        file_root = '/mydata'
        with self.settings(
                KEEP_DUPLICATE_FILES=True,
                FORCE_RERUN=False,
                LOOM_STORAGE_ROOT = file_root
        ):
            
            path = FileResource._get_path_for_import(self.file)
            self.assertTrue(
                path.startswith(os.path.join(file_root, 'imported')))
            self.assertTrue(
                path.endswith('_%s_%s' % (str(self.file.uuid)[0:8],
                                          self.file.filename)))

    def testGetPathForImportNoDuplicates(self):
        file_root = '/mydata'
        with self.settings(
                KEEP_DUPLICATE_FILES=False,
                LOOM_STORAGE_ROOT = file_root,
        ):
            path = FileResource._get_path_for_import(self.file)
            self.assertEqual(
                path,
                os.path.join(file_root,
                             self.file.md5))


class TestBooleanDataObject(TestCase):

    value = True
    
    def testGetByValue(self):
        data_object = DataObject.get_by_value(self.value, 'boolean')
        self.assertEqual(data_object.value, self.value)

    def testSubstitutionValue(self):
        boolean_data_object = BooleanDataObject.objects.create(
            type='boolean', value=self.value)
        data_object = DataObject.objects.get(id=boolean_data_object.id)
        self.assertEqual(data_object.substitution_value, self.value)

    def testIsReady(self):
        boolean_data_object = BooleanDataObject.objects.create(
            type='boolean', value=self.value)
        data_object = DataObject.objects.get(id=boolean_data_object.id)
        self.assertTrue(data_object.is_ready())
        

class TestFloatDataObject(TestCase):

    value = 9.1

    def testGetByValue(self):
        data_object = DataObject.get_by_value(self.value, 'float')
        self.assertEqual(data_object.value, self.value)

    def testSubstitutionValue(self):
        float_data_object = FloatDataObject.objects.create(
            type='float', value=self.value)
        data_object = DataObject.objects.get(id=float_data_object.id)
        self.assertEqual(data_object.substitution_value, self.value)

    def testIsReady(self):
        float_data_object = FloatDataObject.objects.create(
            type='float', value=self.value)
        data_object = DataObject.objects.get(id=float_data_object.id)
        self.assertTrue(data_object.is_ready())


class TestIntegerDataObject(TestCase):

    value = 1000

    def testGetByValue(self):
        data_object = DataObject.get_by_value(self.value, 'integer')
        self.assertEqual(data_object.value, self.value)

    def testSubstitutionValue(self):
        integer_data_object = IntegerDataObject.objects.create(
            type='integer', value=self.value)
        data_object = DataObject.objects.get(id=integer_data_object.id)
        self.assertEqual(data_object.substitution_value, self.value)

    def testIsReady(self):
        integer_data_object = IntegerDataObject.objects.create(
            type='integer', value=self.value)
        data_object = DataObject.objects.get(id=integer_data_object.id)
        self.assertTrue(data_object.is_ready())


class TestStringDataObject(TestCase):

    value = 'sprocket'

    def testGetByValue(self):
        data_object = DataObject.get_by_value(self.value, 'string')
        self.assertEqual(data_object.value, self.value)

    def testSubstitutionValue(self):
        string_data_object = StringDataObject.objects.create(
            type='string', value=self.value)
        data_object = DataObject.objects.get(id=string_data_object.id)
        self.assertEqual(data_object.substitution_value, self.value)

    def testIsReady(self):
        string_data_object = StringDataObject.objects.create(
            type='string', value=self.value)
        data_object = DataObject.objects.get(id=string_data_object.id)
        self.assertTrue(data_object.is_ready())


class TestArrayDataObject(TestCase):

    def testSubstitutionValue(self):
        values = [1,2,3]
        data_object_list = [
            DataObject.get_by_value(i, 'integer')
            for i in values
        ]
        array_data_object = ArrayDataObject.create_from_list(
            data_object_list, 'integer')

        self.assertEqual(array_data_object.substitution_value, values)

    def testIsReady(self):
        values = [1,2,3]
        data_object_list = [
            DataObject.get_by_value(i, 'integer')
            for i in values
        ]
        array_data_object = ArrayDataObject.create_from_list(
            data_object_list, 'integer')
        self.assertTrue(array_data_object.is_ready())

    def testTypeMismatchError(self):
        data_object_list = [
            DataObject.get_by_value(3, 'integer'),
            DataObject.get_by_value(False, 'boolean')
        ]
        with self.assertRaises(TypeMismatchError):
            array_data_object = ArrayDataObject.create_from_list(
                data_object_list, 'integer')

    def testAddToArrayNonArrayError(self):
        member = DataObject.get_by_value(3, 'integer')
        non_array = DataObject.get_by_value(4, 'integer')
        with self.assertRaises(NonArrayError):
            member.add_to_array(non_array)
        
    def testAddToArrayNestedArraysError(self):
        array1 = DataObject.objects.create(
            type='integer',
            is_array=True
        )
        array2 = DataObject.objects.create(
            type='integer',
            is_array=True
        )
        with self.assertRaises(NestedArraysError):
            array1.add_to_array(array2)

    def testCreateFromListNestedArraysError(self):
        list1 = [
            DataObject.get_by_value(3, 'integer'),
            DataObject.get_by_value(5, 'integer')
        ]
        array1 = ArrayDataObject.create_from_list(
            list1, 'integer')

        list2=[
            DataObject.get_by_value(7, 'integer'),
            array1
        ]
        with self.assertRaises(NestedArraysError):
            array2 = ArrayDataObject.create_from_list(
                list2, 'integer')
