"""OpenRouter LLM провайдер."""

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional, TypeVar

import httpx
from pydantic import BaseModel

# Generic type for structured output
T = TypeVar("T", bound=BaseModel)
from rich.console import Console
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class LLMUsageStats:
    """Statistics for LLM usage tracking."""
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_time_seconds: float = 0.0
    total_cost_usd: float = 0.0
    
    def add_call(self, prompt_tokens: int, completion_tokens: int, time_seconds: float, cost_usd: float = 0.0):
        """Record a single LLM call."""
        self.total_calls += 1
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_time_seconds += time_seconds
        self.total_cost_usd += cost_usd
    
    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens
    
    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"LLM Stats: {self.total_calls} calls, "
            f"{self.total_tokens:,} tokens ({self.total_prompt_tokens:,}+{self.total_completion_tokens:,}), "
            f"{self.total_time_seconds:.1f}s total, "
            f"${self.total_cost_usd:.4f}"
        )


class OpenRouterRetryableError(Exception):
    """Transient error that should trigger retry."""
    pass


class OpenRouterProvider(BaseLLMProvider):
    """Провайдер для OpenRouter API."""

    BASE_URL = "https://openrouter.ai/api/v1"

    # Настройки для разных моделей
    MODEL_CONFIGS = {
        "openai/gpt-4o-mini": {
            "temperature": 0.0,
            "max_tokens": 16384,
        },
        "openai/gpt-oss-20b": {
            "temperature": 0.0,
            "max_tokens": 8192,
        },
        "openai/gpt-oss-120b": {
            "temperature": 0.0,
            "max_tokens": 8192,
        },
    }

    # Дефолтная конфигурация для неизвестных моделей
    DEFAULT_CONFIG = {
        "temperature": 0.0,
        "max_tokens": 8192,
    }

    # Retry settings (used by tenacity decorator)
    MAX_RETRIES = 3
    
    # Errors that indicate transient provider issues (should retry)
    TRANSIENT_ERROR_PATTERNS = [
        "provider returned error",
        "rate limit",
        "overloaded",
        "capacity",
        "temporarily unavailable",
        "service unavailable",
        "internal server error",  # 500 errors
        "502", "503", "504",  # Gateway errors
    ]
    
    # Популярные провайдеры OpenRouter (актуально на Dec 2024)
    # Полный список: https://openrouter.ai/docs/features/provider-routing#provider-list
    # Конкретные провайдеры для модели: https://openrouter.ai/{model}/providers
    POPULAR_PROVIDERS = {
        # Официальные API провайдеры
        "openai": "OpenAI direct API",
        "anthropic": "Anthropic direct API", 
        "google": "Google AI direct API",
        "azure": "Microsoft Azure OpenAI",
        # Инференс-платформы
        "deepinfra": "DeepInfra (fast, cheap)",
        "together": "Together AI",
        "fireworks": "Fireworks AI",
        "lepton": "Lepton AI",
        "mancer": "Mancer (uncensored)",
        # Для OpenAI-совместимых моделей
        "chutes": "Chutes (gpt-oss models)",
        "novita": "Novita AI",
    }
    
    # Параметры которые можно требовать от провайдеров
    # https://openrouter.ai/docs/features/provider-routing#require-parameters
    VALID_REQUIRE_PARAMETERS = [
        "json_schema",      # Structured output support
        "tools",            # Function calling support
        "temperature",      # Temperature control
        "top_p",            # Top-p sampling
        "top_k",            # Top-k sampling
        "frequency_penalty",
        "presence_penalty",
        "repetition_penalty",
        "min_p",
        "top_a",
    ]

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-4o-mini",
        timeout: float = 300.0,
        provider: Optional[str] = None,
        provider_order: Optional[list[str]] = None,
        allow_fallbacks: bool = True,
        require_parameters: Optional[list[str]] = None,
    ):
        """
        Инициализация OpenRouter провайдера.

        Args:
            api_key: API ключ OpenRouter
            model: Название модели (например, openai/gpt-4o-mini)
            timeout: Таймаут запросов в секундах
            provider: Конкретный провайдер для использования (например, "azure")
            provider_order: Список провайдеров в порядке приоритета (например, ["azure", "openai"])
            allow_fallbacks: Разрешать ли fallback на другие провайдеры при ошибках
            require_parameters: Параметры которые должен поддерживать провайдер (например, ["json_schema"])
        """
        if not api_key:
            raise ValueError("OpenRouter API key is required")
        
        self.api_key = api_key
        self.model = model
        self.config = self.MODEL_CONFIGS.get(model, self.DEFAULT_CONFIG)
        self.client = httpx.AsyncClient(timeout=timeout)
        
        # Provider routing configuration
        self.provider = provider
        self.provider_order = provider_order
        self.allow_fallbacks = allow_fallbacks
        self.require_parameters = require_parameters
        
        # Usage tracking
        self.usage_stats = LLMUsageStats()
        
        # Log provider config if set
        if provider or provider_order or require_parameters:
            routing_info = []
            if provider:
                routing_info.append(f"provider={provider}")
            if provider_order:
                routing_info.append(f"order={provider_order}")
            if require_parameters:
                routing_info.append(f"require={require_parameters}")
            logger.info(f"OpenRouter routing: {', '.join(routing_info)}")

    def _is_transient_error(self, error_msg: str) -> bool:
        """Check if error is transient and should be retried."""
        error_lower = error_msg.lower()
        return any(pattern in error_lower for pattern in self.TRANSIENT_ERROR_PATTERNS)
    
    def _build_provider_config(self, require_structured: bool = False) -> Optional[dict]:
        """
        Построить конфигурацию provider routing для запроса.
        
        Args:
            require_structured: Требовать поддержку json_schema от провайдера
        
        Returns:
            dict с настройками провайдера или None если не указаны
        """
        has_routing = self.provider or self.provider_order
        has_require = self.require_parameters or require_structured
        
        if not has_routing and not has_require:
            return None
        
        config = {}
        
        # Порядок провайдеров
        if self.provider:
            config["order"] = [self.provider]
        elif self.provider_order:
            config["order"] = self.provider_order
        
        # Fallback настройка
        if has_routing:
            config["allow_fallbacks"] = self.allow_fallbacks
        
        # require_parameters = true фильтрует провайдеров по поддержке параметров запроса
        # (например response_format.type: json_schema)
        if require_structured or self.require_parameters:
            config["require_parameters"] = True
        
        return config

    def _log_retry(self, retry_state) -> None:
        """Log retry attempt with console output."""
        attempt = retry_state.attempt_number
        exc = retry_state.outcome.exception()
        wait_time = retry_state.next_action.sleep if retry_state.next_action else 0
        
        retry_msg = f"OpenRouter error (attempt {attempt}/{self.MAX_RETRIES}): {exc}. Retrying in {wait_time:.1f}s..."
        logger.warning(retry_msg)
        console.print(f"[bold red]⚠️  {retry_msg}[/bold red]")

    def _build_messages(self, prompt: str, system: Optional[str] = None) -> list[dict]:
        """Build messages array for API request."""
        from .prompts import SYSTEM_PROMPT
        
        messages = []
        system_content = system or SYSTEM_PROMPT
        if system_content:
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_headers(self) -> dict:
        """Build HTTP headers for API request."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/open-jobs-searcher",
            "X-Title": "Open Jobs Searcher",
        }

    async def _make_request(self, payload: dict) -> dict:
        """
        Make HTTP request to OpenRouter API.
        
        Args:
            payload: Request payload
            
        Returns:
            Parsed JSON response
            
        Raises:
            OpenRouterRetryableError: On transient errors (will be retried)
            RuntimeError: On permanent errors
        """
        headers = self._build_headers()
        provider_info = payload.get("provider", {}).get("order", ["default"])[0] if payload.get("provider") else "default"
        logger.debug(f"Starting OpenRouter request to {self.model} via {provider_info}...")
        
        try:
            response = await self.client.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            )
            logger.debug(f"OpenRouter response received: HTTP {response.status_code}")
            response.raise_for_status()
            data = response.json()
            
            # Check for errors in response body
            if data.get("error"):
                error_data = data["error"]
                error_msg = error_data.get("message", "Unknown error")
                error_code = error_data.get("code", "")
                error_type = error_data.get("type", "")
                
                full_error = error_msg
                if error_code:
                    full_error = f"[{error_code}] {full_error}"
                if error_type:
                    full_error = f"{full_error} (type: {error_type})"
                
                logger.debug(f"OpenRouter error response: {error_data}")
                
                if self._is_transient_error(error_msg):
                    raise OpenRouterRetryableError(full_error)
                raise RuntimeError(f"OpenRouter API error: {full_error}")
            
            return data
            
        except httpx.HTTPStatusError as e:
            error_body = e.response.text[:500]
            error_msg = f"HTTP {e.response.status_code}: {error_body}"
            logger.debug(f"OpenRouter HTTP error: status={e.response.status_code}, body={error_body}")
            
            if e.response.status_code >= 500:
                raise OpenRouterRetryableError(error_msg) from e
            raise RuntimeError(f"OpenRouter API error: {error_msg}") from e
            
        except httpx.ConnectError as e:
            raise OpenRouterRetryableError(f"Connection error: {e}") from e
            
        except httpx.ReadTimeout as e:
            raise OpenRouterRetryableError(f"Timeout: {e}") from e

    def _track_usage(self, data: dict, elapsed: float, json_mode: bool = False) -> None:
        """Track usage statistics from API response."""
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        # OpenRouter returns cost in usage.total_cost (in USD)
        # Fallback: calculate from known model prices
        cost_usd = usage.get("total_cost", 0.0)
        if cost_usd == 0.0 and (prompt_tokens or completion_tokens):
            cost_usd = self._estimate_cost(prompt_tokens, completion_tokens)
        
        self.usage_stats.add_call(prompt_tokens, completion_tokens, elapsed, cost_usd)
        
        mode = "JSON" if json_mode else "text"
        logger.debug(
            f"LLM {mode} call: {prompt_tokens}+{completion_tokens} tokens, "
            f"{elapsed:.2f}s, model={self.model}"
        )
    
    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost based on known model pricing (USD per 1M tokens)."""
        # Prices as of Dec 2024: https://openrouter.ai/models
        MODEL_PRICES = {
            "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "openai/gpt-4o": {"input": 2.50, "output": 10.00},
            "openai/gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},
            "anthropic/claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
            "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
            "google/gemini-flash-1.5": {"input": 0.075, "output": 0.30},
        }
        
        prices = MODEL_PRICES.get(self.model, {"input": 0.50, "output": 1.50})  # default fallback
        
        input_cost = (prompt_tokens / 1_000_000) * prices["input"]
        output_cost = (completion_tokens / 1_000_000) * prices["output"]
        
        return input_cost + output_cost

    def _extract_content(self, data: dict) -> str:
        """Extract text content from API response."""
        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            return message.get("content", "")
        return ""
    
    def _log_provider_used(self, data: dict) -> None:
        """Log which provider actually handled the request."""
        # OpenRouter returns provider info in the response
        # Either in 'model' field suffix or 'provider' field
        model_used = data.get("model", "")
        provider_name = data.get("provider", "")
        
        if provider_name:
            logger.debug(f"Request handled by provider: {provider_name}")
        elif "/" in model_used and ":" in model_used:
            # Format: "openai/gpt-4o-mini:provider-slug"
            provider_slug = model_used.split(":")[-1]
            logger.debug(f"Request handled by provider: {provider_slug}")

    @retry(
        stop=stop_after_attempt(3),  # MAX_RETRIES
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(OpenRouterRetryableError),
        before_sleep=lambda rs: OpenRouterProvider._log_retry(rs.args[0], rs),
        reraise=True,
    )
    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate response via OpenRouter API with automatic retry on transient errors."""
        messages = self._build_messages(prompt, system)
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config["temperature"],
            "max_tokens": self.config["max_tokens"],
        }
        
        provider_config = self._build_provider_config()
        if provider_config:
            payload["provider"] = provider_config

        start_time = time.perf_counter()
        
        try:
            data = await self._make_request(payload)
            elapsed = time.perf_counter() - start_time
            
            self._track_usage(data, elapsed)
            self._log_provider_used(data)
            return self._extract_content(data)
            
        except OpenRouterRetryableError:
            raise  # Let tenacity handle it

    @retry(
        stop=stop_after_attempt(3),  # MAX_RETRIES
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(OpenRouterRetryableError),
        before_sleep=lambda rs: OpenRouterProvider._log_retry(rs.args[0], rs),
        reraise=True,
    )
    async def complete_json(self, prompt: str, system: Optional[str] = None) -> dict | list:
        """
        Generate JSON response via OpenRouter API with structured output.
        
        Uses response_format={"type": "json_object"} for guaranteed valid JSON.
        Includes automatic retry on transient errors.
        
        Args:
            prompt: User prompt (should explicitly request JSON)
            system: System prompt (optional)
            
        Returns:
            Parsed JSON (dict or list)
        """
        messages = self._build_messages(prompt, system)
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config["temperature"],
            "max_tokens": self.config["max_tokens"],
            "response_format": {"type": "json_object"},
        }
        
        provider_config = self._build_provider_config()
        if provider_config:
            payload["provider"] = provider_config

        start_time = time.perf_counter()
        
        try:
            data = await self._make_request(payload)
            elapsed = time.perf_counter() - start_time
            
            self._track_usage(data, elapsed, json_mode=True)
            self._log_provider_used(data)
            
            content = self._extract_content(data)
            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parse failed despite response_format: {e}")
                    logger.debug(f"Raw content (first 500 chars): {content[:500]}")
                    # Fallback to extract_json for malformed responses
                    from .html_utils import extract_json
                    return extract_json(content)
            
            return {}
            
        except OpenRouterRetryableError:
            raise  # Let tenacity handle it

    # Models that support json_schema (structured output)
    STRUCTURED_OUTPUT_MODELS = {
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-4o-2024-08-06",
        "openai/gpt-4o-mini-2024-07-18",
    }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(OpenRouterRetryableError),
        before_sleep=lambda rs: OpenRouterProvider._log_retry(rs.args[0], rs),
        reraise=True,
    )
    async def complete_structured(
        self, 
        prompt: str, 
        schema: type[T],
        system: Optional[str] = None
    ) -> T:
        """
        Generate response matching Pydantic schema via OpenRouter API.
        
        Uses response_format={"type": "json_schema"} for guaranteed schema compliance.
        Falls back to json_object mode for models that don't support json_schema.
        
        Args:
            prompt: User prompt
            schema: Pydantic model class defining the response structure
            system: System prompt (optional)
            
        Returns:
            Parsed and validated Pydantic model instance
        """
        messages = self._build_messages(prompt, system)
        
        # Check if model supports json_schema
        use_json_schema = self.model in self.STRUCTURED_OUTPUT_MODELS
        
        if use_json_schema:
            # Use strict json_schema mode
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema()
                }
            }
            logger.debug(f"Using json_schema mode for {schema.__name__}")
        else:
            # Fallback to json_object mode
            response_format = {"type": "json_object"}
            logger.debug(f"Model {self.model} doesn't support json_schema, using json_object fallback")
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config["temperature"],
            "max_tokens": self.config["max_tokens"],
            "response_format": response_format,
        }
        
        # Требуем json_schema от провайдера только если используем structured output
        provider_config = self._build_provider_config(require_structured=use_json_schema)
        if provider_config:
            payload["provider"] = provider_config

        start_time = time.perf_counter()
        
        try:
            data = await self._make_request(payload)
            elapsed = time.perf_counter() - start_time
            
            self._track_usage(data, elapsed, json_mode=True)
            
            # Log actual provider used (OpenRouter returns it in response)
            self._log_provider_used(data)
            
            content = self._extract_content(data)
            if content:
                # Parse and validate with Pydantic
                return schema.model_validate_json(content)
            
            # Return empty instance if no content
            return schema()
            
        except OpenRouterRetryableError:
            raise  # Let tenacity handle it

    def get_usage_summary(self) -> str:
        """Get human-readable usage summary."""
        return self.usage_stats.summary()
    
    async def close(self):
        """Закрыть HTTP клиент."""
        if self.usage_stats.total_calls > 0:
            logger.info(self.usage_stats.summary())
        await self.client.aclose()

