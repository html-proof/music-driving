class ProviderError(Exception):
    """Base class for upstream music/lyrics provider failures."""


class ProviderNotFound(ProviderError):
    """The provider has no data for the requested resource."""


class ProviderUnavailable(ProviderError):
    """The provider could not be reached or returned a server error."""
