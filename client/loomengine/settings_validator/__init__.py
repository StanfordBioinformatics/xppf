from .validator import SettingsValidator


def validate(settings):
    SettingsValidator(settings).validate()
