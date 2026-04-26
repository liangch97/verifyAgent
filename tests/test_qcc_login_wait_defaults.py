from demos.qcc_login_demo import (
    DEFAULT_LOGIN_ONLY_HOLD_SECONDS,
    DEFAULT_LOGIN_TIMEOUT_SECONDS,
    chromium_launch_args,
    find_chrome,
    has_logged_in_marker,
    is_allowed_qcc_detail_url,
    parse_args,
    wait_for_login_checkpoint,
)


class _FakeBodyLocator:
    def __init__(self, page: "_FakePage") -> None:
        self.page = page

    def inner_text(self, timeout: int = 5000) -> str:
        return self.page.current_text()


class _FakePage:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.index = 0
        self.waits: list[int] = []

    def locator(self, selector: str) -> _FakeBodyLocator:
        assert selector == "body"
        return _FakeBodyLocator(self)

    def current_text(self) -> str:
        return self.texts[min(self.index, len(self.texts) - 1)]

    def wait_for_timeout(self, timeout: int) -> None:
        self.waits.append(timeout)
        if self.index < len(self.texts) - 1:
            self.index += 1


def test_qcc_login_defaults_keep_browser_open(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["qcc_login_demo.py", "华为技术有限公司", "--login-only"])

    args = parse_args()

    assert args.login_only is True
    assert args.hold_seconds == DEFAULT_LOGIN_ONLY_HOLD_SECONDS == 900
    assert args.login_timeout == DEFAULT_LOGIN_TIMEOUT_SECONDS == 900


def test_qcc_reuse_profile_args(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "qcc_login_demo.py",
            "华为技术有限公司",
            "--reuse-profile",
            "--company-url",
            "https://www.qcc.com/firm/6b242b475738f45a4dd180564d029aa9.html",
        ],
    )

    args = parse_args()

    assert args.reuse_profile is True
    assert args.company_url.endswith(".html")


def test_qcc_detail_url_allowlist() -> None:
    assert is_allowed_qcc_detail_url("https://www.qcc.com/firm/6b242b475738f45a4dd180564d029aa9.html")
    assert not is_allowed_qcc_detail_url("https://www.qcc.com/web/search?key=华为")
    assert not is_allowed_qcc_detail_url("https://example.com/firm/6b242b475738f45a4dd180564d029aa9.html")


def test_qcc_browser_executable_env_override(monkeypatch, tmp_path) -> None:
    browser = tmp_path / "chromium"
    browser.write_text("", encoding="utf-8")
    monkeypatch.setenv("QCC_BROWSER_EXECUTABLE", str(browser))
    monkeypatch.setattr("demos.qcc_login_demo.shutil.which", lambda _command: None)

    assert find_chrome() == browser


def test_qcc_browser_executable_from_system_path(monkeypatch, tmp_path) -> None:
    browser = tmp_path / "chromium"
    browser.write_text("", encoding="utf-8")
    for key in [
        "QCC_BROWSER_EXECUTABLE",
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE",
        "CHROMIUM_PATH",
        "CHROME_PATH",
        "BROWSER_EXECUTABLE",
    ]:
        monkeypatch.delenv(key, raising=False)

    def fake_exists(self):
        return False

    monkeypatch.setattr("demos.qcc_login_demo.Path.exists", fake_exists)
    monkeypatch.setattr("demos.qcc_login_demo.shutil.which", lambda command: str(browser) if command == "chromium" else None)

    assert find_chrome() == browser


def test_qcc_linux_root_chromium_args(monkeypatch) -> None:
    monkeypatch.setattr("demos.qcc_login_demo.sys.platform", "linux")
    monkeypatch.setattr("demos.qcc_login_demo.os.geteuid", lambda: 0, raising=False)

    assert "--disable-dev-shm-usage" in chromium_launch_args()
    assert "--no-sandbox" in chromium_launch_args()


def test_qcc_logged_in_marker() -> None:
    assert has_logged_in_marker("退出")
    assert has_logged_in_marker("消息\n会员中心\n我的关注")
    assert not has_logged_in_marker("扫码登录\n消息")
    assert not has_logged_in_marker("免费注册\n登录\n消息\n企业套餐")


def test_qcc_login_checkpoint_waits_until_real_login(tmp_path) -> None:
    page = _FakePage(
        [
            "全国企业信用查询系统\n免费注册\n扫码登录\n微信登录",
            "打开 企查查APP 或 微信扫一扫登录\n短信/密码登录",
            "消息\n会员中心\n我的关注",
        ]
    )

    result = wait_for_login_checkpoint(
        page=page,
        timeout_seconds=30,
        log_path=tmp_path / "run.md",
        latest_log_path=tmp_path / "latest.md",
        latest_json_path=tmp_path / "latest.json",
        company_name="华为技术有限公司",
        login_screenshot=tmp_path / "login.png",
        result_screenshot=None,
        status_on_timeout="login_not_detected",
        note_on_timeout="timeout",
    )

    assert result is True
    assert page.waits == [3000, 3000]
    assert not (tmp_path / "latest.json").exists()
