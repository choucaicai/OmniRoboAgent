class OmniRoboAgentError(Exception):
    """Base error for expected framework failures."""


class BackendError(OmniRoboAgentError):
    pass


class ConfigError(OmniRoboAgentError):
    pass


class EnvironmentError(OmniRoboAgentError):
    pass


class PlannerOutputError(OmniRoboAgentError):
    pass


class VerifierOutputError(OmniRoboAgentError):
    pass
