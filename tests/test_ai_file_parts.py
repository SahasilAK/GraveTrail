

from dataforge.ai_context import SourceSnapshot


def source(code, extension='.sql'):
    return SourceSnapshot('file', 'hash', 'query' + extension, extension, 'job', code, extension[1:])
