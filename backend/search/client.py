from opensearchpy import OpenSearch

from config.settings import settings


def get_client() -> OpenSearch:
    kwargs = {
        "hosts": settings.opensearch_hosts,
        "use_ssl": settings.opensearch_use_ssl,
        "verify_certs": settings.opensearch_verify_certs,
        "timeout": settings.opensearch_timeout_seconds,
        "max_retries": settings.opensearch_max_retries,
        "retry_on_timeout": True,
        "pool_maxsize": settings.opensearch_pool_maxsize,
    }
    if settings.opensearch_username and settings.opensearch_password:
        kwargs["http_auth"] = (settings.opensearch_username, settings.opensearch_password)
    return OpenSearch(**kwargs)
