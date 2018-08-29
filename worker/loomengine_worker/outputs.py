import glob
import os
from loomengine_worker.parsers import OutputParser


class BaseOutput(object):

    def __init__(self, output, task_monitor):
        self.output = output
        self.connection = task_monitor.connection
        self.import_manager = task_monitor.import_manager
        self.working_dir = task_monitor.working_dir
        self.task_monitor = task_monitor


class FileOutput(BaseOutput):

    def save(self):
        filename = self.output['source']['filename']
        file_path = os.path.join(
            self.working_dir, filename)
        self.import_manager.import_result_file(
            self.output, file_path, retry=True)


class FileListScatterOutput(BaseOutput):

    def save(self):
        filename_list = self.output['source']['filenames']
        file_path_list = [
            os.path.join(
                self.working_dir, filename)
            for filename in filename_list]
        self.import_manager.import_result_file_list(
            self.output, file_path_list, retry=True)


class FileContentsOutput(BaseOutput):

    def save(self):
        filename = self.output['source']['filename']
        text = self._read_file(filename)
        self.output.update({'data': {'contents': text}})
        self.connection.update_task_attempt_output(
            self.output['uuid'],
            self.output)

    def _read_file(self, filename):
        file_path = os.path.join(
            self.working_dir, filename)
        with open(file_path, 'r') as f:
            text = f.read()
        return text


class FileContentsScatterOutput(FileContentsOutput):

    def save(self):
        filename = self.output['source']['filename']
        parser = OutputParser(self.output)
        text = self._read_file(filename)
        contents_list = parser.parse(text)
        self.output.update({'data': {'contents': contents_list}})
        self.connection.update_task_attempt_output(
            self.output['uuid'],
            self.output)


class FileListContentsScatterOutput(FileContentsOutput):

    def save(self):
        filename_list = self.output['source']['filenames']
        if not isinstance(filename_list, list):
            filename_list = filename_list.split(' ')
        contents_list = []
        for filename in filename_list:
            file_path = os.path.join(
                self.working_dir, filename)
            contents_list.append(self._read_file(file_path))
        self.output.update({'data': {'contents': contents_list}})
        self.connection.update_task_attempt_output(
            self.output['uuid'],
            self.output)


class StreamOutput(BaseOutput):

    def save(self):
        stream = self.output['source']['stream']
        assert stream in ['stdout', 'stderr']
        if self.output['source']['stream'] == 'stdout':
            text = self._get_stdout()
        else:
            text = self._get_stderr()
        self.output.update({'data': {'contents': text}})
        self.connection.update_task_attempt_output(
            self.output['uuid'],
            self.output)

    def _get_stdout(self):
        return self.task_monitor._get_stdout()

    def _get_stderr(self):
        return self.task_monitor._get_stderr()


class StreamScatterOutput(StreamOutput):

    def save(self):
        parser = OutputParser(self.output)
        stream = self.output['source']['stream']
        assert stream in ['stdout', 'stderr']
        if self.output['source']['stream'] == 'stdout':
            text = self._get_stdout()
        else:
            text = self._get_stderr()
        parser = OutputParser(self.output)
        contents_list = parser.parse(text)
        self.output.update({'data': {'contents': contents_list}})
        self.connection.update_task_attempt_output(
            self.output['uuid'],
            self.output)


class GlobScatterOutput(BaseOutput):

    def save(self):
        globstring = os.path.join(
            self.working_dir,
            self.output['source']['glob'])
        file_path_list = glob.glob(globstring)
        self.import_manager.import_result_file_list(
            self.output, file_path_list, retry=True)


class GlobContentsScatterOutput(FileContentsOutput):

    def save(self):
        globstring = os.path.join(
            self.working_dir,
            self.output['source']['glob'])
        file_path_list = glob.glob(globstring)
        contents_list = []
        for file_path in file_path_list:
            contents_list.append(self._read_file(file_path))
        self.output.update({'data': {'contents': contents_list}})
        self.connection.update_task_attempt_output(
            self.output['uuid'],
            self.output)


def _get_output_info(output):
    assert 'type' in output, 'invalid output: "type" is missing'
    assert 'mode' in output, 'invalid output: "mode" is missing'
    assert 'source' in output, 'invalid output: "source" is missing'
    data_type = output['type']
    assert data_type in ['file', 'boolean', 'string', 'integer', 'float'], \
        'output has invalid type "%s"' % data_type
    mode = output['mode']
    assert mode in ['scatter', 'no_scatter'], \
        'output has invalid mode "%s"' % mode
    filename_source = output['source'].get('filename')
    filename_list_source = output['source'].get('filenames')
    glob_source = output['source'].get('glob')
    stream_source = output['source'].get('stream')
    assert sum([bool(filename_source), bool(glob_source),
                bool(stream_source), bool(filename_list_source)]) == 1, \
        'exactly one type of source is required: "%s"' \
        % output['source']
    if glob_source:
        source_type = 'glob'
    elif stream_source:
        source_type = 'stream'
    elif filename_source:
        source_type = 'filename'
    elif filename_list_source:
        source_type = 'filenames'
    return (data_type, mode, source_type)


def TaskAttemptOutput(output, task_attempt):
    """Returns the correct Output class for a given
    data type, source type, and scatter mode
    """

    (data_type, mode, source_type) = _get_output_info(output)

    if data_type == 'file':
        if mode == 'scatter':
            assert source_type in ['filenames', 'glob'], \
                'source type "%s" not allowed' % source_type
            if source_type == 'filenames':
                return FileListScatterOutput(output, task_attempt)
            return GlobScatterOutput(output, task_attempt)
        else:
            assert mode == 'no_scatter'
            assert source_type == 'filename', \
                'source type "%s" not allowed' % source_type
            return FileOutput(output, task_attempt)
    else:  # data_type is non-file
        if mode == 'scatter':
            assert source_type in [
                'filename', 'filenames', 'glob', 'stream'], \
                'source type "%s" not allowed' % source_type
            if source_type == 'filename':
                return FileContentsScatterOutput(output, task_attempt)
            if source_type == 'filenames':
                return FileListContentsScatterOutput(output, task_attempt)
            if source_type == 'glob':
                return GlobContentsScatterOutput(output, task_attempt)
            assert source_type == 'stream'
            return StreamScatterOutput(output, task_attempt)
        else:
            assert mode == 'no_scatter'
            assert source_type in ['filename', 'stream'], \
                'source type "%s" not allowed' % source_type
            if source_type == 'filename':
                return FileContentsOutput(output, task_attempt)
            assert source_type == 'stream'
            return StreamOutput(output, task_attempt)
