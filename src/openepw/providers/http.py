import json
import ssl
import time

import httpx
import truststore

from ..config import RuntimeConfig
from ..models import OpenEPWError


class HttpClient:
    def __init__(self, config: RuntimeConfig, *, transport=None, sleep=time.sleep):
        self.config = config
        self.sleep = sleep
        self.client = httpx.Client(
            timeout=config.timeout,
            transport=transport,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            follow_redirects=False,
            headers={"User-Agent": "openepw/0.1"},
        )

    def request(self, method, url, *, params=None, headers=None, json_body=None, limit=None):
        for attempt in range(self.config.retries + 1):
            try:
                with self.client.stream(
                    method, url, params=params, headers=headers, json=json_body
                ) as response:
                    status = response.status_code
                    if status in (429, 500, 502, 503, 504) and attempt < self.config.retries:
                        retry = response.headers.get("Retry-After", "")
                        self.sleep(min(float(retry) if retry.isdigit() else 2**attempt, 30))
                        continue
                    if not 200 <= status < 300:
                        code = (
                            "AUTH_REQUIRED"
                            if status == 401
                            else "TERMS_REQUIRED"
                            if status == 403
                            else "RATE_LIMITED"
                            if status == 429
                            else "PROVIDER_UNAVAILABLE"
                        )
                        raise OpenEPWError(
                            code,
                            f"Provider returned HTTP {status}",
                            retryable=status >= 500 or status == 429,
                        )
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > (limit or self.config.max_response_bytes):
                            raise OpenEPWError(
                                "RESOURCE_LIMIT", "Provider response exceeds configured byte limit"
                            )
                        chunks.append(chunk)
                    return b"".join(chunks), dict(response.headers), status
            except httpx.HTTPError:
                if attempt == self.config.retries:
                    raise OpenEPWError(
                        "PROVIDER_UNAVAILABLE",
                        "Provider transport failed; credentials and request URL suppressed",
                        retryable=True,
                    ) from None
                self.sleep(2**attempt)
        raise OpenEPWError("PROVIDER_UNAVAILABLE", "Provider request exhausted retries")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)[0]

    def get_json(self, url, **kwargs):
        try:
            return json.loads(self.get(url, **kwargs))
        except (ValueError, TypeError):
            raise OpenEPWError("MALFORMED_RESPONSE", "Provider returned invalid JSON") from None

    def close(self):
        self.client.close()
