"""Legacy import path. This name is the very same module object as
app.infrastructure.persistence.orm_models, so code and tests that import or patch it keep working until
they move to the new location."""
import sys

from app.infrastructure.persistence import orm_models as _module

sys.modules[__name__] = _module
