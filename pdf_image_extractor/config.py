"""Configuration for PDF image extraction filtering."""

from dataclasses import dataclass, field


# Predefined provider base URLs
PROVIDER_BASE_URLS = {
    "openai": None,  # Uses default OpenAI SDK endpoint
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

# Default model names per provider
PROVIDER_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "dashscope": "qwen3-vl-plus",
}


@dataclass
class ImageFilterConfig:
    """Configuration for filtering images during extraction.
    
    All ratio values are relative to page dimensions (0.0 to 1.0).
    All pixel/byte values are absolute minimums.
    """
    
    # Minimum pixel dimensions
    min_width: int = 150
    min_height: int = 150
    
    # Minimum file size in bytes
    min_file_size: int = 3072  # 3KB
    
    # Minimum percentage of page dimensions
    min_page_ratio_width: float = 0.08   # At least 8% of page width
    min_page_ratio_height: float = 0.08  # At least 8% of page height
    
    # Maximum percentage of page dimensions (filter backgrounds)
    max_page_ratio_width: float = 0.95
    max_page_ratio_height: float = 0.95
    
    # Content area margins (skip images in these zones)
    margin_top: float = 0.05     # Skip top 5% of page
    margin_bottom: float = 0.05  # Skip bottom 5% of page
    margin_left: float = 0.02    # Skip left 2% of page
    margin_right: float = 0.02   # Skip right 2% of page
    
    # Vision model filtering (optional, requires API key)
    use_vision_model: bool = False
    vision_api_key: str = ""
    vision_provider: str = "openai"  # "openai" or "dashscope"
    vision_base_url: str = ""  # Custom base URL; auto-set from provider if empty
    vision_model: str = "gpt-4o-mini"

    # Smart content area detection
    use_smart_content_detection: bool = False  # Detect content area from text positions
    
    # Output settings
    output_format: str = "original"  # "original", "png", "jpeg"
    jpeg_quality: int = 95
    
    def merge(self, overrides: dict) -> "ImageFilterConfig":
        """Create a new config with overrides applied.
        
        Raises:
            ValueError: If overrides contain unknown config keys.
        """
        valid_keys = set(self.__dataclass_fields__.keys())
        unknown = set(overrides.keys()) - valid_keys
        if unknown:
            raise ValueError(f"Unknown config keys: {unknown}")
        data = {k: v for k, v in self.__dict__.items()}
        data.update(overrides)
        return ImageFilterConfig(**data)
    
    def resolve_vision_settings(self) -> tuple[str, str]:
        """Resolve the effective base_url and model from provider.
        
        Returns:
            Tuple of (base_url, model). base_url is empty string for OpenAI default.
        """
        provider = self.vision_provider.lower()
        
        # If provider changed but model is still the old default, update model
        model = self.vision_model
        if provider in PROVIDER_DEFAULT_MODELS:
            other_provider = "openai" if provider == "dashscope" else "dashscope"
            if model == PROVIDER_DEFAULT_MODELS.get(other_provider, ""):
                model = PROVIDER_DEFAULT_MODELS[provider]
        
        # Resolve base URL
        base_url = self.vision_base_url
        if not base_url and provider in PROVIDER_BASE_URLS:
            resolved = PROVIDER_BASE_URLS[provider]
            base_url = resolved if resolved else ""
        
        return base_url, model
