"""IBM watsonx.ai provider.

Uses IBM Cloud API key -> IAM access token -> watsonx.ai chat API.
"""

from __future__ import annotations

import time

import httpx

from app.ai.providers.base import (
    ChatMessage,
    CompletionResult,
    LLMProvider,
    ProviderError,
    ProviderNotConfiguredError,
)
from app.core.config import settings


class IBMWatsonXProvider(LLMProvider):
    name = "ibm"

    _token: str | None = None
    _token_expires_at: float = 0.0

    def _api_key(self) -> str | None:
        return settings.ai_watsonx_api_key

    def _project_id(self) -> str | None:
        return settings.ai_watsonx_project_id

    def is_configured(self) -> bool:
        return bool(
            self._api_key()
            and self._project_id()
            and settings.ai_watsonx_url
        )

    def _get_iam_token(
        self,
        timeout_seconds: float,
    ) -> str:

        # Reuse token until shortly before expiry.
        if (
            self._token
            and time.time()
            < self._token_expires_at - 60
        ):
            return self._token

        api_key = self._api_key()

        if not api_key:
            raise ProviderNotConfiguredError(
                self.name,
                "AI_WATSONX_API_KEY is not set",
            )

        try:
            response = httpx.post(
                "https://iam.cloud.ibm.com/identity/token",
                headers={
                    "Content-Type": (
                        "application/x-www-form-urlencoded"
                    ),
                    "Accept": "application/json",
                },
                data={
                    "grant_type": (
                        "urn:ibm:params:oauth:"
                        "grant-type:apikey"
                    ),
                    "apikey": api_key,
                },
                timeout=timeout_seconds,
            )

            response.raise_for_status()

            data = response.json()

            token = data.get(
                "access_token"
            )

            if not token:
                raise ProviderError(
                    self.name,
                    "IBM IAM response did not contain access_token",
                )

            expires_in = int(
                data.get(
                    "expires_in",
                    3600,
                )
            )

            self._token = token

            self._token_expires_at = (
                time.time()
                + max(
                    60,
                    expires_in,
                )
            )

            return token

        except ProviderError:
            raise

        except httpx.HTTPStatusError as exc:

            try:
                detail = exc.response.json()
            except Exception:
                detail = exc.response.text

            raise ProviderError(
                self.name,
                (
                    "IBM IAM token HTTP "
                    f"{exc.response.status_code}: "
                    f"{detail}"
                ),
            ) from exc

        except (
            httpx.TimeoutException,
            httpx.RequestError,
        ) as exc:

            raise ProviderError(
                self.name,
                f"IBM IAM network error: {exc}",
            ) from exc

        except Exception as exc:

            raise ProviderError(
                self.name,
                f"IBM IAM token error: {exc}",
            ) from exc

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
    ) -> CompletionResult:

        if not self.is_configured():

            raise ProviderNotConfiguredError(
                self.name,
                (
                    "IBM watsonx is not configured. "
                    "Set AI_WATSONX_API_KEY, "
                    "AI_WATSONX_PROJECT_ID and "
                    "AI_WATSONX_URL."
                ),
            )

        token = self._get_iam_token(
            timeout_seconds
        )

        base_url = (
            settings.ai_watsonx_url
            .rstrip("/")
        )

        api_version = (
            settings.ai_watsonx_api_version
        )

        url = (
            f"{base_url}/ml/v1/text/chat"
            f"?version={api_version}"
        )

        # watsonx text/chat accepts the normal chat roles.
        ibm_messages = []

        for message in messages:

            role = message.role

            if role not in {
                "system",
                "user",
                "assistant",
            }:
                role = "user"

            ibm_messages.append(
                {
                    "role": role,
                    "content": message.content,
                }
            )

        payload = {
            "messages": ibm_messages,
            "project_id": (
                settings.ai_watsonx_project_id
            ),
            "model_id": model,
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
        }

        try:

            response = httpx.post(
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": (
                        "application/json"
                    ),
                    "Authorization": (
                        f"Bearer {token}"
                    ),
                },
                json=payload,
                timeout=timeout_seconds,
            )

            # Token may have expired/revoked.
            # Refresh once and retry the request.
            if response.status_code == 401:

                self._token = None
                self._token_expires_at = 0.0

                token = self._get_iam_token(
                    timeout_seconds
                )

                response = httpx.post(
                    url,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": (
                            "application/json"
                        ),
                        "Authorization": (
                            f"Bearer {token}"
                        ),
                    },
                    json=payload,
                    timeout=timeout_seconds,
                )

            response.raise_for_status()

            data = response.json()

            # ----------------------------------------------------------
            # Current watsonx text/chat response
            # ----------------------------------------------------------

            text = ""

            choices = data.get(
                "choices"
            )

            if choices:

                message = (
                    choices[0]
                    .get("message", {})
                )

                text = (
                    message.get(
                        "content"
                    )
                    or ""
                )

                if isinstance(
                    text,
                    list,
                ):

                    text = "".join(
                        part.get(
                            "text",
                            "",
                        )
                        for part in text
                        if isinstance(
                            part,
                            dict,
                        )
                    )

            # ----------------------------------------------------------
            # Defensive fallback for result-style responses
            # ----------------------------------------------------------

            if not text:

                results = data.get(
                    "results"
                )

                if results:

                    text = (
                        results[0]
                        .get(
                            "generated_text",
                            "",
                        )
                    )

            if not text.strip():

                raise ProviderError(
                    self.name,
                    (
                        "IBM watsonx returned "
                        "an empty response"
                    ),
                )

            usage = (
                data.get("usage")
                or {}
            )

            prompt_tokens = (
                usage.get(
                    "prompt_tokens",
                    usage.get(
                        "input_tokens",
                        0,
                    ),
                )
                or 0
            )

            completion_tokens = (
                usage.get(
                    "completion_tokens",
                    usage.get(
                        "output_tokens",
                        0,
                    ),
                )
                or 0
            )

            return CompletionResult(
                text=str(text),
                provider=self.name,
                model=model,
                prompt_tokens=int(
                    prompt_tokens
                ),
                completion_tokens=int(
                    completion_tokens
                ),
                finish_reason=(
                    (
                        choices[0]
                        .get(
                            "finish_reason"
                        )
                        if choices
                        else None
                    )
                ),
                raw=data,
            )

        except ProviderError:
            raise

        except httpx.HTTPStatusError as exc:

            try:
                detail = exc.response.json()
            except Exception:
                detail = exc.response.text

            raise ProviderError(
                self.name,
                (
                    "IBM watsonx API HTTP "
                    f"{exc.response.status_code}: "
                    f"{detail}"
                ),
            ) from exc

        except (
            httpx.TimeoutException,
            httpx.RequestError,
        ) as exc:

            raise ProviderError(
                self.name,
                (
                    "IBM watsonx network "
                    f"error: {exc}"
                ),
            ) from exc

        except Exception as exc:

            raise ProviderError(
                self.name,
                str(exc),
            ) from exc