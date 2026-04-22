from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Local AI (Ollama)
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str = "ollama"
    ai_model: str = "qwen2.5:7b"

    # WhatsApp / Meta Cloud API (leave empty to run in dev mode without WhatsApp)
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_verify_token: str = "dev"
    to_phone_number: str = ""  # your personal number — reminders are sent here

    # Comma-separated whitelist of numbers whose messages are tracked (E.164 format).
    # e.g. ALLOWED_NUMBERS=+15551234567,+34612345678
    # Leave unset or empty to track messages from ALL numbers.
    allowed_numbers: str = ""

    # Admin
    admin_username: str = "admin"
    admin_password: str = "admin"
    admin_secret_key: str = "dev-secret-key-change-in-production"
    # Optional custom hostname that maps to the /admin UI (e.g. admin.example.com).
    # When set, requests arriving on this host are transparently rewritten to /admin/*.
    admin_hostname: str = ""

    # Dev mode — enables /dev/chat browser UI, skips real WhatsApp API calls
    dev_mode: bool = False

    # App
    log_level: str = "INFO"
    db_path: str = "traick.db"
    batch_size: int = 20
    process_interval_minutes: int = 5
    reminder_interval_minutes: int = 15

    model_config = {"env_file": ".env"}

    @property
    def allowed_number_list(self) -> list[str]:
        """Parsed list of allowed numbers from the comma-separated config string."""
        return [n.strip() for n in self.allowed_numbers.split(",") if n.strip()]


settings = Settings()
