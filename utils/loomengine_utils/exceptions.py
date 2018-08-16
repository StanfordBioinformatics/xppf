class LoomengineUtilsError(Exception):
    pass

class APIError(LoomengineUtilsError):
    pass

class ServerConnectionError(LoomengineUtilsError):
    pass

class ServerConnectionHttpError(ServerConnectionError):
    pass

class ResourceCountError(LoomengineUtilsError):
    pass

class ExportManagerError(LoomengineUtilsError):
    pass

class FileAlreadyExistsError(ExportManagerError):
    pass

class FileUtilsError(LoomengineUtilsError):
    pass

class Md5ValidationError(FileUtilsError):
    pass

class UrlValidationError(FileUtilsError):
    pass

class InvalidYamlError(FileUtilsError):
    pass

class NoFileError(FileUtilsError):
    pass

class ImportManagerError(LoomengineUtilsError):
    pass

class FileDuplicateError(ImportManagerError):
    pass
