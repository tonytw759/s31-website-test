"""
S31 網站自動化測試
第二階段：公開網站、會員登入、管理員角色及客人前台驗證

注意：
- 使用 GitHub Secrets 取得測試帳號密碼
- 不建立訂單
- 不修改付款或退款
- 不執行真實物流操作
"""

import argparse
import datetime
import json
import os
import re
import sys

from pathlib import Path
from bs4 import BeautifulSoup


BANNED = [
    r"Google Apps Script 網址",
    r"清理預設或殘留測試資料",
    r"確認不再加單[・·]統整匯款金額",
    r"出貨滿\s*10\s*日自動",
]

IDS = [
    "topNavBtnHome",
    "topNavBtnLogin",
    "topNavBtnOrders",
    "admTab_orders",
    "admTab_products",
    "admTab_analytics",
    "admOrdTab_pending",
    "admOrdTab_bought",
    "admOrdTab_packing",
    "admOrdTab_shipped",
    "admOrdTab_completed",
]


def result(name, ok, detail=""):
    return {
        "test": name,
        "status": "PASS" if ok else "FAIL",
        "detail": detail,
    }


def blocked(name, detail=""):
    return {
        "test": name,
        "status": "BLOCKED",
        "detail": detail,
    }


def static_check(html):
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "template"]):
        element.decompose()

    visible = soup.get_text(" ", strip=True)

    results = []

    for pattern in BANNED:
        results.append(
            result(
                "舊文字不存在: " + pattern,
                not bool(re.search(pattern, visible, re.I)),
            )
        )

    for element_id in IDS:
        results.append(
            result(
                "必要介面 ID: " + element_id,
                soup.find(id=element_id) is not None,
            )
        )

    return results


def wait_for_login(page):
    """
    等待 Supabase 使用者登入完成。
    """

    page.wait_for_function(
        """
        () => {
            return (
                typeof s31SupabaseUser !== 'undefined' &&
                !!s31SupabaseUser &&
                typeof memberToken !== 'undefined' &&
                !!memberToken
            );
        }
        """,
        timeout=30000,
    )


def wait_for_admin(page):
    """
    等待管理員角色完成載入。
    """

    try:
        page.wait_for_function(
            """
            () => {
                return (
                    typeof s31IsAdmin !== 'undefined' &&
                    !!s31IsAdmin
                );
            }
            """,
            timeout=20000,
        )

        return True

    except Exception:
        return False


def switch_to_customer(page):
    """
    管理員登入後，嘗試切換客人前台。
    """

    try:
        customer_button = page.get_by_text(
            "客人前台",
            exact=True,
        )

        if customer_button.count() > 0:
            if customer_button.first.is_visible():
                customer_button.first.click(
                    timeout=10000
                )

                return True

    except Exception:
        pass

    return False


def wait_for_orders_button(page):
    """
    等待登入後的訂單按鈕顯示。

    如果目前在賣家後台，
    先嘗試切換客人前台。
    """

    orders_button = page.locator(
        "#topNavBtnOrders"
    )

    try:
        orders_button.wait_for(
            state="visible",
            timeout=8000,
        )

        return True, "登入後直接顯示"

    except Exception:
        pass

    switched = switch_to_customer(page)

    try:
        orders_button.wait_for(
            state="visible",
            timeout=20000,
        )

        if switched:
            return True, "切換客人前台後顯示"

        return True, "等待介面更新後顯示"

    except Exception:
        return (
            False,
            "登入後等待並嘗試切換客人前台，訂單按鈕仍未顯示",
        )


