"""S31 browser QA. Login smoke test; no orders/payments/refunds are submitted."""
import argparse, datetime, json, os, re, sys
from pathlib import Path
from bs4 import BeautifulSoup

BANNED=[r'Google Apps Script 網址',r'清理預設或殘留測試資料',r'確認不再加單[・·]統整匯款金額',r'出貨滿\s*10\s*日自動']
IDS=['topNavBtnHome','topNavBtnLogin','topNavBtnOrders','admTab_orders','admTab_products','admTab_analytics','admOrdTab_pending','admOrdTab_bought','admOrdTab_packing','admOrdTab_shipped','admOrdTab_completed']

def result(name, ok, detail=''):
    return {'test':name,'status':'PASS' if ok else 'FAIL','detail':detail}

def static(html):
    soup=BeautifulSoup(html,'html.parser')
    for s in soup(['script','style','template']):s.decompose()
    visible=soup.get_text(' ',strip=True)
    return [result('舊文字不存在: '+p,not re.search(p,visible,re.I)) for p in BANNED]+[result('必要介面 ID: '+i,soup.find(id=i) is not None) for i in IDS]

def run(url):
    from playwright.sync_api import sync_playwright
    out=[]
    username=os.getenv('S31_TEST_USERNAME','')
    password=os.getenv('S31_TEST_PASSWORD','')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':390,'height':844},locale='zh-TW')
        page.on('dialog',lambda d:d.accept())
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
            out.append(result('首頁 HTTP 200',bool(response and response.ok),str(response.status) if response else '無回應'))
            page.wait_for_timeout(3500)
            out+=static(page.content())
            out.append(result('未登入首頁可見',page.locator('#topNavBtnHome').is_visible()))
            out.append(result('未登入登入按鈕可見',page.locator('#topNavBtnLogin').is_visible()))
            # Orders is intentionally hidden when logged out: do not require visibility.
            out.append(result('未登入我的訂單按鈕存在（允許隱藏）',page.locator('#topNavBtnOrders').count()>0))
            page.screenshot(path='s31_mobile.png',full_page=True)
            page.set_viewport_size({'width':1365,'height':900})
            page.screenshot(path='s31_desktop.png',full_page=True)
            out.append(result('手機及桌面截圖',True))
            if not username or not password:
                out.append({'test':'登入驗證','status':'BLOCKED','detail':'未提供 S31_TEST_USERNAME / S31_TEST_PASSWORD Secrets'})
            else:
                page.set_viewport_size({'width':390,'height':844})
                page.locator('#topNavBtnLogin').click(timeout=10000)
                page.locator('#memberModal').wait_for(state='visible',timeout=10000)
                page.evaluate("switchAuthModalTab('account')")
                page.locator('#loginAccInput').fill(username)
                page.locator('#loginPwdInput').fill(password)
                page.locator('#btnSubmitAccLogin').click(timeout=10000)
                # Supabase async authentication. Never log username/password, request payloads, or authenticated screenshots.
                try:
                    page.wait_for_function("typeof s31SupabaseUser !== 'undefined' && !!s31SupabaseUser && typeof memberToken !== 'undefined' && !!memberToken",timeout=20000)
                    out.append(result('Supabase 帳密登入',True))
                    out.append(result('登入後我的訂單可見',page.locator('#topNavBtnOrders').is_visible()))
                    is_admin=page.evaluate("typeof s31IsAdmin !== 'undefined' && !!s31IsAdmin")
                    out.append(result('管理員角色驗證',is_admin,'管理員' if is_admin else '未取得管理員角色'))
                    out.append(result('登入後賣家控制列存在',page.locator('#sellerControlBar').count()>0))
                except Exception:
                    # Deliberately no screenshots / response body on auth failure.
                    out.append(result('Supabase 帳密登入',False,'20 秒內未取得登入狀態；請檢查帳密、Supabase Auth 或網站登入錯誤'))
            out.append(result('JavaScript 未捕獲錯誤',not errors,' | '.join(errors[:3])[:400] if errors else ''))
        except Exception as e:
            out.append(result('瀏覽器流程執行',False,str(e).split('Call log:')[0][:250]))
        finally:
            browser.close()
    return out

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--browser',action='store_true');parser.add_argument('--url',default='https://ssss31.netlify.app/');args=parser.parse_args()
    if not args.browser:parser.error('請使用 --browser')
    out=run(args.url)
    summary={s:sum(r['status']==s for r in out) for s in ['PASS','FAIL','BLOCKED']}
    Path('s31_qa_report.json').write_text(json.dumps({'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':out,'summary':summary},ensure_ascii=False,indent=2),encoding='utf-8')
    for r in out:print(r['status'],r['test'],r.get('detail',''))
    print('結果:',summary)
    return 1 if summary['FAIL'] or summary['BLOCKED'] else 0
if __name__=='__main__':sys.exit(main())
