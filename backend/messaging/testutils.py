import pathlib
import tempfile
from unittest.mock import patch

# smallest valid PNG header + padding: enough for the code under test, which only uploads the bytes
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'0' * 64


class ReplyImageMixin:
    """Points the demo button-reply image at a temporary file.

    The real asset (backend/media/image.png) is not part of the repository, so tests must not depend
    on it: otherwise they fail on a clean checkout (for example in CI).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        folder = cls.enterClassContext(tempfile.TemporaryDirectory())
        image = pathlib.Path(folder) / 'image.png'
        image.write_bytes(PNG_BYTES)
        cls.enterClassContext(patch('messaging.services.REPLY_IMAGE_PATH', image))