def run(url):

    from playwright.sync_api import sync_playwright

    results = []

    username = os.getenv(
        "S31_TEST_USERNAME",
        "",
    )

    password = os.getenv(
        "S31_TEST_PASSWORD",
        "",
    )

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 390,
                "height": 844,
            },
            locale="zh-TW",
        )

        page.on(
            "dialog",
            lambda dialog: dialog.accept(),
        )

        errors = []

        page.on(
            "pageerror",
            lambda error: errors.append(
                str(error)
            ),
        )

        try:

            # ==================================
            # 第一階段：公開網站
            # ==================================

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            results.append(
                result(
                    "首頁 HTTP 200",
                    bool(
                        response and response.ok
                    ),
                    str(response.status)
                    if response
                    else "無回應",
                )
            )

            page.wait_for_timeout(3500)

            results += static_check(
                page.content()
            )

            results.append(
                result(
                    "未登入首頁可見",
                    page.locator(
                        "#topNavBtnHome"
                    ).is_visible(),
                )
            )

            results.append(
                result(
                    "未登入登入按鈕可見",
                    page.locator(
                        "#topNavBtnLogin"
                    ).is_visible(),
                )
            )

            results.append(
                result(
                    "未登入我的訂單按鈕存在（允許隱藏）",
                    page.locator(
                        "#topNavBtnOrders"
                    ).count() > 0,
                )
            )

            # 未登入手機截圖

            page.screenshot(
                path="s31_mobile.png",
                full_page=True,
            )

            # 未登入桌面截圖

            page.set_viewport_size(
                {
                    "width": 1365,
                    "height": 900,
                }
            )

            page.screenshot(
                path="s31_desktop.png",
                full_page=True,
            )

            results.append(
                result(
                    "手機及桌面截圖",
                    True,
                )
            )

            # ==================================
            # 第二階段：登入測試
            # ==================================

            if not username or not password:

                results.append(
                    blocked(
                        "登入驗證",
                        "尚未設定 GitHub Secrets",
                    )
                )

            else:

                page.set_viewport_size(
                    {
                        "width": 390,
                        "height": 844,
                    }
                )

                page.locator(
                    "#topNavBtnLogin"
                ).click(
                    timeout=10000
                )

                page.locator(
                    "#memberModal"
                ).wait_for(
                    state="visible",
                    timeout=10000,
                )

                page.evaluate(
                    "switchAuthModalTab('account')"
                )

                page.locator(
                    "#loginAccInput"
                ).fill(username)

                page.locator(
                    "#loginPwdInput"
                ).fill(password)

                page.locator(
                    "#btnSubmitAccLogin"
                ).click(
                    timeout=10000
                )

                # 等待真正登入成功

                try:

                    wait_for_login(page)

                    results.append(
                        result(
                            "Supabase 帳密登入",
                            True,
                        )
                    )

                    # ==========================
                    # 管理員角色驗證
                    # ==========================

                    is_admin = wait_for_admin(
                        page
                    )

                    results.append(
                        result(
                            "管理員角色驗證",
                            is_admin,
                            "管理員"
                            if is_admin
                            else "等待 20 秒仍未取得管理員角色",
                        )
                    )

                    # ==========================
                    # 客人訂單入口驗證
                    # ==========================

                    orders_visible, detail = (
                        wait_for_orders_button(
                            page
                        )
                    )

                    results.append(
                        result(
                            "登入後我的訂單可見",
                            orders_visible,
                            detail,
                        )
                    )

                    # ==========================
                    # 賣家控制列驗證
                    # ==========================

                    seller_bar = page.locator(
                        "#sellerControlBar"
                    )

                    results.append(
                        result(
                            "登入後賣家控制列存在",
                            seller_bar.count() > 0,
                        )
                    )

                except Exception:

                    results.append(
                        result(
                            "Supabase 帳密登入",
                            False,
                            "30 秒內未取得登入狀態",
                        )
                    )

            # ==================================
            # JavaScript 錯誤檢查
            # ==================================

            results.append(
                result(
                    "JavaScript 未捕獲錯誤",
                    not errors,
                    " | ".join(
                        errors[:3]
                    )[:400]
                    if errors
                    else "",
                )
            )

        except Exception as error:

            results.append(
                result(
                    "瀏覽器流程執行",
                    False,
                    str(error).split(
                        "Call log:"
                    )[0][:250],
                )
            )

        finally:

            browser.close()

    return results


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--browser",
        action="store_true",
    )

    parser.add_argument(
        "--url",
        default="https://ssss31.netlify.app/",
    )

    args = parser.parse_args()

    if not args.browser:
        parser.error(
            "請使用 --browser"
        )

    results = run(args.url)

    summary = {
        status: sum(
            item["status"] == status
            for item in results
        )
        for status in [
            "PASS",
            "FAIL",
            "BLOCKED",
        ]
    }

    report = {
        "time": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "results": results,
        "summary": summary,
    }

    Path(
        "s31_qa_report.json"
    ).write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    for item in results:

        print(
            item["status"],
            item["test"],
            item.get("detail", ""),
        )

    print(
        "結果:",
        summary,
    )

    return 1 if (
        summary["FAIL"]
        or summary["BLOCKED"]
    ) else 0


if __name__ == "__main__":
    sys.exit(main())
