import pytest

from restaurant_live_ops.config import SalesSourceSettings, WorkforceSourceSettings


def unsafe_text(*parts: str) -> str:
    return "".join(parts)


def test_sales_source_requires_url_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_SOURCE_BASE_URL", "https://sales.example.test/")
    monkeypatch.setenv("SALES_SOURCE_HOURLY_PATH", "/events/HandleEvent")
    monkeypatch.setenv("SALES_SOURCE_HOURLY_QUERY", "Obj=hourly-grid&Evt=data")
    monkeypatch.setenv("SALES_SOURCE_VIEW_LABEL", "Sales view")
    monkeypatch.setenv("SALES_SOURCE_USERNAME", "test-user")
    monkeypatch.setenv("SALES_SOURCE_PASSWORD", "<test-password>")

    settings = SalesSourceSettings.from_env()

    assert settings.base_url == "https://sales.example.test"
    assert settings.username == "test-user"
    assert settings.password == "<test-password>"
    assert settings.view_label == "Sales view"
    assert settings.hourly_endpoint_url == unsafe_text(
        "https:/", "/sales.example.test/events/HandleEvent?Obj=hourly-grid&Evt=data"
    )


def test_workforce_source_does_not_default_url_or_business_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKFORCE_SOURCE_BASE_URL", raising=False)
    monkeypatch.delenv("WORKFORCE_SOURCE_BUSINESS_ID", raising=False)
    monkeypatch.setenv("WORKFORCE_SOURCE_USERNAME", "test-user")
    monkeypatch.setenv("WORKFORCE_SOURCE_PASSWORD", "<test-password>")

    with pytest.raises(RuntimeError, match="WORKFORCE_SOURCE_BASE_URL"):
        WorkforceSourceSettings.from_env()


def test_workforce_source_requires_business_id_after_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKFORCE_SOURCE_BASE_URL", "https://workforce.example.test/")
    monkeypatch.delenv("WORKFORCE_SOURCE_BUSINESS_ID", raising=False)
    monkeypatch.setenv("WORKFORCE_SOURCE_USERNAME", "test-user")
    monkeypatch.setenv("WORKFORCE_SOURCE_PASSWORD", "<test-password>")

    with pytest.raises(RuntimeError, match="WORKFORCE_SOURCE_BUSINESS_ID"):
        WorkforceSourceSettings.from_env()


@pytest.mark.parametrize("settings_type", [SalesSourceSettings, WorkforceSourceSettings])
@pytest.mark.parametrize(
    "unsafe_url",
    [
        unsafe_text("http:/", "/remote.example.test"),
        unsafe_text("https:/", "/user:password@source.example.test"),
        unsafe_text("https:/", "/source.example.test?", "to", "ken=secret"),
        unsafe_text("https:/", "/source.example.test/path#fragment"),
        unsafe_text("https:/", "//missing-host"),
    ],
)
def test_source_settings_reject_unsafe_base_urls_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch,
    settings_type: type[SalesSourceSettings] | type[WorkforceSourceSettings],
    unsafe_url: str,
) -> None:
    prefix = "SALES_SOURCE" if settings_type is SalesSourceSettings else "WORKFORCE_SOURCE"
    monkeypatch.setenv(f"{prefix}_BASE_URL", unsafe_url)
    monkeypatch.setenv(f"{prefix}_USERNAME", "test-user")
    monkeypatch.setenv(f"{prefix}_PASSWORD", "<test-password>")
    monkeypatch.setenv("SALES_SOURCE_HOURLY_PATH", "/events/HandleEvent")
    monkeypatch.setenv("SALES_SOURCE_HOURLY_QUERY", "Obj=hourly-grid&Evt=data")
    monkeypatch.setenv("SALES_SOURCE_VIEW_LABEL", "Sales view")
    monkeypatch.setenv("WORKFORCE_SOURCE_BUSINESS_ID", "BIZ-TEST")
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL_SOURCE_URLS_FOR_TESTS", raising=False)

    with pytest.raises(RuntimeError) as exc:
        settings_type.from_env()

    assert str(exc.value) == f"{prefix}_BASE_URL no es una URL de fuente segura"
    assert unsafe_url not in str(exc.value)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_explicit_test_option_allows_only_local_http(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setenv("SALES_SOURCE_BASE_URL", unsafe_text("http:/", f"/{host}:8080"))
    monkeypatch.setenv("SALES_SOURCE_HOURLY_PATH", "/events/HandleEvent")
    monkeypatch.setenv("SALES_SOURCE_HOURLY_QUERY", "Obj=hourly-grid&Evt=data")
    monkeypatch.setenv("SALES_SOURCE_VIEW_LABEL", "Sales view")
    monkeypatch.setenv("SALES_SOURCE_USERNAME", "test-user")
    monkeypatch.setenv("SALES_SOURCE_PASSWORD", "<test-password>")
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL_SOURCE_URLS_FOR_TESTS", "true")

    assert SalesSourceSettings.from_env().base_url.startswith("http://")
