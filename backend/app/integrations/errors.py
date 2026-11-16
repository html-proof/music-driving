class ProviderError(Exception):
    """Base class for upstream music/lyrics provider failures."""


class ProviderNotFound(ProviderError):
    """The provider has no data for the requested resource."""


class ProviderInvalidRequest(ProviderNotFound):
    """The provider rejected the request itself (400/422), e.g. an id or query it does not
    accept. Handled like "not found" by callers, but never remembered as a miss: the item
    may well exist and be reachable with a valid request."""


class ProviderUnavailable(ProviderError):
    """The provider could not be reached or returned a server error."""
