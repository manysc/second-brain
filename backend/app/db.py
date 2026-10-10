"""Legacy import path. This name is the very same module object as
app.infrastructure.persistence.database, so code and tests that import or patch it keep working until
they move to the new location."""
import sys

from app.infrastructure.persistence import database as _module

sys.modules[__name__] = _module
