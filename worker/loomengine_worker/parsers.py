class DelimitedParser(object):

    def __init__(self, options):
        assert options.get('delimiter') is not None, \
            'required field "delimiter" is missing from parser'
        if options.get('delimiter') is None:
            raise Exception('delimiter is a required option field in a parser '
                            'with type "delimited"')
        self.delimiter = options.get('delimiter', ' ')
        self.trim = options.get('trim', False)

    def parse(self, text):
        if self.trim:
            text = text.strip()
        text_array = text.split(self.delimiter)
        if self.trim:
            text_array = [item.strip() for item in text_array]
        return text_array


def _get_parser_info(output):
    assert output.get('parser'), 'invalid output: "parser" is missing'
    parser_type = output['parser'].get('type')
    assert parser_type == 'delimited', 'invalid parser type "%s"' % parser_type
    options = output['parser'].get('options', {})
    return (parser_type, options)


def OutputParser(output):
    (parser_type, options) = _get_parser_info(output)
    assert parser_type == 'delimited', 'invalid parser type %s' % parser_type
    return DelimitedParser(options)
