"""S31 site QA: static checks plus Playwright browser smoke checks.
Run: pip install playwright beautifulsoup4; python -m playwright install chromium
     python test_s31.py --html ../S31_完整網站_舊功能徹底移除_20261021.html
     python test_s31.py --url https://ssss31.netlify.app/ --browser
No orders, refunds or destructive actions are submitted by this script.
"""
import argparse, json, re, sys, datetime
from pathlib import Path
from bs4 import BeautifulSoup

BANNED_VISIBLE=[r'Google Apps Script 網址',r'清理預設或殘留測試資料',r'確認不再加單[・·]統整匯款金額',r'出貨滿\s*10\s*日自動']
REQUIRED_IDS=['topNavBtnHome','topNavBtnLogin','topNavBtnOrders','admTab_orders','admTab_products','admTab_analytics','admOrdTab_pending','admOrdTab_bought','admOrdTab_packing','admOrdTab_shipped','admOrdTab_completed']

def static(html):
    soup=BeautifulSoup(html,'html.parser')
    for s in soup(['script','style','template']):s.decompose()
    visible=soup.get_text(' ',strip=True)
    results=[]
    for pat in BANNED_VISIBLE:
        m=re.search(pat,visible,re.I)
        results.append(dict(test='舊文字不存在: '+pat, status='FAIL' if m else 'PASS', detail=m.group(0) if m else ''))
    for id_ in REQUIRED_IDS:
        results.append(dict(test='必要介面 ID: '+id_,status='PASS' if soup.find(id=id_) else 'FAIL'))
    return results

def browser(url, headed=False):
    try:from playwright.sync_api import sync_playwright
    except ImportError:
        return [dict(test='Playwright 安裝',status='BLOCKED',detail='pip install playwright && python -m playwright install chromium')]
    results=[]
    with sync_playwright() as p:
        b=p.chromium.launch(headless=not headed)
        page=b.new_page(viewport={'width':390,'height':844}, locale='zh-TW')
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            r=page.goto(url,wait_until='domcontentloaded',timeout=30000)
            results.append(dict(test='線上首頁 HTTP',status='PASS' if r and r.ok else 'FAIL',detail=str(r.status) if r else '無回應'))
            page.wait_for_timeout(3500)
            results.extend(static(page.content()))
            results.append(dict(test='JavaScript 未捕獲錯誤',status='PASS' if not errors else 'FAIL',detail=' | '.join(errors[:5])))
            for id_ in ['topNavBtnHome','topNavBtnLogin','topNavBtnOrders']:
                loc=page.locator('#'+id_)
                results.append(dict(test='手機版顯示 '+id_,status='PASS' if loc.count() and loc.first.is_visible() else 'FAIL'))
            page.screenshot(path='s31_mobile.png',full_page=True)
            page.set_viewport_size({'width':1365,'height':900})
            page.screenshot(path='s31_desktop.png',full_page=True)
            results.append(dict(test='手機與桌面截圖',status='PASS',detail='s31_mobile.png / s31_desktop.png'))
        except Exception as e:results.append(dict(test='瀏覽器連線/載入',status='BLOCKED',detail=str(e)[:500]))
        finally:b.close()
    return results

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--html');ap.add_argument('--url',default='https://ssss31.netlify.app/');ap.add_argument('--browser',action='store_true');ap.add_argument('--headed',action='store_true');args=ap.parse_args()
    out=[]
    if args.html:out.extend(static(Path(args.html).read_text(encoding='utf-8')))
    if args.browser:out.extend(browser(args.url,args.headed))
    if not out:ap.error('請使用 --html 路徑 或 --browser')
    result={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'url':args.url,'results':out,'summary':{s:sum(x['status']==s for x in out) for s in ('PASS','FAIL','BLOCKED')}}
    Path('s31_qa_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for x in out:print(f"{x['status']:7} {x['test']} {x.get('detail','')}")
    print('結果:',result['summary']);print('報告: s31_qa_report.json')
    return 1 if any(x['status']=='FAIL' for x in out) else 0
if __name__=='__main__':sys.exit(main())
