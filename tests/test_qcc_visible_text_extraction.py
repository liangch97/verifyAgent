import json
from pathlib import Path

from demos.qcc_contract_review_demo import is_usable_company_check
from demos.qcc_login_demo import build_company_check_draft, detect_blocked_reason, write_run_log


def test_qcc_credit_code_403_is_not_access_block() -> None:
    text = "\n".join(
        [
            "华为技术有限公司 存续",
            "复制",
            "高新技术企业绿色制造企业技术中心重点实验室技术创新示范企业",
            "法定代表人：赵明路 注册资本：4104113.182万元 成立日期：1987-09-15 统一社会信用代码：914403001922038216复制",
            "电话：0755-28780808 邮箱：catherine.he@huawei.com 官网：",
            "www.huawei.com/cn",
            "地址：深圳市龙岗区坂田华为总部办公楼复制",
        ]
    )

    assert detect_blocked_reason(text) == ""

    draft = build_company_check_draft("华为技术有限公司", text, Path("qcc.png"), "")
    assert draft["extraction_mode"] == "qcc_exact_search_result_card"
    assert draft["party_a"]["name"] == "华为技术有限公司"
    assert draft["party_a"]["company_status"] == "存续"
    assert draft["party_a"]["legal_rep"] == "赵明路"
    assert draft["party_a"]["credit_code"] == "914403001922038216"
    assert draft["party_a"]["registered_address"] == "深圳市龙岗区坂田华为总部办公楼"


def test_qcc_extracts_visible_company_people_for_related_review() -> None:
    text = "\n".join(
        [
            "华为技术有限公司 存续",
            "法定代表人：赵明路 注册资本：4104113.182万元 成立日期：1987-09-15 统一社会信用代码：914403001922038216复制",
            "地址：深圳市龙岗区坂田华为总部办公楼复制",
            "董事长",
            "梁华",
            "副董事长",
            "徐直军",
            "副董事长",
            "孟晚舟",
            "股东： 华为投资控股有限公司",
        ]
    )

    draft = build_company_check_draft("华为技术有限公司", text, Path("qcc.png"), "")

    assert {"name": "梁华", "title": "董事长"} in draft["party_a"]["directors"]
    assert {"name": "徐直军", "title": "副董事长"} in draft["party_a"]["directors"]
    assert {"name": "孟晚舟", "title": "副董事长"} in draft["party_a"]["directors"]
    assert {"name": "华为投资控股有限公司", "type": "股东"} in draft["party_a"]["shareholders"]


def test_qcc_real_access_block_still_detected() -> None:
    assert detect_blocked_reason("HTTP 403 Forbidden") != ""
    assert detect_blocked_reason("错误403：访问受限") != ""


def test_qcc_login_page_does_not_leak_footer_address(tmp_path: Path) -> None:
    text = "\n".join(
        [
            "缔造有远见的商业传奇",
            "全国企业信用查询系统",
            "免费注册",
            "扫码登录",
            "微信登录",
            "打开 企查查APP 或 微信扫一扫登录",
            "客服电话：400-928-2212",
            "地址：江苏省苏州市工业园区汇智街8号",
        ]
    )

    draft = build_company_check_draft("华为技术有限公司", text, Path("qcc.png"), "")
    assert draft["extraction_mode"] == "no_target_company_visible"
    assert draft["party_a"]["name"] == ""
    assert draft["party_a"]["registered_address"] == ""

    draft_path = tmp_path / "company_check_draft.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    assert is_usable_company_check(draft_path) is False


def test_qcc_address_only_draft_is_not_usable_for_auto_review(tmp_path: Path) -> None:
    draft = {
        "extraction_mode": "qcc_generic_visible_text",
        "blocked_reason": "",
        "party_a": {
            "name": "华为技术有限公司",
            "registered_address": "深圳市龙岗区坂田华为总部办公楼",
        },
    }
    draft_path = tmp_path / "company_check_draft.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")

    assert is_usable_company_check(draft_path) is False


def test_qcc_run_log_writes_dashboard_preview_html(tmp_path: Path) -> None:
    login_screenshot = tmp_path / "login.png"
    result_screenshot = tmp_path / "result.png"
    login_screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfake-login")
    result_screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfake-result")

    log_path = tmp_path / "qcc_login_demo_run_20260426_120000.md"
    latest_log_path = tmp_path / "qcc_login_demo_latest.md"
    latest_json_path = tmp_path / "qcc_login_demo_latest.json"
    draft_json_path = tmp_path / "company_check_draft.json"

    write_run_log(
        log_path=log_path,
        latest_log_path=latest_log_path,
        latest_json_path=latest_json_path,
        company_name="华为技术有限公司",
        login_screenshot=login_screenshot,
        result_screenshot=result_screenshot,
        draft_json_path=draft_json_path,
        status="company_page_captured",
        note="test note",
        blocked_reason="",
    )

    payload = json.loads(latest_json_path.read_text(encoding="utf-8"))
    preview_path = Path(payload["preview_html"])
    latest_preview_path = Path(payload["latest_preview_html"])

    assert preview_path.exists()
    assert latest_preview_path.exists()
    assert latest_preview_path == latest_log_path.with_suffix(".html")

    preview_html = latest_preview_path.read_text(encoding="utf-8")
    assert "data:image/png;base64," in preview_html
    assert "登录二维码截图" in preview_html
    assert "查询页面截图" in preview_html
