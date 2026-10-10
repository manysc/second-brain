"""Legacy import path. This name is the very same module object as
app.infrastructure.external_services.s3_storage, so code and tests that import or patch it keep working until
they move to the new location."""
import sys

from app.infrastructure.external_services import s3_storage as _module

sys.modules[__name__] = _module
