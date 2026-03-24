"""AWS Systems Manager Parameter Store client."""

import boto3

_SSM_CACHE: dict[str, str] = {}
_SSM_CLIENT = boto3.client("ssm")


def get_ssm_param(name: str) -> str:
    """Fetch an SSM parameter, caching across invocations."""
    if name not in _SSM_CACHE:
        response = _SSM_CLIENT.get_parameter(Name=name, WithDecryption=True)
        _SSM_CACHE[name] = response["Parameter"]["Value"]
    return _SSM_CACHE[name]
