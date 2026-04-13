from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Local AI (Ollama)
    ollama_base_url: str = "http://localhost:11434"
    ai_model: str = "qwen2.5:7b"

    # WhatsApp / Meta Cloud API
    whatsapp_token: str
    whatsapp_phone_number_id: str
    whatsapp_business_account_id: str
    whatsapp_verify_token: str
    to_phone_number: str  # your personal number — reminders are sent here

    # Comma-separated whitelist of numbers whose messages are tracked (E.164 format).
    # e.g. ALLOWED_NUMBERS=+15551234567,+34612345678
    # Leave unset or empty to track messages from ALL numbers.
    allowed_numbers: str = ""

    # Admin
    admin_username: str = "admin"
    admin_password: str
    admin_secret_key: str

    # App
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
