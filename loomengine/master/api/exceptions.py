class Error(Exception):
    pass

class DataObjectValidationError(Error):
    pass

class UnknownNameFieldError(Error):
    pass

class IdTooShortError(Error):
    pass

class InvalidIdError(Error):
    pass

class MissingInputsError(Error):
    pass

class IdNotFoundError(Error):
    pass

class TooManyMatchesError(Error):
    pass

class ConcurrentModificationError(Exception):
    pass

class NoFileMatchError(Exception):
    pass

class MultipleFileMatchesError(Exception):
    pass

class NoTemplateMatchError(Exception):
    pass

class MultipleTemplateMatchesError(Exception):
    pass

class NoTemplateInputMatchError(Exception):
    pass

class ChannelNameCollisionError(Exception):
    pass

class SaveRetriesExceededError(Exception):
    pass
