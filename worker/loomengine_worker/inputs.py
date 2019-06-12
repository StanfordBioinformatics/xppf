import os


class BaseInput(object):

    def __init__(self, data_contents, channel, task_monitor):
        self.data_contents = data_contents
        self.export_manager = task_monitor.export_manager
        self.working_dir = task_monitor.working_dir
        self.channel = channel

    def _index_duplicate_filenames(self, filename, duplicate_filename_counters):
        # Increment filenames if there are duplicates,
        # e.g. file__0__.txt, file__1__.txt, file__2__.txt
        if filename in duplicate_filename_counters:
            counter = duplicate_filename_counters[filename]
            duplicate_filename_counters[filename] += 1
            filename = self._rename_duplicate(filename, counter)
        return filename

    def _rename_duplicate(self, filename, counter):
        parts = filename.split('.')
        assert len(parts) > 0, 'missing filename'
        if len(parts) == 1:
            return parts[0] + '__%s__' % counter
        else:
            return '.'.join(
                parts[0:len(parts)-1]) + '__%s__.' % counter + parts[-1]


class FileInput(BaseInput):

    def copy(self, duplicate_filename_counters):
        data_object = self.data_contents
        filename = self._index_duplicate_filenames(
            data_object['value']['filename'], duplicate_filename_counters)
        self.export_manager.export_file(
            data_object,
            destination_directory=self.working_dir,
            destination_filename=filename,
            retry=True)

    def get_filenames(self):
        return [self.data_contents['value']['filename']]


class FileListInput(BaseInput):

    def copy(self, duplicate_filename_counters):
        data_object_list = self.data_contents
        filename_array = [data_object['value']['filename']
                          for data_object in data_object_list]
        for data_object in data_object_list:
            filename = self._index_duplicate_filenames(
                data_object['value']['filename'], duplicate_filename_counters)
            self.export_manager.export_file(
                data_object,
                destination_directory=self.working_dir,
                destination_filename=filename,
                retry=True)

    def get_filenames(self):
        return [data_object['value']['filename'] for data_object in self.data_contents]


class NoOpInput(BaseInput):

    def copy(self, duplicate_filename_counters):
        return

    def get_filenames(self):
        return []

def _get_input_info(input):
    assert 'type' in input, 'invalid input: "type" is missing'
    assert 'mode' in input, 'invalid input: "mode" is missing'
    data_type = input['type']
    assert data_type in ['file', 'boolean', 'string', 'integer', 'float'], \
        'input has invalid type "%s"' % data_type
    mode = input['mode']
    assert mode == 'no_gather' or mode.startswith('gather'), \
        'input has invalid mode "%s"' % mode
    channel = input['channel']
    return (data_type, mode, channel)


def TaskAttemptInput(input, task_attempt):
    """Returns the correct Input class for a given
    data type and gather mode
    """

    (data_type, mode, channel) = _get_input_info(input)

    if data_type != 'file':
        return NoOpInput(None, channel, task_attempt)

    if mode == 'no_gather':
        return FileInput(input['data']['contents'], channel, task_attempt)
    else:
        assert mode.startswith('gather')
        return FileListInput(input['data']['contents'], channel, task_attempt)


class TaskAttemptInputs(object):

    def __init__(self, inputs, task_attempt):
        self.filename_counters = {} # filename: number of times seen
        self.inputs = [TaskAttemptInput(input, task_attempt) for input in inputs]
        # Inputs are sorted by channel name for consistent indexing of 
        # duplicate filenames, i.e. duplicatename__0__.ext, duplicatename__1__.ext. 
        # Indexing is applied in alphanumeric order of input channel names.
        self.inputs.sort(key=lambda i: i.channel)
        self.duplicate_filename_counters = self._get_duplicate_filename_counters()

    def _get_duplicate_filename_counters(self):
        counters = {}
        all_filenames = []
        for input in self.inputs:
            all_filenames.extend(input.get_filenames())
        for duplicate_filename in self._get_duplicates(all_filenames):
            counters[duplicate_filename] = 0
        return counters

    def _get_duplicates(self, array):
        seen = set()
        duplicates = set()
        for member in array:
            if member in seen:
                duplicates.add(member)
            seen.add(member)
        return duplicates

    def copy(self):
        for input in self.inputs:
            input.copy(self.duplicate_filename_counters)
